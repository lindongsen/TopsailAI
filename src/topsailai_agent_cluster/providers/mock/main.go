package main

import (
	"bytes"
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"io"
	"os"
	"os/exec"
	"sort"
	"strings"
	"time"
)

const (
	faultEnvironment  = "AGENT_CLUSTER_MOCK_FAULT"
	helperEnvironment = "AGENT_CLUSTER_MOCK_HELPER"
	fixtureTimeMS     = int64(1700000000000)
)

// mockOptions are the argv-driven knobs the test harness needs.
//
// The Cluster's Generic CLI Adapter sets a child's environment to exactly the
// configured Environment, and the Endpoint factory configures none, so a test
// cannot inject a fault through the environment. argv is the only channel the
// harness controls, so every knob the removed argv fixture exposed is accepted
// here as a flag. The environment fault variable is still honoured for the
// conformance suite, which launches the mock directly.
type mockOptions struct {
	mode               string
	fault              string
	recordFile         string
	discoveryCountFile string
	delayMS            int
	outputSize         int
	failAfterN         int
	alwaysFail         bool
}

// parseOptions reads the argv knobs. Unknown flags are rejected by flag.Parse,
// so a harness that passes a stale flag fails loudly instead of silently
// running with a default.
func parseOptions() mockOptions {
	var options mockOptions
	flag.StringVar(&options.mode, "mode", "one", "discovery document mode: one, mixed, empty or fail")
	flag.StringVar(&options.fault, "fault", "", "deterministic fault to inject, overriding the environment")
	flag.StringVar(&options.recordFile, "record-file", "", "append one JSON record per provider invocation")
	flag.StringVar(&options.discoveryCountFile, "discovery-count-file", "", "durable discovery invocation counter")
	flag.IntVar(&options.delayMS, "delay-ms", 0, "delay execution for evidence tests")
	flag.IntVar(&options.outputSize, "output-size", 0, "pad the output snapshot to this many bytes")
	flag.IntVar(&options.failAfterN, "fail-after-n", -1, "fail discovery after N successful calls; zero fails immediately")
	flag.BoolVar(&options.alwaysFail, "always-fail", false, "fail every discovery call")
	flag.Parse()
	return options
}

// main reads one request and emits one deterministic fixture response.
func main() {
	if os.Getenv(helperEnvironment) == "1" {
		time.Sleep(30 * time.Second)
		return
	}
	options := parseOptions()
	requestDocument, err := io.ReadAll(io.LimitReader(os.Stdin, 1<<20))
	if err != nil {
		writeDiagnostic("read request: %v", err)
		os.Exit(2)
	}
	request, err := decodeRequest(requestDocument)
	if err != nil {
		writeDiagnostic("decode request: %v", err)
		os.Exit(2)
	}
	// argv wins over the environment so a harness can inject a fault without
	// controlling the child's environment.
	fault := options.fault
	if fault == "" {
		fault = os.Getenv(faultEnvironment)
	}
	if fault == "timeout" {
		if err := startHelper(); err != nil {
			writeDiagnostic("start helper: %v", err)
			os.Exit(2)
		}
		time.Sleep(30 * time.Second)
		return
	}
	if fault == "empty-stdout" {
		return
	}
	if fault == "malformed-json" {
		_, _ = io.WriteString(os.Stdout, "{not-json")
		return
	}
	if fault == "oversized-stdout" {
		_, _ = io.WriteString(os.Stdout, strings.Repeat("x", int(request.Budget.MaxStdoutBytes)+1024))
		return
	}
	if fault == "helper-leak" {
		if err := startHelper(); err != nil {
			writeDiagnostic("start helper: %v", err)
			os.Exit(2)
		}
	}
	if request.Function == functionFollowOutput {
		if err := writeStream(request, fault); err != nil {
			writeDiagnostic("write stream: %v", err)
			os.Exit(2)
		}
		return
	}
	response := handleUnary(request, fault, options)
	if fault == "wrong-request-id" {
		response.RequestID = "wrong-request-id"
	}
	if fault == "wrong-version" {
		response.Minor++
	}
	encoded, err := json.Marshal(response)
	if err != nil {
		writeDiagnostic("encode response: %v", err)
		os.Exit(2)
	}
	if fault == "stdout-banner" {
		_, _ = io.WriteString(os.Stdout, "mock provider ready\n")
	}
	if fault == "oversized-stderr" {
		_, _ = io.WriteString(os.Stderr, strings.Repeat("e", int(request.Budget.MaxStderrBytes)+1024))
	}
	_, _ = os.Stdout.Write(encoded)
	if fault == "duplicate-response" {
		_, _ = os.Stdout.Write([]byte("\n"))
		_, _ = os.Stdout.Write(encoded)
	}
	if fault == "exit-result-conflict" {
		os.Exit(7)
	}
}

