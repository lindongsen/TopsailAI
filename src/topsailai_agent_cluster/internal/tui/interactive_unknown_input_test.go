package tui

import (
	"context"
	"encoding/json"
	"strings"
	"testing"

	"topsailai_agent_cluster/internal/protocol"
)

// sessionScopeInput prefixes a session-scope navigation so every case starts in
// the scope where the send offer is available.
const sessionScopeInput = "cd host-one/endpoint-1/res-1\n"

// TestUnknownInputOffersSendInSessionScope proves an unrecognized line is offered
// as a message and that accepting the offer admits exactly one send command.
func TestUnknownInputOffersSendInSessionScope(t *testing.T) {
	stub := scopeStub()
	output, diagnostics := runScope(t, stub, sessionScopeInput+"hello world\ny\nquit\n", ColorPolicy{})
	if diagnostics != "" {
		t.Fatalf("unexpected diagnostics: %q", diagnostics)
	}
	if stub.admit != 1 {
		t.Fatalf("admitted %d commands, want 1", stub.admit)
	}
	if !strings.Contains(output, "as a message?") {
		t.Fatalf("missing send offer: %q", output)
	}
	if !strings.Contains(output, "command submitted:") {
		t.Fatalf("missing submission evidence: %q", output)
	}
	if got := intentPayloadText(t, stub.intents[0]); got != "hello world" {
		t.Fatalf("payload text = %q, want the whole literal line", got)
	}
	if stub.intents[0].Operation != protocol.OperationMessageSend {
		t.Fatalf("operation = %q, want %q", stub.intents[0].Operation, protocol.OperationMessageSend)
	}
}

// TestUnknownInputKeepsFirstWordInPayload proves the offer sends the literal line
// rather than the words after the unrecognized word, so accepting the offer never
// silently drops text the operator typed.
func TestUnknownInputKeepsFirstWordInPayload(t *testing.T) {
	stub := scopeStub()
	_, diagnostics := runScope(t, stub, sessionScopeInput+"deploy the release now\nyes\nquit\n", ColorPolicy{})
	if diagnostics != "" {
		t.Fatalf("unexpected diagnostics: %q", diagnostics)
	}
	if stub.admit != 1 {
		t.Fatalf("admitted %d commands, want 1", stub.admit)
	}
	if got := intentPayloadText(t, stub.intents[0]); got != "deploy the release now" {
		t.Fatalf("payload text = %q, want the whole literal line", got)
	}
}

// TestUnknownInputDeclinedKeepsDiagnostic proves a declined offer reports the typo
// instead of admitting a command, so no mutating action is inferred from a refusal.
func TestUnknownInputDeclinedKeepsDiagnostic(t *testing.T) {
	for _, answer := range []string{"n", "", "no"} {
		t.Run("answer="+answer, func(t *testing.T) {
			stub := scopeStub()
			_, diagnostics := runScope(t, stub, sessionScopeInput+"hello world\n"+answer+"\nquit\n", ColorPolicy{})
			if stub.admit != 0 {
				t.Fatalf("declined offer admitted %d commands", stub.admit)
			}
			assertActionableError(t, diagnostics, `error: unknown command "hello" (try help)`)
		})
	}
}

// TestUnknownInputUnreadableAnswerKeepsDiagnostic proves an incomplete answer
// cannot authorize a send, because a partial line is not a confirmation.
func TestUnknownInputUnreadableAnswerKeepsDiagnostic(t *testing.T) {
	stub := scopeStub()
	_, diagnostics := runScope(t, stub, sessionScopeInput+"hello world\ny", ColorPolicy{})
	if stub.admit != 0 {
		t.Fatalf("partial answer admitted %d commands", stub.admit)
	}
	assertActionableError(t, diagnostics, `error: unknown command "hello" (try help)`)
}

// TestUnknownInputOutsideSessionScopeKeepsDiagnostic proves the offer is limited to
// session scope, where send is available; elsewhere the plain diagnostic is kept
// because an accepted offer could never be honoured.
func TestUnknownInputOutsideSessionScopeKeepsDiagnostic(t *testing.T) {
	cases := []struct {
		name  string
		input string
	}{
		{name: "workspace", input: "hello world\nquit\n"},
		{name: "endpoint", input: "cd host-one/endpoint-1\nhello world\nquit\n"},
	}
	for _, testCase := range cases {
		t.Run(testCase.name, func(t *testing.T) {
			stub := scopeStub()
			output, diagnostics := runScope(t, stub, testCase.input, ColorPolicy{})
			if stub.admit != 0 {
				t.Fatalf("out-of-scope offer admitted %d commands", stub.admit)
			}
			if strings.Contains(output, "as a message?") {
				t.Fatalf("out-of-scope offer must not prompt: %q", output)
			}
			assertActionableError(t, diagnostics, `error: unknown command "hello" (try help)`)
		})
	}
}

