package tui

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"strings"
	"testing"

	"topsailai_agent_cluster/internal/protocol"
)

// ctlStubAPI advertises provider control actions and returns a terminal receipt,
// so the interactive control path can be exercised without a live Endpoint.
type ctlStubAPI struct {
	interactiveStub
	capabilities []protocol.Capability
	command      map[string]any
}

// GetCapabilities returns the caller-supplied descriptor, so a test can prove the
// rendered action list follows the advertised capabilities rather than a table.
func (s *ctlStubAPI) GetCapabilities(context.Context, string) (protocol.CapabilityDescriptor, error) {
	return protocol.CapabilityDescriptor{Revision: "rev-1", Capabilities: s.capabilities}, nil
}

// GetCommand returns the terminal receipt the wait loop observes.
func (s *ctlStubAPI) GetCommand(context.Context, string) (map[string]any, error) {
	return s.command, nil
}

// ctlStub returns a stub whose selected session is already pinned in session scope.
func ctlStub(capabilities ...protocol.Capability) *ctlStubAPI {
	stub := &ctlStubAPI{
		capabilities: capabilities,
		command: map[string]any{
			"command_id":        "cmd-1",
			"status":            string(protocol.StatusFinished),
			"delivery_boundary": string(protocol.DeliverySubmitted),
			"effect_certainty":  string(protocol.EffectAcknowledged),
		},
	}
	stub.endpoints = []protocol.Endpoint{{EndpointID: "endpoint-1"}}
	stub.reports = map[string]protocol.InventoryReport{"endpoint-1": testInventory()}
	return stub
}

// ctlState pins the selection and the session scope that the command requires.
func ctlState() *interactiveState {
	state := shellState()
	state.Scope.Kind = ScopeSession
	return state
}

// ctlLines builds a prompt channel holding the supplied answers in order.
func ctlLines(answers ...string) <-chan lineReadResult {
	lines := make(chan lineReadResult, len(answers))
	for _, answer := range answers {
		lines <- lineReadResult{line: answer}
	}
	return lines
}

// sameJSONObject compares two JSON objects by decoded value.
//
// The guided parameter builder encodes through a map, so key order is not the
// order the operator typed. Comparing decoded values keeps the assertions about
// meaning instead of about serialization order.
func sameJSONObject(got json.RawMessage, want string) bool {
	var gotValue, wantValue map[string]any
	if err := json.Unmarshal(got, &gotValue); err != nil {
		return false
	}
	if err := json.Unmarshal([]byte(want), &wantValue); err != nil {
		return false
	}
	if len(gotValue) != len(wantValue) {
		return false
	}
	for key, wantEntry := range wantValue {
		gotEntry, ok := gotValue[key]
		if !ok || fmt.Sprint(gotEntry) != fmt.Sprint(wantEntry) {
			return false
		}
	}
	return true
}

// TestCtlActionNamesFollowsTheDescriptor proves the rendered list is derived from
// the advertised capabilities, so an unsupported action is never offered and a
// newly advertised action needs no client change.
func TestCtlActionNamesFollowsTheDescriptor(t *testing.T) {
	descriptor := protocol.CapabilityDescriptor{Capabilities: []protocol.Capability{
		{Name: "ctl.pause"},
		{Name: protocol.OperationMessageSend},
		{Name: "ctl.heartbeat"},
		{Name: "ctl.get_session_messages"},
		{Name: protocol.OperationCommandExec},
	}}
	names := ctlActionNames(descriptor)
	want := []string{"get_session_messages", "heartbeat", "pause"}
	if len(names) != len(want) {
		t.Fatalf("names = %q, want %q", names, want)
	}
	for index := range want {
		if names[index] != want[index] {
			t.Fatalf("names = %q, want %q", names, want)
		}
	}
}

// TestCtlActionNamesEmpty proves an Endpoint advertising no control action yields
// an empty list rather than a fabricated default.
func TestCtlActionNamesEmpty(t *testing.T) {
	if names := ctlActionNames(protocol.CapabilityDescriptor{}); len(names) != 0 {
		t.Fatalf("names = %q, want none", names)
	}
}

