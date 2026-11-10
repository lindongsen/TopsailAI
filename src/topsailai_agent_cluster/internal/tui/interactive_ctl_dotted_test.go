package tui

import (
	"context"
	"strings"
	"testing"

	"topsailai_agent_cluster/internal/protocol"
)

// TestCtlDottedActionDetectsTheSpelling proves the dotted form is recognised from
// the command word alone and that a plain command word is never mistaken for it.
func TestCtlDottedActionDetectsTheSpelling(t *testing.T) {
	cases := []struct {
		name       string
		word       string
		wantAction string
		wantDotted bool
	}{
		{name: "action", word: "ctl.heartbeat", wantAction: "heartbeat", wantDotted: true},
		{name: "underscored action", word: "ctl.get_session_messages", wantAction: "get_session_messages", wantDotted: true},
		{name: "empty action", word: "ctl.", wantAction: "", wantDotted: true},
		{name: "spaced spelling", word: "ctl", wantDotted: false},
		{name: "other command", word: "send", wantDotted: false},
		{name: "prefix without dot", word: "ctlheartbeat", wantDotted: false},
		{name: "empty word", word: "", wantDotted: false},
	}
	for _, testCase := range cases {
		t.Run(testCase.name, func(t *testing.T) {
			action, dotted := ctlDottedAction(testCase.word)
			if dotted != testCase.wantDotted || action != testCase.wantAction {
				t.Fatalf("ctlDottedAction(%q) = %q/%v, want %q/%v",
					testCase.word, action, dotted, testCase.wantAction, testCase.wantDotted)
			}
		})
	}
}

// TestParseCtlDottedArguments proves every remaining token is one guided
// parameter, so a second bare word is rejected instead of being reinterpreted as
// an action, and a JSON document is no longer accepted.
func TestParseCtlDottedArguments(t *testing.T) {
	cases := []struct {
		name       string
		action     string
		rest       string
		wantAction string
		wantPay    string
		wantErr    string
	}{
		{name: "omitted parameters", action: "heartbeat", rest: "", wantAction: "heartbeat", wantPay: "{}"},
		{name: "whitespace parameters", action: "heartbeat", rest: "   ", wantAction: "heartbeat", wantPay: "{}"},
		{name: "one parameter", action: "pause", rest: "reason=x", wantAction: "pause", wantPay: `{"reason":"x"}`},
		{name: "two parameters", action: "pause", rest: "reason=x timeout_seconds=300", wantAction: "pause", wantPay: `{"reason":"x","timeout_seconds":300}`},
		{name: "surrounding spaces", action: "pause", rest: "  reason=x  ", wantAction: "pause", wantPay: `{"reason":"x"}`},
		{name: "second bare word", action: "heartbeat", rest: "heartbeat", wantErr: "must be key=value"},
		{name: "json document", action: "pause", rest: `{"reason":"x"}`, wantErr: "must be key=value"},
		{name: "empty action", action: "", rest: "", wantErr: ctlDottedUsage},
		{name: "flag-like action", action: "--json", rest: "", wantErr: ctlDottedUsage},
	}
	for _, testCase := range cases {
		t.Run(testCase.name, func(t *testing.T) {
			action, payload, err := parseCtlDottedArguments(testCase.action, testCase.rest)
			if testCase.wantErr != "" {
				if err == nil || !strings.Contains(err.Error(), testCase.wantErr) {
					t.Fatalf("error = %v, want it to contain %q", err, testCase.wantErr)
				}
				return
			}
			if err != nil {
				t.Fatalf("parseCtlDottedArguments(%q, %q) error: %v", testCase.action, testCase.rest, err)
			}
			if action != testCase.wantAction || !sameJSONObject(payload, testCase.wantPay) {
				t.Fatalf("action=%q payload=%q, want %q/%q", action, payload, testCase.wantAction, testCase.wantPay)
			}
		})
	}
}

// TestExecuteInteractiveLineCtlDottedSkipsTheActionPrompt proves the dotted form
// admits the named action without rendering the action list. Only the
// confirmation answer is supplied, so a prompt for the action would consume it
// and fail with an unknown-action rejection instead of admitting the command.
func TestExecuteInteractiveLineCtlDottedSkipsTheActionPrompt(t *testing.T) {
	stub := ctlStub(
		protocol.Capability{Name: "ctl.heartbeat", Version: "2"},
		protocol.Capability{Name: "ctl.pause"},
	)
	state := ctlState()
	var output, diagnostics strings.Builder
	_, err := executeInteractiveLine(context.Background(), stub, state, `ctl.heartbeat note=x`, ctlLines("y"), &output, &output, &diagnostics, InteractiveOptions{WaitTimeoutMS: 100})
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
	if strings.Contains(output.String(), "Control actions:") {
		t.Fatalf("dotted spelling must not render the action list: %q", output.String())
	}
	if !strings.Contains(output.String(), "CommandID: cmd-1") {
		t.Fatalf("output missing the receipt: %q", output.String())
	}
}

