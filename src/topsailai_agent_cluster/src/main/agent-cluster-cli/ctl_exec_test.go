package main

import (
	"context"
	"encoding/json"
	"strings"
	"testing"

	"topsailai_agent_cluster/internal/protocol"
	"topsailai_agent_cluster/internal/tui"
)

// ctlExecStub records the intents the standalone ctl and exec commands admit and
// advertises the capabilities those commands preflight.
type ctlExecStub struct {
	capabilities []protocol.Capability
	intents      []protocol.ImmutableIntent
	command      map[string]any
}

// ListEndpoints returns one endpoint so the commands have a target.
func (s *ctlExecStub) ListEndpoints(context.Context) ([]protocol.Endpoint, error) {
	return []protocol.Endpoint{{EndpointID: "ep"}}, nil
}

// GetInventory returns a complete report with one session.
func (s *ctlExecStub) GetInventory(context.Context, string) (protocol.InventoryReport, error) {
	return protocol.InventoryReport{ReportComplete: true, CollectionStatus: protocol.CollectionSucceeded}, nil
}

// GetCapabilities returns the caller-supplied descriptor.
func (s *ctlExecStub) GetCapabilities(context.Context, string) (protocol.CapabilityDescriptor, error) {
	return protocol.CapabilityDescriptor{Revision: "rev-1", Capabilities: s.capabilities}, nil
}

// GetCommand returns the terminal receipt the wait loop observes.
func (s *ctlExecStub) GetCommand(context.Context, string) (map[string]any, error) {
	if s.command == nil {
		return map[string]any{"status": string(protocol.StatusFinished)}, nil
	}
	return s.command, nil
}

// ListCommands returns no history.
func (s *ctlExecStub) ListCommands(context.Context, string, string, int) ([]map[string]any, error) {
	return nil, nil
}

// GetOutput returns an empty bounded snapshot.
func (s *ctlExecStub) GetOutput(context.Context, string, string, string, int, int) (protocol.OutputSnapshotResponse, error) {
	return protocol.OutputSnapshotResponse{}, nil
}

// AdmitCommand records the intent and returns a durable command identifier.
func (s *ctlExecStub) AdmitCommand(_ context.Context, intent protocol.ImmutableIntent) (map[string]any, error) {
	s.intents = append(s.intents, intent)
	return map[string]any{"command_id": "cmd-1"}, nil
}

// ctlExecStubFor returns a stub advertising the supplied capabilities.
func ctlExecStubFor(capabilities ...protocol.Capability) *ctlExecStub {
	return &ctlExecStub{capabilities: capabilities}
}

// TestCtlCommandAdmitsTheAdvertisedOperation proves the standalone control command
// submits the advertised ctl.<action> operation against the exact generation and
// carries the advertised version, so the Endpoint can match it.
func TestCtlCommandAdmitsTheAdvertisedOperation(t *testing.T) {
	stub := ctlExecStubFor(protocol.Capability{Name: "ctl.heartbeat", Version: "2"})
	var output strings.Builder
	args := []string{"ctl", "ep", "session", "heartbeat", `{"note":"x"}`, "gen"}
	if err := ctlCommand(context.Background(), stub, &output, args, true, false, 100, ""); err != nil {
		t.Fatalf("ctlCommand: %v", err)
	}
	if len(stub.intents) != 1 {
		t.Fatalf("intents = %d, want 1", len(stub.intents))
	}
	intent := stub.intents[0]
	if intent.Operation != "ctl.heartbeat" {
		t.Fatalf("operation = %q, want ctl.heartbeat", intent.Operation)
	}
	if intent.OperationVersion != "2" {
		t.Fatalf("operation version = %q, want the advertised 2", intent.OperationVersion)
	}
	if intent.Target == nil || intent.Target.ResourceID != "session" || intent.Target.Generation != "gen" {
		t.Fatalf("target = %+v, want session/gen", intent.Target)
	}
	if string(intent.Payload) != `{"note":"x"}` {
		t.Fatalf("payload = %q, want the supplied object", intent.Payload)
	}
}