// TestCtlPayload proves an omitted payload becomes the empty object and a
// non-object payload is rejected instead of being silently wrapped.
func TestCtlPayload(t *testing.T) {
	cases := []struct {
		name    string
		text    string
		want    string
		wantErr bool
	}{
		{name: "omitted", text: "", want: "{}"},
		{name: "whitespace only", text: "   ", want: "{}"},
		{name: "object", text: `{"reason":"maintenance"}`, want: `{"reason":"maintenance"}`},
		{name: "empty object", text: "{}", want: "{}"},
		{name: "scalar", text: `"text"`, wantErr: true},
		{name: "number", text: "42", wantErr: true},
		{name: "array", text: "[1,2]", wantErr: true},
		{name: "invalid json", text: "{oops}", wantErr: true},
	}
	for _, testCase := range cases {
		t.Run(testCase.name, func(t *testing.T) {
			payload, err := ctlPayload(testCase.text)
			if testCase.wantErr {
				if err == nil {
					t.Fatalf("ctlPayload(%q) = %q, want error", testCase.text, payload)
				}
				return
			}
			if err != nil {
				t.Fatalf("ctlPayload(%q) error: %v", testCase.text, err)
			}
			if string(payload) != testCase.want {
				t.Fatalf("payload = %q, want %q", payload, testCase.want)
			}
		})
	}
}

// TestParseCtlArguments proves the action and the guided parameters are split
// without interpreting a parameter as a further action, and that a JSON document
// is no longer accepted on the interactive surface.
func TestParseCtlArguments(t *testing.T) {
	cases := []struct {
		name       string
		rest       string
		wantAction string
		wantPay    string
		wantErr    string
	}{
		{name: "action only", rest: "heartbeat", wantAction: "heartbeat", wantPay: "{}"},
		{name: "one parameter", rest: "pause reason=maintenance", wantAction: "pause", wantPay: `{"reason":"maintenance"}`},
		{name: "two parameters", rest: "pause reason=maintenance timeout_seconds=300", wantAction: "pause", wantPay: `{"reason":"maintenance","timeout_seconds":300}`},
		{name: "surrounding spaces", rest: "  heartbeat  ", wantAction: "heartbeat", wantPay: "{}"},
		{name: "empty", rest: "", wantErr: ctlInteractiveUsage},
		{name: "whitespace only", rest: "   ", wantErr: ctlInteractiveUsage},
		{name: "leading dash", rest: "--json", wantErr: ctlInteractiveUsage},
		{name: "bare word parameter", rest: "pause nope", wantErr: "must be key=value"},
		{name: "json document", rest: `pause {"reason":"x"}`, wantErr: "must be key=value"},
	}
	for _, testCase := range cases {
		t.Run(testCase.name, func(t *testing.T) {
			action, payload, err := parseCtlArguments(testCase.rest)
			if testCase.wantErr != "" {
				if err == nil || !strings.Contains(err.Error(), testCase.wantErr) {
					t.Fatalf("error = %v, want it to contain %q", err, testCase.wantErr)
				}
				return
			}
			if err != nil {
				t.Fatalf("parseCtlArguments(%q) error: %v", testCase.rest, err)
			}
			if action != testCase.wantAction || !sameJSONObject(payload, testCase.wantPay) {
				t.Fatalf("action=%q payload=%q, want %q/%q", action, payload, testCase.wantAction, testCase.wantPay)
			}
		})
	}
}

// TestCtlOperation proves the advertised operation name is the prefixed spelling
// and that an empty or flag-like action is a usage error.
func TestCtlOperation(t *testing.T) {
	operation, err := CtlOperation("heartbeat")
	if err != nil {
		t.Fatalf("CtlOperation error: %v", err)
	}
	if operation != "ctl.heartbeat" {
		t.Fatalf("operation = %q, want ctl.heartbeat", operation)
	}
	for _, action := range []string{"", "   ", "--json"} {
		if operation, err := CtlOperation(action); err == nil {
			t.Fatalf("CtlOperation(%q) = %q, want error", action, operation)
		}
	}
}