// TestExecuteInteractiveLineCtlDottedWithoutPayload proves the dotted form guides
// the operator through the parameters and sends the empty object when the answer
// is empty, so no JSON is ever required.
func TestExecuteInteractiveLineCtlDottedWithoutPayload(t *testing.T) {
	stub := ctlStub(protocol.Capability{Name: "ctl.heartbeat"})
	state := ctlState()
	var output, diagnostics strings.Builder
	_, err := executeInteractiveLine(context.Background(), stub, state, "ctl.heartbeat", ctlLines("", "y"), &output, &output, &diagnostics, InteractiveOptions{WaitTimeoutMS: 100})
	if err != nil {
		t.Fatalf("executeInteractiveLine: %v", err)
	}
	if stub.admit != 1 {
		t.Fatalf("admitted %d commands, want 1", stub.admit)
	}
	if got := string(stub.intents[0].Payload); got != "{}" {
		t.Fatalf("payload = %q, want the empty object", got)
	}
	if !strings.Contains(output.String(), "Parameters for heartbeat:") {
		t.Fatalf("output missing the guided parameter prompt: %q", output.String())
	}
}

// TestExecuteInteractiveLineCtlDottedKeepsTheConfirmationGate proves the dotted
// form is still a mutating request, so a declined confirmation admits nothing.
// The parameter answer is empty because the guided prompt runs before the
// confirmation, so the confirmation answer must be the second line.
func TestExecuteInteractiveLineCtlDottedKeepsTheConfirmationGate(t *testing.T) {
	stub := ctlStub(protocol.Capability{Name: "ctl.heartbeat"})
	state := ctlState()
	var output, diagnostics strings.Builder
	_, err := executeInteractiveLine(context.Background(), stub, state, "ctl.heartbeat", ctlLines("", "n"), &output, &output, &diagnostics, InteractiveOptions{WaitTimeoutMS: 100})
	if err != nil {
		t.Fatalf("executeInteractiveLine: %v", err)
	}
	if stub.admit != 0 {
		t.Fatalf("declined dotted control admitted %d commands", stub.admit)
	}
	if !strings.Contains(output.String(), "ctl heartbeat cancelled") {
		t.Fatalf("missing cancellation notice: %q", output.String())
	}
}

// TestExecuteInteractiveLineCtlDottedRequiresSessionScope proves the dotted form
// inherits the session-only scope rule instead of becoming a second command.
func TestExecuteInteractiveLineCtlDottedRequiresSessionScope(t *testing.T) {
	stub := ctlStub(protocol.Capability{Name: "ctl.heartbeat"})
	state := shellState()
	var output, diagnostics strings.Builder
	_, err := executeInteractiveLine(context.Background(), stub, state, "ctl.heartbeat", ctlLines("y"), &output, &output, &diagnostics, InteractiveOptions{WaitTimeoutMS: 100})
	if err == nil || !strings.Contains(err.Error(), "unavailable in workspace scope") {
		t.Fatalf("error = %v, want a scope rejection", err)
	}
	if stub.admit != 0 {
		t.Fatalf("out-of-scope dotted control admitted %d commands", stub.admit)
	}
}

// TestExecuteInteractiveLineCtlDottedRejectsUnadvertisedAction proves the dotted
// form still fails during preflight for an action the Endpoint does not advertise.
func TestExecuteInteractiveLineCtlDottedRejectsUnadvertisedAction(t *testing.T) {
	stub := ctlStub(protocol.Capability{Name: "ctl.heartbeat"})
	state := ctlState()
	var output, diagnostics strings.Builder
	_, err := executeInteractiveLine(context.Background(), stub, state, "ctl.hard_interrupt", ctlLines("y"), &output, &output, &diagnostics, InteractiveOptions{WaitTimeoutMS: 100})
	if err == nil || !strings.Contains(err.Error(), "unsupported capability") {
		t.Fatalf("error = %v, want an unsupported-capability rejection", err)
	}
	if stub.admit != 0 {
		t.Fatalf("unadvertised dotted action admitted %d commands", stub.admit)
	}
}

// TestExecuteInteractiveLineCtlDottedRejectsSecondWord proves a dotted line with a
// second bare word is rejected rather than silently ignored. The second word is
// read as a parameter, so it must be a key=value pair.
func TestExecuteInteractiveLineCtlDottedRejectsSecondWord(t *testing.T) {
	stub := ctlStub(protocol.Capability{Name: "ctl.heartbeat"})
	state := ctlState()
	var output, diagnostics strings.Builder
	_, err := executeInteractiveLine(context.Background(), stub, state, "ctl.heartbeat pause", ctlLines("y"), &output, &output, &diagnostics, InteractiveOptions{WaitTimeoutMS: 100})
	if err == nil || !strings.Contains(err.Error(), "must be key=value") {
		t.Fatalf("error = %v, want a parameter rejection", err)
	}
	if stub.admit != 0 {
		t.Fatalf("malformed dotted control admitted %d commands", stub.admit)
	}
}

