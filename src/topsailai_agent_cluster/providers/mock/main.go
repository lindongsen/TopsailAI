package main

import (
	"bytes"
	"encoding/json"
	"errors"
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

// main reads one request and emits one deterministic fixture response.
func main() {
	if os.Getenv(helperEnvironment) == "1" {
		time.Sleep(30 * time.Second)
		return
	}
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
	fault := os.Getenv(faultEnvironment)
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
	response := handleUnary(request, fault)
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
func handleUnary(request request, fault string) response {
	base := response{version: currentVersion(), RequestID: request.RequestID, OK: true}
	switch request.Function {
	case functionDescribe:
		descriptor := mockDescriptor(fault)
		base.Descriptor = &descriptor
	case functionDiscover:
		base.Discovery = &discoveryResult{
			Observations: []providerObservation{fixtureObservation()},
			Complete:     true,
			Checkpoint:   "checkpoint-1",
		}
	case functionInspect:
		observation := fixtureObservation()
		base.Inspection = &inspectionResult{Found: true, Live: true, Observation: &observation}
	case functionExecute:
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
		base.Output = &outputSnapshot{ObservedAtMS: fixtureTimeMS, Content: "mock output\n", Complete: true}
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