// TestCtlCommandDefaultsThePayload proves an omitted payload becomes the empty
// object rather than an empty byte slice the Endpoint would reject.
func TestCtlCommandDefaultsThePayload(t *testing.T) {
	stub := ctlExecStubFor(protocol.Capability{Name: "ctl.heartbeat"})
	if err := ctlCommand(context.Background(), stub, &strings.Builder{}, []string{"ctl", "ep", "session", "heartbeat"}, true, false, 100, "gen"); err != nil {
		t.Fatalf("ctlCommand: %v", err)
	}
	if got := string(stub.intents[0].Payload); got != "{}" {
		t.Fatalf("payload = %q, want {}", got)
	}
}

// TestCtlCommandUsesTheGenerationFlag proves the flag form is accepted as an
// alternative to the positional generation.
func TestCtlCommandUsesTheGenerationFlag(t *testing.T) {
	stub := ctlExecStubFor(protocol.Capability{Name: "ctl.heartbeat"})
	if err := ctlCommand(context.Background(), stub, &strings.Builder{}, []string{"ctl", "ep", "session", "heartbeat"}, true, false, 100, "gen-flag"); err != nil {
		t.Fatalf("ctlCommand: %v", err)
	}
	if got := stub.intents[0].Target.Generation; got != "gen-flag" {
		t.Fatalf("generation = %q, want gen-flag", got)
	}
}

// TestCtlCommandRequiresConfirmation proves the mutating command is never
// submitted without --yes, so an unattended script cannot send a control action.
func TestCtlCommandRequiresConfirmation(t *testing.T) {
	stub := ctlExecStubFor(protocol.Capability{Name: "ctl.heartbeat"})
	err := ctlCommand(context.Background(), stub, &strings.Builder{}, []string{"ctl", "ep", "session", "heartbeat"}, false, false, 100, "gen")
	if err == nil || !strings.Contains(err.Error(), "confirmation required for ctl heartbeat") {
		t.Fatalf("error = %v, want a confirmation requirement", err)
	}
	if len(stub.intents) != 0 {
		t.Fatalf("unconfirmed control admitted %d commands", len(stub.intents))
	}
}

// TestCtlCommandRejectsMalformedArguments proves every malformed form fails before
// a command is admitted, so a typo cannot become a mutating request.
func TestCtlCommandRejectsMalformedArguments(t *testing.T) {
	cases := []struct {
		name string
		args []string
		want string
	}{
		{name: "no arguments", args: nil, want: "usage: ctl <endpoint-id> <resource-id> <action> [json] [generation]"},
		{name: "missing action", args: []string{"ctl", "ep", "session"}, want: "usage: ctl <endpoint-id> <resource-id> <action> [json] [generation]"},
		{name: "misplaced flag", args: []string{"ctl", "ep", "session", "--json"}, want: `option "--json" must be written before the command; run help ctl for valid syntax`},
		{name: "surplus argument", args: []string{"ctl", "ep", "session", "heartbeat", "{}", "gen", "extra"}, want: `unexpected arguments "extra"; run help ctl for valid syntax`},
		{name: "bad payload", args: []string{"ctl", "ep", "session", "heartbeat", "nope"}, want: "payload must be a JSON object"},
	}
	for _, testCase := range cases {
		t.Run(testCase.name, func(t *testing.T) {
			stub := ctlExecStubFor(protocol.Capability{Name: "ctl.heartbeat"})
			err := ctlCommand(context.Background(), stub, &strings.Builder{}, testCase.args, true, false, 100, "")
			if err == nil || err.Error() != testCase.want {
				t.Fatalf("error = %v, want %q", err, testCase.want)
			}
			if len(stub.intents) != 0 {
				t.Fatalf("malformed control admitted %d commands", len(stub.intents))
			}
		})
	}
}

// TestCtlCommandRejectsUnadvertisedAction proves an action the Endpoint does not
// advertise fails during preflight, before admission.
func TestCtlCommandRejectsUnadvertisedAction(t *testing.T) {
	stub := ctlExecStubFor(protocol.Capability{Name: "ctl.heartbeat"})
	err := ctlCommand(context.Background(), stub, &strings.Builder{}, []string{"ctl", "ep", "session", "hard_interrupt"}, true, false, 100, "gen")
	if err == nil || !strings.Contains(err.Error(), "unsupported capability") {
		t.Fatalf("error = %v, want an unsupported-capability rejection", err)
	}
	if len(stub.intents) != 0 {
		t.Fatalf("unadvertised action admitted %d commands", len(stub.intents))
	}
}

