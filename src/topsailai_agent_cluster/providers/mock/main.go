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
	followHoldMS       int
	outputSize         int
	failAfterN         int
	alwaysFail         bool
	// sessionDir is the working directory the mock reports for every session it
	// publishes. The Cluster resolves an operator command's directory from this
	// provider evidence and refuses the command when it is absent, so a mock that
	// never reports one cannot exercise command.exec at all. It is a flag rather
	// than an environment variable because the adapter sets a child's environment
	// to exactly the configured Environment, which is empty.
	sessionDir string
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
	// followHoldMS keeps a follow stream alive after its last record. A stream
	// that ends on its own can never be mistaken for a stream the operator
	// stopped, so a scenario that proves the stop path needs the process to
	// outlive the records. The default stays zero because the conformance suite
	// requires a terminal frame and must not wait for a hold.
	flag.IntVar(&options.followHoldMS, "follow-hold-ms", 0, "keep a follow stream open this long after its last record")
	flag.IntVar(&options.outputSize, "output-size", 0, "pad the output snapshot to this many bytes")
	flag.IntVar(&options.failAfterN, "fail-after-n", -1, "fail discovery after N successful calls; zero fails immediately")
	flag.BoolVar(&options.alwaysFail, "always-fail", false, "fail every discovery call")
	flag.StringVar(&options.sessionDir, "session-dir", "", "working directory reported for every published session")
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
		if err := writeStream(request, fault, options.followHoldMS); err != nil {
			writeDiagnostic("write stream: %v", err)
			os.Exit(2)
		}
		return
	}
	// A crash after the invocation was recorded but before any answer is written
	// is the uncertain boundary the Cluster must report as unknown. It is a
	// separate fault from exit-result-conflict, which writes a valid answer and
	// then exits non-zero: that one proves a conflict between exit and result,
	// while this one proves that no result exists at all.
	if fault == "crash-after-invocation" && request.Function == functionExecute {
		recordInvocation(options, request, "execute")
		os.Exit(97)
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
	// The exit code is gated on the function, because a fault that also broke
	// describe or discover would make the adapter unhealthy and the session
	// invisible, so a scenario that only wants a failing execution would fail
	// before it could submit one.
	if fault == "execute-failure" && request.Function == functionExecute {
		os.Exit(2)
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
		// Inspection answers for the exact target it was asked about, because the
		// Cluster authorizes resume on the absence of a live target. A mock that
		// reported every target as live would make resume unreachable: the
		// Endpoint would refuse it with target_still_active before the policy hook
		// ran, so a resume scenario would pass while proving nothing about
		// authorization. The stopped row is therefore found but not live, which is
		// exactly what a provider reports for a record whose process is gone.
		observation := fixtureObservation(options)
		if request.Target != nil && request.Target.ProviderResourceKey == "session:stopped" {
			stopped := stoppedObservation(options)
			base.Inspection = &inspectionResult{Found: true, Live: false, Observation: &stopped}
			break
		}
		base.Inspection = &inspectionResult{Found: true, Live: true, Observation: &observation}
	case functionExecute:
		// The interval is measured around the work, not around the record write,
		// because the record is the evidence a caller uses to prove two commands
		// for one target did not overlap. A record written with no interval left
		// every entry at zero, so an overlap assertion compared zero with zero and
		// passed while proving nothing.
		startNS := time.Now().UnixNano()
		if options.delayMS > 0 {
			time.Sleep(time.Duration(options.delayMS) * time.Millisecond)
		}
		recordInvocationInterval(options, request, "execute", startNS, time.Now().UnixNano())
		// The diagnostic goes to stderr and the answer is a failure document, so
		// the Cluster keeps the provider's own words as evidence instead of
		// flattening the failure into a generic error. The invocation is recorded
		// first, because a failing execution still happened.
		if fault == "execute-failure" {
			writeDiagnostic("mock execution failure")
			return failureResponse(request.RequestID, "provider_error", "mock execution failure", "not_applied")
		}
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
			// The read is recorded because a scenario proves the provider was
			// reached exactly once, and a read that answers without leaving a
			// record is indistinguishable from a read the Cluster answered from
			// its own cache. The kind is the query name, which is what the
			// structured record carries for a function call.
			recordInvocation(options, request, queryModelCatalog)
			// Two profiles are returned because the catalog scenarios select the
			// first and the second row and assert which name reached the provider.
			// A single-profile answer could not distinguish "row 2 resolved to
			// profile 2" from "row 2 resolved to the only profile there is", so the
			// row-number-leak assertion would pass while proving nothing.
			base.QueryResult = json.RawMessage(`{"profiles":[{"resource_kind":"model_profile","provider_resource_key":"fixture-model-a","provider_display_name":"fixture-model-a","current_state":"yes","available":true},{"resource_kind":"model_profile","provider_resource_key":"fixture-model-b","provider_display_name":"fixture-model-b","current_state":"no","available":true}],"current_provider_resource_key":"fixture-model-a","observed_at_ms":1700000000000,"truncated":false}`)
		case querySessionMessages:
			// The provider echoes the session key it was asked about, because the
			// Cluster forwards the caller's selector verbatim and a hardcoded
			// answer made a scoped read look like it had answered for a different
			// session. Two messages are returned because the block-rendering
			// scenario asserts two headers, and a single-message answer could not
			// distinguish "blocks" from "one block".
			//
			// The body is already unwrapped. Unwrapping a provider step record is
			// provider behaviour, not Cluster behaviour: the shipped provider does
			// it in providers/topsailai/query.go and its unit test asserts the
			// exact result. The mock stands in for a provider, so it answers in the
			// same unwrapped form instead of teaching the Cluster a record format
			// it deliberately does not know.
			sessionKey := "session:stable"
			if request.Target != nil && request.Target.ProviderResourceKey != "" {
				sessionKey = request.Target.ProviderResourceKey
			}
			// A session the mock does not know is answered with the provider's own
			// missing-session code instead of two invented messages. Answering
			// every key made "this session does not exist" indistinguishable from
			// "this session recorded nothing", so the Cluster could never be shown
			// to report a missing session and the assertion that it does would
			// have passed against a provider that never said so.
			if !mockKnownSession(sessionKey) {
				return failureResponse(request.RequestID, mockSessionNotFoundCode, "provider session does not exist", "not_applied")
			}
			base.QueryResult = json.RawMessage(fmt.Sprintf(`{"provider_session_id":%q,"messages":[{"role":"user","content":"topsailai.task\nthe operator wrote this","word_count":5,"token_count":6},{"role":"assistant","content":"the operator wrote this","word_count":4,"token_count":5}],"message_count":2,"observed_at_ms":1700000000000,"truncated":false}`, sessionKey))
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
		// A provider that cannot read output reports the capability gap instead of
		// returning an empty snapshot, because an empty snapshot is a successful
		// read of nothing and would be indistinguishable from a session that has
		// produced no output yet.
		if fault == "output-unsupported" {
			return failureResponse(request.RequestID, "unsupported", "output is unsupported", "not_applied")
		}
		// The content and the truncation rule mirror what the removed argv
		// fixture emitted, so a migrated scenario keeps asserting the same
		// Cluster behaviour instead of a new invented shape. The marker text is
		// what the policy and output-scope scenarios look for, and max_bytes is
		// the budget the Cluster forwards, so honouring it is what makes a
		// bounded snapshot actually bounded rather than merely labelled.
		content := "provider output marker"
		truncated := false
		var budget struct {
			MaxBytes int `json:"max_bytes"`
		}
		if len(request.Payload) > 0 {
			_ = json.Unmarshal(request.Payload, &budget)
		}
		if budget.MaxBytes > 0 && len(content) > budget.MaxBytes {
			content = content[:budget.MaxBytes]
			truncated = true
		}
		if options.outputSize > len(content) {
			content += strings.Repeat("x", options.outputSize-len(content))
		}
		base.Output = &outputSnapshot{ObservedAtMS: fixtureTimeMS, Content: content, Truncated: truncated, Complete: !truncated}
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
	version          string
	deliveryBoundary string
	effectCertainty  string
	providerOutcome  string
	providerResponse string
	// exitConfirmed is the provider's own observation that the signalled process
	// exited. It is only meaningful for a signal_sent operation, and it is not a
	// decoration: the Cluster keeps signal_sent && !exit_confirmed at "executing"
	// forever, so a provider that never confirms an exit leaves the operator
	// watching a command that can never finish.
	//
	// execution.interrupt confirms the exit because the provider kills the
	// process and observes it die. agent.stop deliberately does not: the shipped
	// provider reports a stop request as sent with the exit unconfirmed, and
	// features/real_boundary.feature asserts exactly that, so confirming it here
	// would make the mock disagree with the provider it stands in for.
	exitConfirmed bool
}

// operationEvidenceTable answers every operation the mock advertises.
//
// A missing entry is a deliberate rejection rather than a silent success, so an
// operation that is advertised but not answered cannot pass unnoticed.
//
// The version is part of the entry because the Cluster intersects the configured
// capability list with the advertised one by name AND version. An operation whose
// payload schema is versioned independently therefore advertises that payload
// version, not the generic "v1": command.exec and agent.model.select carry their
// own payload version, and advertising "v1" for them would silently drop them from
// the intersection, so every such command would be rejected as unsupported while
// the descriptor looked complete.
var operationEvidenceTable = map[string]operationEvidence{
	"message.send":        {version: "v1", deliveryBoundary: "pipe_written", effectCertainty: "acknowledged", providerOutcome: "submitted", providerResponse: `{"outcome":"accepted","effect_certainty":"acknowledged","delivery_boundary":"pipe_written"}`},
	"context.inject":      {version: "v1", deliveryBoundary: "pipe_written", effectCertainty: "acknowledged", providerOutcome: "submitted", providerResponse: `{"outcome":"accepted","effect_certainty":"acknowledged","delivery_boundary":"pipe_written"}`},
	"execution.interrupt": {version: "v1", deliveryBoundary: "signal_sent", effectCertainty: "acknowledged", providerOutcome: "submitted", providerResponse: `{"outcome":"accepted","effect_certainty":"acknowledged","delivery_boundary":"signal_sent","exit_confirmed":true}`, exitConfirmed: true},
	"agent.stop":          {version: "v1", deliveryBoundary: "signal_sent", effectCertainty: "acknowledged", providerOutcome: "submitted", providerResponse: `{"delivery_boundary":"signal_sent","signal_sent":true,"exit_confirmed":false}`},
	"agent.resume":        {version: "v1", deliveryBoundary: "submitted", effectCertainty: "acknowledged", providerOutcome: "submitted", providerResponse: `{"outcome":"accepted","effect_certainty":"acknowledged","delivery_boundary":"submitted"}`},
	"agent.start":         {version: "v1", deliveryBoundary: "submitted", effectCertainty: "acknowledged", providerOutcome: "submitted", providerResponse: `{"outcome":"accepted","effect_certainty":"acknowledged","delivery_boundary":"submitted"}`},
	"agent.drive.start":   {version: "v1", deliveryBoundary: "submitted", effectCertainty: "acknowledged", providerOutcome: "submitted", providerResponse: `{"outcome":"accepted","effect_certainty":"acknowledged","delivery_boundary":"submitted"}`},
	"agent.drive.stop":    {version: "v1", deliveryBoundary: "signal_sent", effectCertainty: "acknowledged", providerOutcome: "submitted", providerResponse: `{"outcome":"accepted","effect_certainty":"acknowledged","delivery_boundary":"signal_sent"}`},
	"agent.model.select":  {version: "1", deliveryBoundary: "submitted", effectCertainty: "acknowledged", providerOutcome: "submitted", providerResponse: `{"outcome":"accepted","effect_certainty":"acknowledged","delivery_boundary":"submitted"}`},
	"command.exec":        {version: "1", deliveryBoundary: "submitted", effectCertainty: "acknowledged", providerOutcome: "succeeded", providerResponse: `{"outcome":"accepted","effect_certainty":"acknowledged","delivery_boundary":"submitted"}`},
	"workspace.clean":     {version: "v1", deliveryBoundary: "submitted", effectCertainty: "acknowledged", providerOutcome: "succeeded", providerResponse: `{"outcome":"accepted","effect_certainty":"acknowledged","delivery_boundary":"submitted"}`},
}

// nonLiveOperations are the operations the Cluster contract allows to address a
// resource without a live generation. The list is duplicated here on purpose:
// the mock is a separate Go module and cannot import the Cluster's internal
// package, so the duplication is the price of the module boundary. A drift is
// caught by the conformance suite, which drives both sides.
// resourceLaunchProfile and launchProfileRevision mirror the launch profile the
// mock advertises through its launch-options query, so the target an agent.start
// carries can be validated against the same values the Cluster was told about.
const (
	resourceLaunchProfile = "launch_profile"
	launchProfileRevision = "launch-r1"
)

var nonLiveOperations = map[string]struct{}{
	"agent.resume":     {},
	"agent.drive.stop": {},
	"workspace.clean":  {},
}

// executeResponse revalidates generation inside the mutation path.
func executeResponse(request request, fault string) response {
	if request.Operation == nil {
		return failureResponse(request.RequestID, "unsupported", "operation is unsupported", "not_applied")
	}
	// A control action is answered from its own table, because the provider
	// reports control actions separately from operations. Looking only at the
	// operation table refused every ctl. operation as unsupported, so a configured
	// catalog could never reach the provider and the positive authorization
	// scenario ended before the policy hook.
	evidence, ok := operationEvidenceTable[request.Operation.Name]
	if !ok {
		evidence, ok = controlActionEvidenceTable[request.Operation.Name]
	}
	if !ok && strings.HasPrefix(request.Operation.Name, mockControlPrefix) {
		// Any other ctl. operation is answered with the generic control evidence.
		// The Endpoint-local catalog is the only source of action names, so the
		// mock cannot enumerate them; refusing an action the catalog defined would
		// make the control channel testable only for the one name this file
		// happens to list.
		evidence, ok = genericControlEvidence, true
	}
	if !ok {
		return failureResponse(request.RequestID, "unsupported", "operation is unsupported", "not_applied")
	}
	// The version is compared against the table entry rather than against a fixed
	// "v1", because two operations carry their own payload schema version. A fixed
	// comparison rejected them as unsupported even though the descriptor advertised
	// them, so the Cluster intersected them in and the provider then refused them:
	// the descriptor and the answer disagreed about the same operation, and the
	// operator saw "unsupported" for an operation the Endpoint had just listed.
	if request.Operation.Version != evidence.version {
		return failureResponse(request.RequestID, "unsupported", "operation is unsupported", "not_applied")
	}
	// A live operation must prove which process it reaches, so an absent target
	// or a changed generation is rejected before any effect is claimed. A
	// non-live operation addresses a durable record instead, so it is allowed to
	// carry no generation at all.
	//
	// agent.start is neither: it addresses a launch profile, so the generation it
	// must prove is the profile revision rather than a session process
	// generation. Comparing it against a session generation rejected every start
	// with generation_mismatch even though the Cluster had validated the profile
	// revision against the descriptor it was advertised.
	if request.Operation.Name == "agent.start" {
		if request.Target == nil || request.Target.ResourceKind != resourceLaunchProfile || request.Target.ExpectedGeneration != launchProfileRevision {
			return failureResponse(request.RequestID, "generation_mismatch", "launch profile revision changed", "not_applied")
		}
	} else if _, nonLive := nonLiveOperations[request.Operation.Name]; !nonLive {
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
			ExitConfirmed:             evidence.exitConfirmed,
			StartedAtMS:               fixtureTimeMS,
			FinishedAtMS:              fixtureTimeMS + 1,
		},
	}
}