// TestPromptCtlActionRendersAdvertisedActions proves the prompt lists only the
// advertised actions and accepts either the number or the name.
func TestPromptCtlActionRendersAdvertisedActions(t *testing.T) {
	cases := []struct {
		name   string
		answer string
		want   string
	}{
		{name: "by number", answer: "2", want: "pause"},
		{name: "by name", answer: "pause", want: "pause"},
		{name: "first by number", answer: "1", want: "heartbeat"},
	}
	for _, testCase := range cases {
		t.Run(testCase.name, func(t *testing.T) {
			stub := ctlStub(
				protocol.Capability{Name: "ctl.heartbeat"},
				protocol.Capability{Name: "ctl.pause"},
			)
			var output strings.Builder
			action, err := promptCtlAction(context.Background(), stub, ctlState(), ctlLines(testCase.answer), &output, InteractiveOptions{})
			if err != nil {
				t.Fatalf("promptCtlAction error: %v", err)
			}
			if action != testCase.want {
				t.Fatalf("action = %q, want %q", action, testCase.want)
			}
			if !strings.Contains(output.String(), "1. heartbeat") || !strings.Contains(output.String(), "2. pause") {
				t.Fatalf("rendered list missing actions: %q", output.String())
			}
		})
	}
}

// TestPromptCtlActionCancelsOnEmptyAnswer proves an empty answer cancels instead
// of selecting the first action, because the request is mutating.
func TestPromptCtlActionCancelsOnEmptyAnswer(t *testing.T) {
	stub := ctlStub(protocol.Capability{Name: "ctl.heartbeat"})
	var output strings.Builder
	action, err := promptCtlAction(context.Background(), stub, ctlState(), ctlLines(""), &output, InteractiveOptions{})
	if err == nil || !strings.Contains(err.Error(), "ctl cancelled") {
		t.Fatalf("error = %v, want a cancellation", err)
	}
	if action != "" {
		t.Fatalf("action = %q, want none", action)
	}
}

// TestPromptCtlActionRejectsUnknownAction proves an answer outside the advertised
// list fails instead of being forwarded to the Endpoint.
func TestPromptCtlActionRejectsUnknownAction(t *testing.T) {
	stub := ctlStub(protocol.Capability{Name: "ctl.heartbeat"})
	var output strings.Builder
	action, err := promptCtlAction(context.Background(), stub, ctlState(), ctlLines("hard_interrupt"), &output, InteractiveOptions{})
	if err == nil || !strings.Contains(err.Error(), "unknown control action") {
		t.Fatalf("error = %v, want an unknown-action rejection", err)
	}
	if action != "" {
		t.Fatalf("action = %q, want none", action)
	}
}

// TestPromptCtlActionRejectsEndpointWithoutActions proves an Endpoint advertising
// no control action fails instead of prompting with an empty list.
func TestPromptCtlActionRejectsEndpointWithoutActions(t *testing.T) {
	stub := ctlStub(protocol.Capability{Name: protocol.OperationMessageSend})
	var output strings.Builder
	action, err := promptCtlAction(context.Background(), stub, ctlState(), ctlLines("1"), &output, InteractiveOptions{})
	if err == nil || !strings.Contains(err.Error(), "advertises no control actions") {
		t.Fatalf("error = %v, want an empty-catalog rejection", err)
	}
	if action != "" {
		t.Fatalf("action = %q, want none", action)
	}
}