// TestExecCommandAdmitsTheArgvArray proves the standalone exec command submits
// command.exec with the argv array taken verbatim from the separator form.
func TestExecCommandAdmitsTheArgvArray(t *testing.T) {
	stub := ctlExecStubFor(protocol.Capability{Name: protocol.OperationCommandExec, Version: protocol.CommandExecPayloadVersion})
	args := []string{"exec", "ep", "session", "gen", "--", "git", "status", "--short"}
	if err := execCommand(context.Background(), stub, &strings.Builder{}, args, true, false, 100, ""); err != nil {
		t.Fatalf("execCommand: %v", err)
	}
	if len(stub.intents) != 1 {
		t.Fatalf("intents = %d, want 1", len(stub.intents))
	}
	intent := stub.intents[0]
	if intent.Operation != protocol.OperationCommandExec {
		t.Fatalf("operation = %q, want %q", intent.Operation, protocol.OperationCommandExec)
	}
	if intent.OperationVersion != protocol.CommandExecPayloadVersion {
		t.Fatalf("operation version = %q, want %q", intent.OperationVersion, protocol.CommandExecPayloadVersion)
	}
	if intent.Target == nil || intent.Target.ResourceID != "session" || intent.Target.Generation != "gen" {
		t.Fatalf("target = %+v, want session/gen", intent.Target)
	}
	var request protocol.CommandExecRequest
	if err := json.Unmarshal(intent.Payload, &request); err != nil {
		t.Fatalf("decode payload: %v", err)
	}
	want := []string{"git", "status", "--short"}
	if len(request.Argv) != len(want) {
		t.Fatalf("argv = %q, want %q", request.Argv, want)
	}
	for index := range want {
		if request.Argv[index] != want[index] {
			t.Fatalf("argv = %q, want %q", request.Argv, want)
		}
	}
}

// TestExecCommandKeepsFlagLikeArguments proves an argument beginning with a dash
// after the separator is part of the argv array, not a misplaced option.
func TestExecCommandKeepsFlagLikeArguments(t *testing.T) {
	stub := ctlExecStubFor(protocol.Capability{Name: protocol.OperationCommandExec, Version: protocol.CommandExecPayloadVersion})
	args := []string{"exec", "ep", "session", "gen", "--", "ls", "-la"}
	if err := execCommand(context.Background(), stub, &strings.Builder{}, args, true, false, 100, ""); err != nil {
		t.Fatalf("execCommand: %v", err)
	}
	var request protocol.CommandExecRequest
	if err := json.Unmarshal(stub.intents[0].Payload, &request); err != nil {
		t.Fatalf("decode payload: %v", err)
	}
	if len(request.Argv) != 2 || request.Argv[1] != "-la" {
		t.Fatalf("argv = %q, want [ls -la]", request.Argv)
	}
}

// TestExecCommandRejectsMalformedArguments proves every malformed form fails
// before admission, including a missing separator and a missing generation.
func TestExecCommandRejectsMalformedArguments(t *testing.T) {
	cases := []struct {
		name string
		args []string
		want string
	}{
		{name: "no separator", args: []string{"exec", "ep", "session", "gen", "ls"}, want: "usage: exec <endpoint-id> <resource-id> <generation> -- <argv...>"},
		{name: "no argv", args: []string{"exec", "ep", "session", "gen", "--"}, want: "usage: exec <endpoint-id> <resource-id> <generation> -- <argv...>"},
		{name: "missing target", args: []string{"exec", "ep", "--", "ls"}, want: "usage: exec <endpoint-id> <resource-id> <generation> -- <argv...>"},
		{name: "misplaced flag", args: []string{"exec", "ep", "session", "--json", "--", "ls"}, want: `option "--json" must be written before the command; run help exec for valid syntax`},
		{name: "surplus head", args: []string{"exec", "ep", "session", "gen", "extra", "--", "ls"}, want: `unexpected arguments "extra"; run help exec for valid syntax`},
		{name: "missing generation", args: []string{"exec", "ep", "session", "--", "ls"}, want: "exec requires a generation; run help exec for valid syntax"},
	}
	for _, testCase := range cases {
		t.Run(testCase.name, func(t *testing.T) {
			stub := ctlExecStubFor(protocol.Capability{Name: protocol.OperationCommandExec, Version: protocol.CommandExecPayloadVersion})
			err := execCommand(context.Background(), stub, &strings.Builder{}, testCase.args, true, false, 100, "")
			if err == nil || err.Error() != testCase.want {
				t.Fatalf("error = %v, want %q", err, testCase.want)
			}
			if len(stub.intents) != 0 {
				t.Fatalf("malformed exec admitted %d commands", len(stub.intents))
			}
		})
	}
}