// TestHelpTargetResolvesTheDottedSpelling proves help for a dotted spelling lands
// on the ctl entry instead of reporting an unknown command for a spelling the
// dispatcher accepts.
func TestHelpTargetResolvesTheDottedSpelling(t *testing.T) {
	cases := map[string]string{
		"ctl.heartbeat":             "ctl",
		"  CTL.Pause  ":             "ctl",
		"/ctl.get_session_messages": "ctl",
		"ctl":                       "ctl",
		"send":                      "send",
	}
	for target, want := range cases {
		if got := helpTarget(target); got != want {
			t.Fatalf("helpTarget(%q) = %q, want %q", target, got, want)
		}
	}
}

// TestDiagnosticCommandNameResolvesTheDottedSpelling proves a rejected dotted line
// points at the ctl help rather than at a command that does not exist.
func TestDiagnosticCommandNameResolvesTheDottedSpelling(t *testing.T) {
	if got := diagnosticCommandName("ctl.heartbeat", ScopeSession); got != "ctl" {
		t.Fatalf("diagnosticCommandName = %q, want ctl", got)
	}
	if got := diagnosticCommandName("ctl heartbeat", ScopeSession); got != "ctl" {
		t.Fatalf("diagnosticCommandName = %q, want ctl", got)
	}
	if got := diagnosticCommandName("send hello", ScopeSession); got != "send" {
		t.Fatalf("diagnosticCommandName = %q, want send", got)
	}
}

// TestDiagnosticCommandNameKeepsNumericShorthandOutOfSessionScope proves a bare
// number is reported under its own literal word in session scope, because the
// numeric shorthand is a navigation form that scope does not offer. Reporting it
// as "cd" would point the operator at a command the scope rejects.
func TestDiagnosticCommandNameKeepsNumericShorthandOutOfSessionScope(t *testing.T) {
	if got := diagnosticCommandName("1", ScopeWorkspace); got != "cd" {
		t.Fatalf("workspace diagnosticCommandName = %q, want cd", got)
	}
	if got := diagnosticCommandName("1", ScopeEndpoint); got != "cd" {
		t.Fatalf("endpoint diagnosticCommandName = %q, want cd", got)
	}
	if got := diagnosticCommandName("1", ScopeSession); got != "1" {
		t.Fatalf("session diagnosticCommandName = %q, want the literal word", got)
	}
}

// TestExecuteInteractiveLineCtlDottedShortcutAdmitsTheShortcut proves a configured
// shortcut is reachable through the dotted spelling with no client change. The
// Endpoint advertises one capability per catalog entry, so a shortcut arrives as
// its own capability name and the dotted spelling sends that exact name. The
// client never resolves the shortcut to its target, because resolution belongs to
// the Endpoint catalog and a client-side table would drift from the file.
func TestExecuteInteractiveLineCtlDottedShortcutAdmitsTheShortcut(t *testing.T) {
	stub := ctlStub(
		protocol.Capability{Name: "ctl.get_session_messages", Version: "1"},
		protocol.Capability{Name: "ctl.session.messages", Version: "1"},
	)
	state := ctlState()
	var output, diagnostics strings.Builder
	_, err := executeInteractiveLine(context.Background(), stub, state, "ctl.session.messages", ctlLines("", "y"), &output, &output, &diagnostics, InteractiveOptions{WaitTimeoutMS: 100})
	if err != nil {
		t.Fatalf("executeInteractiveLine: %v", err)
	}
	if stub.admit != 1 {
		t.Fatalf("admitted %d commands, want 1", stub.admit)
	}
	if got := stub.intents[0].Operation; got != "ctl.session.messages" {
		t.Fatalf("operation = %q, want the shortcut name", got)
	}
	if strings.Contains(output.String(), "Control actions:") {
		t.Fatalf("the dotted shortcut must not render the action list: %q", output.String())
	}
}

// TestExecuteInteractiveLineCtlDottedShortcutRejectsAnUnconfiguredShortcut proves
// a shortcut that the catalog does not carry is refused during preflight, so a
// plausible-looking dotted name never reaches the provider.
func TestExecuteInteractiveLineCtlDottedShortcutRejectsAnUnconfiguredShortcut(t *testing.T) {
	stub := ctlStub(protocol.Capability{Name: "ctl.get_session_messages"})
	state := ctlState()
	var output, diagnostics strings.Builder
	_, err := executeInteractiveLine(context.Background(), stub, state, "ctl.session.messages", ctlLines("y"), &output, &output, &diagnostics, InteractiveOptions{WaitTimeoutMS: 100})
	if err == nil || !strings.Contains(err.Error(), "unsupported capability") {
		t.Fatalf("error = %v, want an unsupported-capability rejection", err)
	}
	if stub.admit != 0 {
		t.Fatalf("unconfigured shortcut admitted %d commands", stub.admit)
	}
}