// TestExecuteInteractiveLineCtlAdmitsTheAdvertisedOperation proves a control line
// reaches the Endpoint as the advertised ctl.<action> operation against the exact
// pinned generation, and that the intent carries the advertised version.
func TestExecuteInteractiveLineCtlAdmitsTheAdvertisedOperation(t *testing.T) {
	stub := ctlStub(protocol.Capability{Name: "ctl.heartbeat", Version: "2"})
	state := ctlState()
	var output, diagnostics strings.Builder
	_, err := executeInteractiveLine(context.Background(), stub, state, `ctl heartbeat note=x`, ctlLines("y"), &output, &output, &diagnostics, InteractiveOptions{WaitTimeoutMS: 100})
	if err != nil {
		t.Fatalf("executeInteractiveLine: %v", err)
	}
	if stub.admit != 1 {
		t.Fatalf("admitted %d commands, want 1", stub.admit)
	}
	intent := stub.intents[0]
	if intent.Operation != "ctl.heartbeat" {
		t.Fatalf("operation = %q, want ctl.heartbeat", intent.Operation)
	}
	if intent.OperationVersion != "2" {
		t.Fatalf("operation version = %q, want the advertised 2", intent.OperationVersion)
	}
	if intent.Target == nil || intent.Target.ResourceID != "session-1" || intent.Target.ProviderGeneration != "generation-1" {
		t.Fatalf("target = %+v, want session-1/generation-1", intent.Target)
	}
	if !sameJSONObject(intent.Payload, `{"note":"x"}`) {
		t.Fatalf("payload = %q, want the supplied parameter", intent.Payload)
	}
	if !strings.Contains(output.String(), "CommandID: cmd-1") {
		t.Fatalf("output missing the receipt: %q", output.String())
	}
}

// TestExecuteInteractiveLineCtlPromptsForTheAction proves a bare control line
// renders the advertised actions, then guides the parameters, and submits the
// chosen action. The parameter answer is empty, so no JSON is ever required.
func TestExecuteInteractiveLineCtlPromptsForTheAction(t *testing.T) {
	stub := ctlStub(
		protocol.Capability{Name: "ctl.heartbeat"},
		protocol.Capability{Name: "ctl.pause"},
	)
	state := ctlState()
	var output, diagnostics strings.Builder
	_, err := executeInteractiveLine(context.Background(), stub, state, "ctl", ctlLines("2", "", "y"), &output, &output, &diagnostics, InteractiveOptions{WaitTimeoutMS: 100})
	if err != nil {
		t.Fatalf("executeInteractiveLine: %v", err)
	}
	if stub.admit != 1 {
		t.Fatalf("admitted %d commands, want 1", stub.admit)
	}
	if got := stub.intents[0].Operation; got != "ctl.pause" {
		t.Fatalf("operation = %q, want ctl.pause", got)
	}
	if !strings.Contains(output.String(), "1. heartbeat") {
		t.Fatalf("output missing the rendered action list: %q", output.String())
	}
	if !strings.Contains(output.String(), "Parameters for pause:") {
		t.Fatalf("output missing the guided parameter prompt: %q", output.String())
	}
}

// TestExecuteInteractiveLineCtlDeclinedAdmitsNothing proves the confirmation gate
// still guards the control path. The parameter answer comes first because the
// guided prompt runs before the confirmation.
func TestExecuteInteractiveLineCtlDeclinedAdmitsNothing(t *testing.T) {
	stub := ctlStub(protocol.Capability{Name: "ctl.heartbeat"})
	state := ctlState()
	var output, diagnostics strings.Builder
	_, err := executeInteractiveLine(context.Background(), stub, state, "ctl heartbeat", ctlLines("", "n"), &output, &output, &diagnostics, InteractiveOptions{WaitTimeoutMS: 100})
	if err != nil {
		t.Fatalf("executeInteractiveLine: %v", err)
	}
	if stub.admit != 0 {
		t.Fatalf("declined control admitted %d commands", stub.admit)
	}
	if !strings.Contains(output.String(), "ctl heartbeat cancelled") {
		t.Fatalf("missing cancellation notice: %q", output.String())
	}
}