// TestExecCommandRequiresConfirmation proves the mutating command is never
// submitted without --yes.
func TestExecCommandRequiresConfirmation(t *testing.T) {
	stub := ctlExecStubFor(protocol.Capability{Name: protocol.OperationCommandExec, Version: protocol.CommandExecPayloadVersion})
	err := execCommand(context.Background(), stub, &strings.Builder{}, []string{"exec", "ep", "session", "gen", "--", "ls"}, false, false, 100, "")
	if err == nil || !strings.Contains(err.Error(), "confirmation required for exec") {
		t.Fatalf("error = %v, want a confirmation requirement", err)
	}
	if len(stub.intents) != 0 {
		t.Fatalf("unconfirmed exec admitted %d commands", len(stub.intents))
	}
}

// TestExecCommandRendersTheSnapshot proves a command.exec receipt is rendered
// through the shared renderer, so the standalone and interactive surfaces cannot
// disagree about the receipt fields or the output sanitization.
func TestExecCommandRendersTheSnapshot(t *testing.T) {
	document, err := json.Marshal(protocol.CommandExecResult{
		Argv:     []string{"echo", "hello"},
		ExitCode: 0,
		Stdout:   "hello\n",
	})
	if err != nil {
		t.Fatalf("marshal result: %v", err)
	}
	stub := ctlExecStubFor(protocol.Capability{Name: protocol.OperationCommandExec, Version: protocol.CommandExecPayloadVersion})
	stub.command = map[string]any{
		"command_id":        "cmd-1",
		"status":            string(protocol.StatusFinished),
		"delivery_boundary": string(protocol.DeliverySubmitted),
		"effect_certainty":  string(protocol.EffectAcknowledged),
		"provider_response": string(document),
	}
	var output strings.Builder
	if err := execCommand(context.Background(), stub, &output, []string{"exec", "ep", "session", "gen", "--", "echo", "hello"}, true, false, 100, ""); err != nil {
		t.Fatalf("execCommand: %v", err)
	}
	if !strings.Contains(output.String(), "hello") {
		t.Fatalf("output missing the snapshot: %q", output.String())
	}
	if !strings.Contains(output.String(), "exit_code") {
		t.Fatalf("output missing the exit code: %q", output.String())
	}
}

// TestSubmitActionJSONModeRendersTheDurableResult proves --json keeps the machine
// readable envelope instead of the human receipt.
func TestSubmitActionJSONModeRendersTheDurableResult(t *testing.T) {
	stub := ctlExecStubFor(protocol.Capability{Name: "ctl.heartbeat"})
	var output strings.Builder
	request := tuiActionRequest("ctl.heartbeat", "ctl heartbeat")
	if err := submitAction(context.Background(), stub, &output, request, true); err != nil {
		t.Fatalf("submitAction: %v", err)
	}
	if !strings.Contains(output.String(), `"status": "finished"`) {
		t.Fatalf("output is not the durable JSON result: %q", output.String())
	}
}

// TestSubmitActionRejectsUnadvertisedOperation proves the shared sequence keeps
// the capability preflight, so a new command cannot skip it.
func TestSubmitActionRejectsUnadvertisedOperation(t *testing.T) {
	stub := ctlExecStubFor(protocol.Capability{Name: "ctl.heartbeat"})
	err := submitAction(context.Background(), stub, &strings.Builder{}, tuiActionRequest("ctl.pause", "ctl pause"), false)
	if err == nil || !strings.Contains(err.Error(), "unsupported capability") {
		t.Fatalf("error = %v, want an unsupported-capability rejection", err)
	}
	if len(stub.intents) != 0 {
		t.Fatalf("unadvertised operation admitted %d commands", len(stub.intents))
	}
}

// tuiActionRequest builds the immutable action request the shared submit
// sequence consumes, so a test can exercise it without the argument parsing.
func tuiActionRequest(operation, label string) tui.ActionRequest {
	return tui.ActionRequest{
		Operation:      operation,
		OperationLabel: label,
		EndpointID:     "ep",
		ResourceID:     "session",
		Generation:     "gen",
		Payload:        json.RawMessage(`{}`),
		Confirmed:      true,
		WaitTimeoutMS:  100,
	}
}