// decodeRequest enforces the strict public request envelope.
func decodeRequest(data []byte) (request, error) {
	var value request
	decoder := json.NewDecoder(bytes.NewReader(data))
	decoder.DisallowUnknownFields()
	if err := decoder.Decode(&value); err != nil {
		return request{}, err
	}
	var extra any
	if err := decoder.Decode(&extra); !errors.Is(err, io.EOF) {
		if err == nil {
			return request{}, errors.New("extra JSON document")
		}
		return request{}, err
	}
	if value.Protocol != protocolName || value.Major != protocolMajor || value.Minor != protocolMinor {
		return request{}, errors.New("unsupported protocol version")
	}
	if value.RequestID == "" || value.AdapterID == "" || value.Function == "" || len(value.Payload) == 0 {
		return request{}, errors.New("required request field is empty")
	}
	return value, nil
}

// handleUnary dispatches one deterministic unary fixture.
func handleUnary(request request, fault string, options mockOptions) response {
	base := response{version: currentVersion(), RequestID: request.RequestID, OK: true}
	switch request.Function {
	case functionDescribe:
		descriptor := mockDescriptor(fault)
		base.Descriptor = &descriptor
	case functionDiscover:
		observations, discoveryErr := discoveryObservations(options)
		if discoveryErr != nil {
			return failureResponse(request.RequestID, "provider_error", discoveryErr.Error(), "not_applied")
		}
		base.Discovery = &discoveryResult{
			Observations: observations,
			Complete:     true,
			Checkpoint:   "checkpoint-1",
		}
	case functionInspect:
		observation := fixtureObservation()
		base.Inspection = &inspectionResult{Found: true, Live: true, Observation: &observation}
	case functionExecute:
		if options.delayMS > 0 {
			time.Sleep(time.Duration(options.delayMS) * time.Millisecond)
		}
		recordInvocation(options, request, "execute")
		return executeResponse(request, fault)
	case functionQuery:
		if request.Query == nil || request.Query.Version != "v1" || fault == "false-capability" {
			return failureResponse(request.RequestID, "unsupported", "query is unsupported", "not_applied")
		}
		switch request.Query.Name {
		case queryLaunchOptions:
			base.QueryResult = json.RawMessage(`{"profile":{"resource_kind":"launch_profile","provider_resource_key":"launch:mock","display_name":"Mock","revision":"launch-r1"},"projects":[{"name":"mock","path":"/work/mock"}]}`)
		case queryHistoryMessages:
			base.QueryResult = json.RawMessage(`{"rows":[{"resource_kind":"session","provider_resource_key":"session:stable","provider_session_id":"session-1","resumable":true}],"observed_at_ms":1700000000000,"truncated":false}`)
		case queryModelCatalog:
			base.QueryResult = json.RawMessage(`{"profiles":[{"resource_kind":"model_profile","provider_resource_key":"model:mock","provider_display_name":"Mock","current_state":"yes","available":true}],"current_provider_resource_key":"model:mock","observed_at_ms":1700000000000,"truncated":false}`)
		case querySessionMessages:
			base.QueryResult = json.RawMessage(`{"provider_session_id":"session-1","messages":[{"role":"user","content":"hello"}],"message_count":1,"observed_at_ms":1700000000000,"truncated":false}`)
		default:
			return failureResponse(request.RequestID, "unsupported", "query is unsupported", "not_applied")
		}
	case functionQueryCommand:
		base.Result = &operationResult{
			ProviderRequestRef:        "provider-ref-1",
			DeliveryBoundary:          "submitted",
			EffectCertainty:           "acknowledged",
			ProviderOutcome:           "reconciled",
			ProviderResponseTruncated: false,
			StartedAtMS:               fixtureTimeMS,
			FinishedAtMS:              fixtureTimeMS + 1,
		}
	case functionReadOutput:
		recordInvocation(options, request, "output.read")
		content := "mock output\n"
		if options.outputSize > len(content) {
			content += strings.Repeat("x", options.outputSize-len(content))
		}
		base.Output = &outputSnapshot{ObservedAtMS: fixtureTimeMS, Content: content, Complete: true}
	default:
		return failureResponse(request.RequestID, "unsupported", "function is unsupported", "not_applied")
	}
	return base
}