// TestExecuteInteractiveLineCtlRejectsUnadvertisedAction proves an action the
// Endpoint does not advertise fails during preflight, before admission and before
// any parameter prompt. No answer is supplied, so a parameter prompt would block
// or consume the confirmation answer and the test would fail.
func TestExecuteInteractiveLineCtlRejectsUnadvertisedAction(t *testing.T) {
	stub := ctlStub(protocol.Capability{Name: "ctl.heartbeat"})
	state := ctlState()
	var output, diagnostics strings.Builder
	_, err := executeInteractiveLine(context.Background(), stub, state, "ctl hard_interrupt", ctlLines(), &output, &output, &diagnostics, InteractiveOptions{WaitTimeoutMS: 100})
	if err == nil || !strings.Contains(err.Error(), "unsupported capability") {
		t.Fatalf("error = %v, want an unsupported-capability rejection", err)
	}
	if stub.admit != 0 {
		t.Fatalf("unadvertised action admitted %d commands", stub.admit)
	}
	if strings.Contains(output.String(), "Parameters for") {
		t.Fatalf("an unadvertised action must not prompt for parameters: %q", output.String())
	}
}

// TestExecuteInteractiveLineCtlRequiresSessionScope proves the command is refused
// outside session scope with the uniform actionable message.
func TestExecuteInteractiveLineCtlRequiresSessionScope(t *testing.T) {
	stub := ctlStub(protocol.Capability{Name: "ctl.heartbeat"})
	state := shellState()
	var output, diagnostics strings.Builder
	_, err := executeInteractiveLine(context.Background(), stub, state, "ctl heartbeat", ctlLines("y"), &output, &output, &diagnostics, InteractiveOptions{WaitTimeoutMS: 100})
	if err == nil || !strings.Contains(err.Error(), "unavailable in workspace scope") {
		t.Fatalf("error = %v, want a scope rejection", err)
	}
	if stub.admit != 0 {
		t.Fatalf("out-of-scope control admitted %d commands", stub.admit)
	}
}

// TestCtlIsRegisteredInSessionScopeOnly proves the matrix entry is what makes the
// command reachable, so removing it would surface as an unknown command.
func TestCtlIsRegisteredInSessionScopeOnly(t *testing.T) {
	if !containsCanonicalCommand("ctl") {
		t.Fatal("ctl is not registered in the command scope matrix")
	}
	if !commandAllowed("ctl", ScopeSession) {
		t.Fatal("ctl must be available in session scope")
	}
	for _, kind := range []ScopeKind{ScopeWorkspace, ScopeEndpoint} {
		if commandAllowed("ctl", kind) {
			t.Fatalf("ctl must not be available in %s scope", kind)
		}
	}
	if canonical := canonicalCommandName("ctl"); canonical != "ctl" {
		t.Fatalf("ctl must not be an alias, got %q", canonical)
	}
}

// TestCtlHelpAdvertisesTheInteractiveSyntax proves the interactive help advertises
// the guided parameter form and never a JSON payload, while the standalone help
// keeps its explicit JSON argument. The two surfaces are separate contracts, so a
// reader of one must not be told to use the other.
func TestCtlHelpAdvertisesTheInteractiveSyntax(t *testing.T) {
	entry, ok := commandHelpCatalog["ctl"]
	if !ok {
		t.Fatal("ctl is missing from the help catalog")
	}
	if !strings.Contains(entry.syntax, "key=value") {
		t.Fatalf("interactive syntax = %q, want the guided parameter form", entry.syntax)
	}
	if strings.Contains(entry.syntax, "[json]") {
		t.Fatalf("interactive syntax = %q, must not advertise a JSON payload", entry.syntax)
	}
	if !strings.Contains(entry.syntax, "ctl.<action>") {
		t.Fatalf("interactive syntax = %q, want the dotted spelling", entry.syntax)
	}
	for _, example := range entry.examples {
		if strings.Contains(example, "{") {
			t.Fatalf("interactive example %q must not contain a JSON document", example)
		}
	}
	if !containsCommand(nonInteractiveHelpOrder, "ctl") {
		t.Fatal("ctl is missing from the non-interactive help order")
	}
	var standalone bytes.Buffer
	if err := PrintNonInteractiveCommandHelp(&standalone, "ctl"); err != nil {
		t.Fatalf("PrintNonInteractiveCommandHelp: %v", err)
	}
	if !strings.Contains(standalone.String(), "[json]") {
		t.Fatalf("standalone help = %q, want the explicit JSON argument", standalone.String())
	}
}