// TestUnknownInputOfferRejectsJSONFlagPayload proves the offer never promises a
// payload the send command itself rejects, so the diagnostic is reported instead.
func TestUnknownInputOfferRejectsJSONFlagPayload(t *testing.T) {
	stub := scopeStub()
	output, diagnostics := runScope(t, stub, sessionScopeInput+"--json\nquit\n", ColorPolicy{})
	if stub.admit != 0 {
		t.Fatalf("rejected payload admitted %d commands", stub.admit)
	}
	if strings.Contains(output, "as a message?") {
		t.Fatalf("rejected payload must not prompt: %q", output)
	}
	assertActionableError(t, diagnostics, `error: unknown command "--json" (try help)`)
}

// TestUnknownInputOfferSanitizesQuestion proves operator text cannot inject
// terminal control sequences into the trusted question writer.
func TestUnknownInputOfferSanitizesQuestion(t *testing.T) {
	stub := scopeStub()
	output, _ := runScope(t, stub, sessionScopeInput+"hello \x1b[31mred\x1b[0m\ny\nquit\n", ColorPolicy{})
	if strings.Contains(output, "\x1b[31m") {
		t.Fatalf("offer question leaked a control sequence: %q", output)
	}
	if stub.admit != 1 {
		t.Fatalf("admitted %d commands, want 1", stub.admit)
	}
}

// TestSendCommandStillAsksOnce proves the offer does not change the send command
// itself: one question, one admission.
func TestSendCommandStillAsksOnce(t *testing.T) {
	stub := scopeStub()
	output, diagnostics := runScope(t, stub, sessionScopeInput+"send hello world\ny\nquit\n", ColorPolicy{})
	if diagnostics != "" {
		t.Fatalf("unexpected diagnostics: %q", diagnostics)
	}
	if stub.admit != 1 {
		t.Fatalf("admitted %d commands, want 1", stub.admit)
	}
	if count := strings.Count(output, "Confirm send?"); count != 1 {
		t.Fatalf("send asked %d confirmations, want 1: %q", count, output)
	}
}

// TestUnknownInputOfferAsksOnce proves accepting the offer does not repeat the
// confirmation the operator already gave.
func TestUnknownInputOfferAsksOnce(t *testing.T) {
	stub := scopeStub()
	output, diagnostics := runScope(t, stub, sessionScopeInput+"hello world\ny\nquit\n", ColorPolicy{})
	if diagnostics != "" {
		t.Fatalf("unexpected diagnostics: %q", diagnostics)
	}
	if count := strings.Count(output, "as a message?"); count != 1 {
		t.Fatalf("offer asked %d questions, want 1: %q", count, output)
	}
	if count := strings.Count(output, "Confirm send?"); count != 0 {
		t.Fatalf("offer repeated the send confirmation %d times: %q", count, output)
	}
}

// TestUnknownInputOfferRevalidatesSelection proves the offer still fails closed when
// the pinned session generation changed, so the offer cannot bypass selection checks.
func TestUnknownInputOfferRevalidatesSelection(t *testing.T) {
	stub := refreshScopeStub()
	stub.fresh["endpoint-1"] = scopeInventory("res-1", "generation-2")
	_, diagnostics := runScope(t, stub, sessionScopeInput+"refresh\nhello world\ny\nquit\n", ColorPolicy{})
	if stub.admit != 0 {
		t.Fatalf("changed generation admitted %d commands", stub.admit)
	}
	if !strings.Contains(diagnostics, "selected session generation changed") {
		t.Fatalf("missing generation diagnostic: %q", diagnostics)
	}
}

// intentPayloadText decodes the text field of one admitted message payload.
func intentPayloadText(t *testing.T, intent protocol.ImmutableIntent) string {
	t.Helper()
	var payload struct {
		Text string `json:"text"`
	}
	if err := json.Unmarshal(intent.Payload, &payload); err != nil {
		t.Fatalf("decode payload %q: %v", string(intent.Payload), err)
	}
	return payload.Text
}

// TestUnknownInputOfferUsesInjectedReader proves the offer works through the
// injected prompt reader, which is the terminal editor path, not only the stream
// fallback.
func TestUnknownInputOfferUsesInjectedReader(t *testing.T) {
	stub := scopeStub()
	answers := []string{"cd host-one/endpoint-1/res-1", "hello world", "y", "quit"}
	index := 0
	read := func(context.Context, string, bool, int) (string, bool, error) {
		if index >= len(answers) {
			return "", false, nil
		}
		answer := answers[index]
		index++
		return answer, false, nil
	}
	var output, diagnostics strings.Builder
	if err := RunInteractive(context.Background(), stub, noPromptStream{t}, &output, &diagnostics, InteractiveOptions{ReadLine: read, WaitTimeoutMS: 100}); err != nil {
		t.Fatalf("RunInteractive: %v", err)
	}
	if stub.admit != 1 {
		t.Fatalf("admitted %d commands, want 1; diagnostics=%q", stub.admit, diagnostics.String())
	}
	if got := intentPayloadText(t, stub.intents[0]); got != "hello world" {
		t.Fatalf("payload text = %q, want the whole literal line", got)
	}
}