// operationEvidence is the deterministic provider evidence for one operation.
//
// The delivery boundary and outcome are not decoration: the Cluster receipt is
// built from exactly these two fields, so a scenario that asserts "stop request
// sent" needs signal_sent here and a scenario that asserts "delivered" needs
// pipe_written. The values mirror what the removed argv fixture emitted, so a
// migrated scenario keeps asserting the same Cluster behaviour instead of a new
// invented shape.
type operationEvidence struct {
	deliveryBoundary string
	effectCertainty  string
	providerOutcome  string
	providerResponse string
}

// operationEvidenceTable answers every operation the mock advertises.
//
// A missing entry is a deliberate rejection rather than a silent success, so an
// operation that is advertised but not answered cannot pass unnoticed.
var operationEvidenceTable = map[string]operationEvidence{
	"message.send":        {deliveryBoundary: "pipe_written", effectCertainty: "acknowledged", providerOutcome: "submitted", providerResponse: `{"ok":true}`},
	"context.inject":      {deliveryBoundary: "pipe_written", effectCertainty: "acknowledged", providerOutcome: "submitted", providerResponse: `{"ok":true}`},
	"execution.interrupt": {deliveryBoundary: "signal_sent", effectCertainty: "acknowledged", providerOutcome: "submitted", providerResponse: `{"ok":true}`},
	"agent.stop":          {deliveryBoundary: "signal_sent", effectCertainty: "acknowledged", providerOutcome: "submitted", providerResponse: `{"ok":true}`},
	"agent.resume":        {deliveryBoundary: "submitted", effectCertainty: "acknowledged", providerOutcome: "submitted", providerResponse: `{"ok":true}`},
	"agent.start":         {deliveryBoundary: "submitted", effectCertainty: "acknowledged", providerOutcome: "submitted", providerResponse: `{"ok":true}`},
	"agent.drive.start":   {deliveryBoundary: "submitted", effectCertainty: "acknowledged", providerOutcome: "submitted", providerResponse: `{"ok":true}`},
	"agent.drive.stop":    {deliveryBoundary: "signal_sent", effectCertainty: "acknowledged", providerOutcome: "submitted", providerResponse: `{"ok":true}`},
	"agent.model.select":  {deliveryBoundary: "submitted", effectCertainty: "acknowledged", providerOutcome: "submitted", providerResponse: `{"ok":true}`},
	"command.exec":        {deliveryBoundary: "submitted", effectCertainty: "acknowledged", providerOutcome: "succeeded", providerResponse: `{"ok":true}`},
	"workspace.clean":     {deliveryBoundary: "submitted", effectCertainty: "acknowledged", providerOutcome: "succeeded", providerResponse: `{"ok":true}`},
}

// nonLiveOperations are the operations the Cluster contract allows to address a
// resource without a live generation. The list is duplicated here on purpose:
// the mock is a separate Go module and cannot import the Cluster's internal
// package, so the duplication is the price of the module boundary. A drift is
// caught by the conformance suite, which drives both sides.
var nonLiveOperations = map[string]struct{}{
	"agent.resume":     {},
	"agent.drive.stop": {},
	"workspace.clean":  {},
}

// executeResponse revalidates generation inside the mutation path.
func executeResponse(request request, fault string) response {
	if request.Operation == nil || request.Operation.Version != "v1" {
		return failureResponse(request.RequestID, "unsupported", "operation is unsupported", "not_applied")
	}
	evidence, ok := operationEvidenceTable[request.Operation.Name]
	if !ok {
		return failureResponse(request.RequestID, "unsupported", "operation is unsupported", "not_applied")
	}
	// A live operation must prove which process it reaches, so an absent target
	// or a changed generation is rejected before any effect is claimed. A
	// non-live operation addresses a durable record instead, so it is allowed to
	// carry no generation at all.
	if _, nonLive := nonLiveOperations[request.Operation.Name]; !nonLive {
		if request.Target == nil || request.Target.ExpectedGeneration != "generation-1" {
			return failureResponse(request.RequestID, "generation_mismatch", "provider generation changed", "not_applied")
		}
	}
	if fault == "generation-race" {
		return failureResponse(request.RequestID, "generation_mismatch", "provider generation changed", "not_applied")
	}
	return response{
		version:   currentVersion(),
		RequestID: request.RequestID,
		OK:        true,
		Result: &operationResult{
			ProviderRequestRef:        "provider-ref-1",
			DeliveryBoundary:          evidence.deliveryBoundary,
			EffectCertainty:           evidence.effectCertainty,
			ProviderOutcome:           evidence.providerOutcome,
			ProviderResponse:          evidence.providerResponse,
			ProviderResponseTruncated: false,
			StartedAtMS:               fixtureTimeMS,
			FinishedAtMS:              fixtureTimeMS + 1,
		},
	}
}