// TestCtlPayloadExportMatchesTheInternalValidator proves the exported wrapper the
// standalone CLI uses cannot drift from the interactive validator.
func TestCtlPayloadExportMatchesTheInternalValidator(t *testing.T) {
	payload, err := CtlPayload(`{"a":1}`)
	if err != nil {
		t.Fatalf("CtlPayload error: %v", err)
	}
	if string(payload) != `{"a":1}` {
		t.Fatalf("payload = %q", payload)
	}
	if _, err := CtlPayload("nope"); err == nil {
		t.Fatal("CtlPayload must reject a non-object payload")
	}
	var decoded map[string]any
	if err := json.Unmarshal(payload, &decoded); err != nil {
		t.Fatalf("payload is not a JSON object: %v", err)
	}
}

// TestCtlParameterPayloadBuildsTheGuidedObject proves the guided parameters become
// one JSON object, so the interactive surface never needs a JSON document.
func TestCtlParameterPayloadBuildsTheGuidedObject(t *testing.T) {
	cases := []struct {
		name       string
		parameters []string
		want       string
		wantErr    string
	}{
		{name: "empty sends the empty object", parameters: nil, want: "{}"},
		{name: "one string", parameters: []string{"reason=maintenance"}, want: `{"reason":"maintenance"}`},
		{name: "number keeps its type", parameters: []string{"timeout_seconds=300"}, want: `{"timeout_seconds":300}`},
		{name: "boolean keeps its type", parameters: []string{"force=true"}, want: `{"force":true}`},
		{name: "null keeps its type", parameters: []string{"default=null"}, want: `{"default":null}`},
		{name: "quoted number stays a string", parameters: []string{`timeout_seconds="300"`}, want: `{"timeout_seconds":"300"}`},
		{name: "quoted boolean stays a string", parameters: []string{`force="true"`}, want: `{"force":"true"}`},
		{name: "plain word stays a string", parameters: []string{"default=continue"}, want: `{"default":"continue"}`},
		{name: "two parameters", parameters: []string{"reason=maintenance", "timeout_seconds=300"}, want: `{"reason":"maintenance","timeout_seconds":300}`},
		{name: "missing equals", parameters: []string{"nope"}, wantErr: "must be key=value"},
		{name: "empty key", parameters: []string{"=value"}, wantErr: "must be key=value"},
		{name: "duplicate key", parameters: []string{"a=1", "a=2"}, wantErr: "supplied twice"},
		{name: "json document is not a parameter", parameters: []string{`{"reason":"x"}`}, wantErr: "must be key=value"},
	}
	for _, testCase := range cases {
		t.Run(testCase.name, func(t *testing.T) {
			payload, err := ctlParameterPayload(testCase.parameters)
			if testCase.wantErr != "" {
				if err == nil || !strings.Contains(err.Error(), testCase.wantErr) {
					t.Fatalf("error = %v, want it to contain %q", err, testCase.wantErr)
				}
				return
			}
			if err != nil {
				t.Fatalf("ctlParameterPayload(%v) error: %v", testCase.parameters, err)
			}
			if !sameJSONObject(payload, testCase.want) {
				t.Fatalf("payload = %q, want %q", payload, testCase.want)
			}
		})
	}
}