// controlActionEvidenceTable answers the provider control family.
//
// A control action is not an operation: the provider reports it in its own
// contract list, and the Cluster advertises it as a ctl. capability. Keeping the
// two tables apart is what makes the mock honest about the distinction, because a
// ctl. entry placed in the operation table would be advertised as an operation and
// the Cluster would then accept a command the provider never offered as one.
//
// The entry is answered by prefix rather than by exact name, mirroring the real
// provider: any ctl. operation the Endpoint admits is one the Endpoint-local
// catalog defined, and the catalog is the only source of action names. A mock that
// answered one hardcoded name would make a scenario pass only for that name.
// mockControlPrefix is the Cluster's prefix for a control action capability. It
// is a wire contract value, so it is stated once here and the production
// declaration must agree.
const mockControlPrefix = "ctl."

// genericControlEvidence answers a ctl. operation the table does not name.
//
// A control action is submitted and acknowledged: the provider accepted the
// request and reports that it reached the provider, which is the strongest claim
// a control action can make without observing the effect itself.
var genericControlEvidence = operationEvidence{version: "v1", deliveryBoundary: "submitted", effectCertainty: "acknowledged", providerOutcome: "succeeded", providerResponse: `{"outcome":"accepted","effect_certainty":"acknowledged","delivery_boundary":"submitted"}`}