// mockOperations returns every operation the mock advertises.
//
// The list is derived from the evidence table so the advertised surface and the
// answered surface cannot drift apart: an operation that is advertised but not
// answered would be a capability lie, and an operation that is answered but not
// advertised would be unreachable.
func mockOperations() []namedContract {
	names := make([]string, 0, len(operationEvidenceTable))
	for name := range operationEvidenceTable {
		names = append(names, name)
	}
	sort.Strings(names)
	operations := make([]namedContract, 0, len(names))
	for _, name := range names {
		operations = append(operations, namedContract{Name: name, Version: "v1"})
	}
	return operations
}

// mockDescriptor returns the deterministic Provider CLI surface.
func mockDescriptor(fault string) descriptor {
	queries := []namedContract{
		{Name: queryLaunchOptions, Version: "v1"},
		{Name: queryHistoryMessages, Version: "v1"},
		{Name: queryModelCatalog, Version: "v1"},
		{Name: querySessionMessages, Version: "v1"},
	}
	return descriptor{
		ProviderType:       "mock",
		ProviderVersion:    "1.0.0",
		DescriptorRevision: "mock-v1",
		ProtocolRange: protocolRange{
			Protocol: protocolName,
			Major:    protocolMajor,
			Minimum:  protocolMinor,
			Maximum:  protocolMinor,
		},
		Functions: []string{
			functionDescribe,
			functionDiscover,
			functionInspect,
			functionExecute,
			functionQuery,
			functionQueryCommand,
			functionReadOutput,
			functionFollowOutput,
		},
		Operations:     mockOperations(),
		Queries:        queries,
		ControlActions: []namedContract{},
		Limits: budget{
			MaxStdoutBytes: 1 << 20,
			MaxStderrBytes: 64 << 10,
			MaxRecords:     128,
		},
		Concurrency: concurrencyLimits{Total: 4, Discovery: 2, Mutation: 1, Follow: 2},
	}
}

// discoveryObservations builds the discovery document for the selected mode.
//
// The modes mirror the removed argv fixture exactly, because a migrated scenario
// must keep observing the same Cluster behaviour: "mixed" exists so a resume
// scenario has a row the provider lists but cannot prove is live, and "empty"
// exists so a scenario can prove an empty inventory is not a failure.
func discoveryObservations(options mockOptions) ([]providerObservation, error) {
	if options.discoveryCountFile != "" {
		count := 1
		if data, err := os.ReadFile(options.discoveryCountFile); err == nil {
			_, _ = fmt.Sscanf(string(data), "%d", &count)
			count++
		}
		_ = os.WriteFile(options.discoveryCountFile, []byte(fmt.Sprint(count)), 0o600)
		if options.alwaysFail || (options.failAfterN >= 0 && count > options.failAfterN) {
			return nil, fmt.Errorf("fixture_discovery_failed call=%d fail_after_n=%d", count, options.failAfterN)
		}
	} else if options.alwaysFail {
		return nil, errors.New("fixture_discovery_failed")
	}
	switch options.mode {
	case "one", "":
		return []providerObservation{fixtureObservation()}, nil
	case "mixed":
		return []providerObservation{fixtureObservation(), stoppedObservation()}, nil
	case "empty":
		return []providerObservation{}, nil
	case "fail":
		return nil, errors.New("fixture failure")
	default:
		return nil, fmt.Errorf("unknown discovery mode %q", options.mode)
	}
}

// stoppedObservation is a row the provider lists but cannot prove is live.
//
// An empty generation is the provider's own statement that no process holds the
// session, which is exactly what a resume scenario needs: resume authorizes on
// the absence of a live target.
func stoppedObservation() providerObservation {
	return providerObservation{
		ProviderResourceKey: "session:stopped",
		ProviderGeneration:  "",
		ResourceKind:        resourceSession,
		State:               "stopped",
		ObservedAtMS:        fixtureTimeMS,
		Attributes:          json.RawMessage(`{"provider_display_name":"Stopped Session"}`),
	}
}