// TestCtlParameterSummaryEchoesTheGuidedForm proves the confirmation preview shows
// the parameters as key=value pairs with stable ordering, so the operator verifies
// what will be sent without reading JSON.
func TestCtlParameterSummaryEchoesTheGuidedForm(t *testing.T) {
	cases := []struct {
		name    string
		payload string
		want    string
	}{
		{name: "empty object", payload: "{}", want: "none"},
		{name: "one pair", payload: `{"reason":"maintenance"}`, want: "reason=maintenance"},
		{name: "sorted keys", payload: `{"timeout_seconds":300,"reason":"maintenance"}`, want: "reason=maintenance timeout_seconds=300"},
		{name: "number is unquoted", payload: `{"timeout_seconds":300}`, want: "timeout_seconds=300"},
		{name: "boolean is unquoted", payload: `{"force":true}`, want: "force=true"},
	}
	for _, testCase := range cases {
		t.Run(testCase.name, func(t *testing.T) {
			if got := ctlParameterSummary(json.RawMessage(testCase.payload)); got != testCase.want {
				t.Fatalf("summary = %q, want %q", got, testCase.want)
			}
		})
	}
}

// TestPromptCtlParametersGuidesAndSendsTheEmptyObject proves the guided prompt is
// rendered and an empty answer sends the empty object, so an action without
// arguments needs no input at all.
func TestPromptCtlParametersGuidesAndSendsTheEmptyObject(t *testing.T) {
	var output strings.Builder
	payload, err := promptCtlParameters(context.Background(), "heartbeat", ctlLines(""), &output)
	if err != nil {
		t.Fatalf("promptCtlParameters: %v", err)
	}
	if string(payload) != "{}" {
		t.Fatalf("payload = %q, want the empty object", payload)
	}
	if !strings.Contains(output.String(), "Parameters for heartbeat:") {
		t.Fatalf("output missing the guided prompt: %q", output.String())
	}
}

// TestPromptCtlParametersAcceptsKeyValuePairs proves a supplied answer becomes the
// guided object rather than being parsed as JSON.
func TestPromptCtlParametersAcceptsKeyValuePairs(t *testing.T) {
	var output strings.Builder
	payload, err := promptCtlParameters(context.Background(), "pause", ctlLines("reason=maintenance timeout_seconds=300"), &output)
	if err != nil {
		t.Fatalf("promptCtlParameters: %v", err)
	}
	if !sameJSONObject(payload, `{"reason":"maintenance","timeout_seconds":300}`) {
		t.Fatalf("payload = %q", payload)
	}
}

// TestPromptCtlParametersRejectsAJSONDocument proves the guided prompt refuses a
// JSON document, so the interactive surface keeps exactly one payload syntax.
func TestPromptCtlParametersRejectsAJSONDocument(t *testing.T) {
	var output strings.Builder
	_, err := promptCtlParameters(context.Background(), "pause", ctlLines(`{"reason":"x"}`), &output)
	if err == nil || !strings.Contains(err.Error(), "must be key=value") {
		t.Fatalf("error = %v, want a guided-parameter rejection", err)
	}
}

// TestExecuteInteractiveLineCtlSuppliedParametersSkipThePrompt proves parameters
// typed on the command line are sent without asking again, so the guided prompt is
// only a fallback.
func TestExecuteInteractiveLineCtlSuppliedParametersSkipThePrompt(t *testing.T) {
	stub := ctlStub(protocol.Capability{Name: "ctl.pause"})
	state := ctlState()
	var output, diagnostics strings.Builder
	_, err := executeInteractiveLine(context.Background(), stub, state, "ctl pause reason=maintenance", ctlLines("y"), &output, &output, &diagnostics, InteractiveOptions{WaitTimeoutMS: 100})
	if err != nil {
		t.Fatalf("executeInteractiveLine: %v", err)
	}
	if stub.admit != 1 {
		t.Fatalf("admitted %d commands, want 1", stub.admit)
	}
	if !sameJSONObject(stub.intents[0].Payload, `{"reason":"maintenance"}`) {
		t.Fatalf("payload = %q, want the supplied parameter", stub.intents[0].Payload)
	}
	if strings.Contains(output.String(), "Parameters for") {
		t.Fatalf("supplied parameters must not prompt again: %q", output.String())
	}
	if !strings.Contains(output.String(), "Parameters: reason=maintenance") {
		t.Fatalf("output missing the guided preview: %q", output.String())
	}
}