var controlActionEvidenceTable = map[string]operationEvidence{
	"ctl.fixture_probe": {version: "v1", deliveryBoundary: "submitted", effectCertainty: "acknowledged", providerOutcome: "succeeded", providerResponse: `{"outcome":"accepted","effect_certainty":"acknowledged","delivery_boundary":"submitted"}`},
}

// mockControlActions returns every control action the mock advertises.
func mockControlActions() []namedContract {
	names := make([]string, 0, len(controlActionEvidenceTable))
	for name := range controlActionEvidenceTable {
		names = append(names, name)
	}
	sort.Strings(names)
	actions := make([]namedContract, 0, len(names))
	for _, name := range names {
		actions = append(actions, namedContract{Name: name, Version: controlActionEvidenceTable[name].version})
	}
	return actions
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
		operations = append(operations, namedContract{Name: name, Version: operationEvidenceTable[name].version})
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
		ControlActions: mockControlActions(),
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
		return []providerObservation{fixtureObservation(options)}, nil
	case "mixed":
		return []providerObservation{fixtureObservation(options), stoppedObservation(options)}, nil
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
func stoppedObservation(options mockOptions) providerObservation {
	return providerObservation{
		ProviderResourceKey: "session:stopped",
		ProviderGeneration:  "",
		ResourceKind:        resourceSession,
		State:               "stopped",
		ObservedAtMS:        fixtureTimeMS,
		Attributes:          sessionAttributesJSON("session:stopped", "Stopped Session", options.sessionDir),
	}
}

// invocationPayloadLimit bounds the payload copied into an invocation record.
//
// The record is evidence, not a transport, so a payload larger than this is
// reported as truncated rather than written whole. An unbounded copy would let a
// large mutation payload grow the record file without limit.
const invocationPayloadLimit = 4096

// recordInvocation appends one JSON record per provider invocation.
//
// The record is the only evidence that a provider was actually reached, so a
// scenario asserting "the provider was not called" reads this file rather than
// inferring absence from a Cluster response.
func recordInvocation(options mockOptions, request request, kind string) {
	recordInvocationInterval(options, request, kind, 0, 0)
}

// recordInvocationInterval records one invocation together with the interval it
// occupied. A zero interval is omitted rather than written as zero, so a caller
// can tell "this invocation reported no interval" from "this invocation took no
// time".
func recordInvocationInterval(options mockOptions, request request, kind string, startNS, endNS int64) {
	if options.recordFile == "" {
		return
	}
	record := map[string]any{
		"kind":       kind,
		"request_id": request.RequestID,
		"pid":        os.Getpid(),
	}
	// The operation name is recorded for every invocation, not only for the
	// mutation path. A read function carries no Operation field, so keying the
	// record on it alone left the read invocations with a kind but no operation,
	// and a caller counting provider reads by operation name counted zero while
	// the provider had in fact been invoked. The kind is the operation name for a
	// function call, so it is the honest fallback rather than an invented value.
	if request.Operation != nil {
		record["operation"] = request.Operation.Name
	} else {
		record["operation"] = kind
	}
	if request.Target != nil {
		record["target_resource_key"] = request.Target.ProviderResourceKey
		record["target_generation"] = request.Target.ExpectedGeneration
	}
	// The payload is recorded because a scenario proves which provider-private
	// key the Cluster resolved and forwarded. Without it the record shows that
	// the provider was called but not what it was asked, so a leaked row number
	// and a resolved profile name would look identical in the evidence.
	if len(request.Payload) > 0 {
		if len(request.Payload) <= invocationPayloadLimit {
			record["payload"] = string(request.Payload)
		} else {
			record["payload_truncated"] = true
		}
	}
	if startNS != 0 && endNS != 0 {
		record["timestamp_ns"] = endNS
		record["start_ns"] = startNS
		record["end_ns"] = endNS
	}
	file, err := os.OpenFile(options.recordFile, os.O_CREATE|os.O_APPEND|os.O_WRONLY, 0o600)
	if err != nil {
		writeDiagnostic("append invocation record: %v", err)
		return
	}
	defer func() { _ = file.Close() }()
	_ = json.NewEncoder(file).Encode(record)
}

// sessionAttributesJSON builds the provider attribute document for one session.
//
// provider_project_workspace is reported only when the mock was told a directory,
// because the Cluster treats an absent workspace as "the provider did not say"
// and refuses an operator command rather than inventing one. Reporting a made-up
// path would let a command run somewhere the operator never selected.
func sessionAttributesJSON(sessionID, displayName, workspace string) json.RawMessage {
	document := map[string]any{"provider_session_id": sessionID, "provider_display_name": displayName}
	if workspace != "" {
		document["provider_project_workspace"] = workspace
	}
	encoded, err := json.Marshal(document)
	if err != nil {
		return json.RawMessage(`{}`)
	}
	return json.RawMessage(encoded)
}

// fixtureObservation returns the stable cross-process discovery identity.
func fixtureObservation(options mockOptions) providerObservation {
	return providerObservation{
		ProviderResourceKey: "session:stable",
		ProviderGeneration:  "generation-1",
		ResourceKind:        resourceSession,
		State:               "running",
		ObservedAtMS:        fixtureTimeMS,
		// provider_session_id is the provider's own session identifier, and the
		// Cluster copies it into the Session resource verbatim. Omitting it left
		// every reported session with an empty provider_session_id, so a caller
		// addressing a session by its provider key could not find the row it had
		// just been told about. The provider resource key is that identifier here,
		// so it is reported rather than invented.
		Attributes: sessionAttributesJSON("session:stable", "Mock Session", options.sessionDir),
	}
}

// failureResponse builds one standard Provider CLI rejection.
// mockSessionNotFoundCode is the provider's own code for a session it does not
// know. It is a provider protocol value, not a Cluster error code.
const mockSessionNotFoundCode = "session_not_found"

// mockKnownSession reports whether the mock has a session under this key.
//
// The two keys are the ones the mock's own observations publish, so a read for a
// key it never advertised is answered as missing rather than invented.
func mockKnownSession(key string) bool {
	return key == "session:stable" || key == "session:stopped"
}

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
//
// holdMS keeps the process alive after the terminal frame. The deleted argv
// fixture did the same on purpose: it wrote its records 150 ms apart and then
// slept, so a stream that ended by itself could never be mistaken for a stream
// the operator stopped. Without the hold the mock answers started, one record
// and end in a single burst, the CLI reports a clean end, and a scenario that
// presses a key to stop the stream has nothing left to stop.
func writeStream(request request, fault string, holdMS int) error {
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
			// The record shape is the Cluster contract, not a provider choice:
			// the Generic CLI Adapter decodes a record strictly as
			// {"lines":[...]} and rejects any other field, so a record carrying
			// "text" made every follow scenario fail with "decode output record:
			// json: unknown field". The text keeps the "fixture follow" marker the
			// follow scenarios assert, because that marker is what proves a record
			// reached the terminal rather than the stream merely being armed.
			Record: json.RawMessage(`{"lines":["fixture follow record 1"]}`),
		},
	}
	if fault == "record-overflow" {
		for sequence := int64(3); sequence <= 20; sequence++ {
			frames = append(frames, streamFrame{
				version: currentVersion(), RequestID: streamRequestID, Type: "record", Sequence: sequence,
				ObservedAtMS: fixtureTimeMS + sequence, Record: json.RawMessage(`{"lines":["overflow"]}`),
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
			Record:       json.RawMessage(`{"lines":["late"]}`),
		})
	}
	// The hold sits between the last record and the terminal frame, not after
	// it. A terminal frame tells the CLI the stream finished, so holding after
	// it would only delay the process exit while the CLI had already reported a
	// clean end. Holding before it keeps the stream open, which is the state a
	// keypress or an interrupt is supposed to end.
	body, terminal := frames, streamFrame{}
	if len(frames) > 0 && frames[len(frames)-1].Type == "end" {
		body, terminal = frames[:len(frames)-1], frames[len(frames)-1]
	}
	encoder := json.NewEncoder(os.Stdout)
	for _, frame := range body {
		if err := encoder.Encode(frame); err != nil {
			return err
		}
	}
	if holdMS > 0 {
		time.Sleep(time.Duration(holdMS) * time.Millisecond)
	}
	if terminal.Type == "end" {
		if err := encoder.Encode(terminal); err != nil {
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