// recordInvocation appends one JSON record per provider invocation.
//
// The record is the only evidence that a provider was actually reached, so a
// scenario asserting "the provider was not called" reads this file rather than
// inferring absence from a Cluster response.
func recordInvocation(options mockOptions, request request, kind string) {
	if options.recordFile == "" {
		return
	}
	record := map[string]any{
		"kind":       kind,
		"request_id": request.RequestID,
		"pid":        os.Getpid(),
	}
	if request.Operation != nil {
		record["operation"] = request.Operation.Name
	}
	if request.Target != nil {
		record["target_resource_key"] = request.Target.ProviderResourceKey
		record["target_generation"] = request.Target.ExpectedGeneration
	}
	file, err := os.OpenFile(options.recordFile, os.O_CREATE|os.O_APPEND|os.O_WRONLY, 0o600)
	if err != nil {
		writeDiagnostic("append invocation record: %v", err)
		return
	}
	defer func() { _ = file.Close() }()
	_ = json.NewEncoder(file).Encode(record)
}

// fixtureObservation returns the stable cross-process discovery identity.
func fixtureObservation() providerObservation {
	return providerObservation{
		ProviderResourceKey: "session:stable",
		ProviderGeneration:  "generation-1",
		ResourceKind:        resourceSession,
		State:               "running",
		ObservedAtMS:        fixtureTimeMS,
		Attributes:          json.RawMessage(`{"provider_display_name":"Mock Session"}`),
	}
}

// failureResponse builds one standard Provider CLI rejection.
func failureResponse(requestID, code, message, certainty string) response {
	return response{
		version:   currentVersion(),
		RequestID: requestID,
		OK:        false,
		Error: &providerError{
			Code:            code,
			Message:         message,
			Retryable:       false,
			EffectCertainty: certainty,
		},
	}
}

// writeStream emits deterministic JSONL frames and selected lifecycle faults.
func writeStream(request request, fault string) error {
	streamRequestID := request.RequestID
	if fault == "stream-correlation" {
		streamRequestID = "wrong-request-id"
	}
	frames := []streamFrame{
		{version: currentVersion(), RequestID: streamRequestID, Type: "started", Sequence: 1},
		{
			version:      currentVersion(),
			RequestID:    streamRequestID,
			Type:         "record",
			Sequence:     2,
			ObservedAtMS: fixtureTimeMS,
			Record:       json.RawMessage(`{"text":"mock output"}`),
		},
	}
	if fault == "record-overflow" {
		for sequence := int64(3); sequence <= 20; sequence++ {
			frames = append(frames, streamFrame{
				version: currentVersion(), RequestID: streamRequestID, Type: "record", Sequence: sequence,
				ObservedAtMS: fixtureTimeMS + sequence, Record: json.RawMessage(`{"text":"overflow"}`),
			})
		}
		frames = append(frames, streamFrame{version: currentVersion(), RequestID: streamRequestID, Type: "end", Sequence: 21})
	} else if fault != "missing-terminal" {
		frames = append(frames, streamFrame{version: currentVersion(), RequestID: streamRequestID, Type: "end", Sequence: 3})
	}
	if fault == "duplicate-terminal" {
		frames = append(frames, streamFrame{version: currentVersion(), RequestID: request.RequestID, Type: "end", Sequence: 4})
	}
	if fault == "post-terminal-record" {
		frames = append(frames, streamFrame{
			version:      currentVersion(),
			RequestID:    request.RequestID,
			Type:         "record",
			Sequence:     4,
			ObservedAtMS: fixtureTimeMS + 1,
			Record:       json.RawMessage(`{"text":"late"}`),
		})
	}
	encoder := json.NewEncoder(os.Stdout)
	for _, frame := range frames {
		if err := encoder.Encode(frame); err != nil {
			return err
		}
	}
	return nil
}

// startHelper creates a same-group child for exact cleanup verification.
func startHelper() error {
	command := exec.Command(os.Args[0])
	command.Env = append(os.Environ(), helperEnvironment+"=1", faultEnvironment+"=")
	command.Stdin = nil
	command.Stdout = nil
	command.Stderr = nil
	if err := command.Start(); err != nil {
		return err
	}
	writeDiagnostic("helper_pid=%d", command.Process.Pid)
	return nil
}

// writeDiagnostic writes local fixture evidence to stderr.
func writeDiagnostic(format string, values ...any) {
	_, _ = fmt.Fprintf(os.Stderr, format+"\n", values...)
}
