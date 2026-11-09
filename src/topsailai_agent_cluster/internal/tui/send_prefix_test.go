package tui

import (
	"context"
	"strings"
	"testing"

	"topsailai_agent_cluster/internal/protocol"
)

// TestSendPrefixAliasAdmitsMessage proves "> <text>" reaches the same standard
// message payload as "send <text>", so a message can be typed directly.
func TestSendPrefixAliasAdmitsMessage(t *testing.T) {
	cases := []struct {
		name    string
		input   string
		payload string
	}{
		{name: "with space", input: "cd endpoint-1/session-1\n> hello world\nexit\n", payload: `{"text":"hello world"}`},
		{name: "without space", input: "cd endpoint-1/session-1\n>hello world\nexit\n", payload: `{"text":"hello world"}`},
		{name: "single character", input: "cd endpoint-1/session-1\n> x\nexit\n", payload: `{"text":"x"}`},
		{name: "reserved word as first word", input: "cd endpoint-1/session-1\n> stop and summarize\nexit\n", payload: `{"text":"stop and summarize"}`},
		{name: "command-like typo", input: "cd endpoint-1/session-1\n> sned hello world\nexit\n", payload: `{"text":"sned hello world"}`},
		{name: "leading spaces preserved after prefix", input: "cd endpoint-1/session-1\n>   padded\nexit\n", payload: `{"text":"padded"}`},
	}
	for _, testCase := range cases {
		t.Run(testCase.name, func(t *testing.T) {
			stub := &interactiveStub{endpoints: []protocol.Endpoint{{EndpointID: "endpoint-1"}}, reports: map[string]protocol.InventoryReport{"endpoint-1": testInventory()}}
			_, diagnostics := runScope(t, stub, testCase.input, ColorPolicy{})
			if diagnostics != "" {
				t.Fatalf("diagnostics=%q", diagnostics)
			}
			if stub.admit != 1 || len(stub.intents) != 1 {
				t.Fatalf("admitted %d commands with %d intents", stub.admit, len(stub.intents))
			}
			intent := stub.intents[0]
			if intent.Operation != protocol.OperationMessageSend {
				t.Fatalf("operation=%q want %q", intent.Operation, protocol.OperationMessageSend)
			}
			if string(intent.Payload) != testCase.payload {
				t.Fatalf("payload=%s want %s", intent.Payload, testCase.payload)
			}
		})
	}
}

// TestSendPrefixSubmitsWithoutConfirmation proves the alias submits directly,
// like an explicit send: the prefix already states the action and the text, so a
// second question could only repeat what the operator typed.
func TestSendPrefixSubmitsWithoutConfirmation(t *testing.T) {
	stub := &interactiveStub{endpoints: []protocol.Endpoint{{EndpointID: "endpoint-1"}}, reports: map[string]protocol.InventoryReport{"endpoint-1": testInventory()}}
	output, diagnostics := runScope(t, stub, "cd endpoint-1/session-1\n> hello world\nexit\n", ColorPolicy{})
	if diagnostics != "" {
		t.Fatalf("diagnostics=%q", diagnostics)
	}
	if stub.admit != 1 {
		t.Fatalf("admitted %d commands, want 1", stub.admit)
	}
	if count := strings.Count(output, "Confirm send?"); count != 0 {
		t.Fatalf("alias asked %d confirmations, want 0: %q", count, output)
	}
}

// TestSendPrefixIsRejectedOutsideSessionScope proves the alias inherits the
// scope rule of send instead of reaching the session-only action from another
// scope.
func TestSendPrefixIsRejectedOutsideSessionScope(t *testing.T) {
	cases := []struct {
		name  string
		input string
		want  string
	}{
		{
			name:  "workspace",
			input: "> hello world\nexit\n",
			want:  `error: command "send" is unavailable in workspace scope; available commands: list, endpoints, cd, show, info, start, resume, stop, drive, status, refresh, watch, history, messages, help, quit, exit`,
		},
		{
			name:  "endpoint",
			input: "cd host-one/endpoint-1\n> hello world\nexit\n",
			want:  `error: command "send" is unavailable in endpoint scope; available commands: list, cd, show, info, start, resume, stop, drive, logs, status, refresh, watch, history, messages, help, quit, exit`,
		},
	}
	for _, testCase := range cases {
		t.Run(testCase.name, func(t *testing.T) {
			stub := scopeStub()
			_, diagnostics := runScope(t, stub, testCase.input, ColorPolicy{})
			assertActionableError(t, diagnostics, testCase.want)
			if stub.admit != 0 {
				t.Fatalf("out-of-scope alias admitted %d commands", stub.admit)
			}
		})
	}
}

// TestSendPrefixDoesNotReinterpretCommands proves the prefix is disjoint from
// the command vocabulary: unprefixed commands and typos keep their existing
// behaviour, so the alias cannot fail open.
func TestSendPrefixDoesNotReinterpretCommands(t *testing.T) {
	stub := &interactiveStub{endpoints: []protocol.Endpoint{{EndpointID: "endpoint-1"}}, reports: map[string]protocol.InventoryReport{"endpoint-1": testInventory()}}
	_, diagnostics := runScope(t, stub, "cd endpoint-1/session-1\nsned hello world\nexit\n", ColorPolicy{})
	assertActionableError(t, diagnostics, `error: unknown command "sned" (try help)`)
	if stub.admit != 0 {
		t.Fatalf("typo admitted %d commands", stub.admit)
	}
}

// TestSendPrefixBareFormReadsMultiLine proves a bare prefix reuses the
// multi-line composer instead of submitting an empty message.
func TestSendPrefixBareFormReadsMultiLine(t *testing.T) {
	stub := &interactiveStub{endpoints: []protocol.Endpoint{{EndpointID: "endpoint-1"}}, reports: map[string]protocol.InventoryReport{"endpoint-1": testInventory()}}
	_, diagnostics := runScope(t, stub, "cd endpoint-1/session-1\n>\nfirst line\nsecond line\nEOF\ny\nexit\n", ColorPolicy{})
	if diagnostics != "" {
		t.Fatalf("diagnostics=%q", diagnostics)
	}
	if stub.admit != 1 || len(stub.intents) != 1 {
		t.Fatalf("admitted %d commands with %d intents", stub.admit, len(stub.intents))
	}
	if got, want := string(stub.intents[0].Payload), `{"text":"first line\nsecond line"}`; got != want {
		t.Fatalf("payload=%s want %s", got, want)
	}
}

// TestSendPrefixHelpIsInteractiveOnly proves the alias is documented where it is
// usable and never advertised on the standalone surface, where ">" is a shell
// redirect.
func TestSendPrefixHelpIsInteractiveOnly(t *testing.T) {
	var session strings.Builder
	if err := PrintScopedCommandHelp(&session, "", ScopeSession); err != nil {
		t.Fatal(err)
	}
	if !strings.Contains(session.String(), "> <text>") {
		t.Fatalf("session help does not document the alias: %q", session.String())
	}
	var all strings.Builder
	if err := PrintScopedCommandHelp(&all, "all", ScopeWorkspace); err != nil {
		t.Fatal(err)
	}
	if !strings.Contains(all.String(), ">=send") {
		t.Fatalf("help all does not list the alias: %q", all.String())
	}
	var standalone strings.Builder
	if err := PrintNonInteractiveCommandHelp(&standalone, ""); err != nil {
		t.Fatal(err)
	}
	if strings.Contains(standalone.String(), "> <text>") || strings.Contains(standalone.String(), ">=send") {
		t.Fatalf("standalone help advertised an interactive-only alias: %q", standalone.String())
	}
}

// TestSendPrefixCompletionOffersSend proves the prefix does not disturb command
// completion, which completes command words only.
func TestSendPrefixCompletionOffersSend(t *testing.T) {
	if got := canonicalCommandName(sendPrefix); got != "send" {
		t.Fatalf("canonicalCommandName(%q)=%q want send", sendPrefix, got)
	}
	if !commandAllowed(sendPrefix, ScopeSession) {
		t.Fatal("alias must be allowed in session scope")
	}
	if commandAllowed(sendPrefix, ScopeWorkspace) {
		t.Fatal("alias must be rejected in workspace scope")
	}
}

// TestSendPrefixEmptyMessageIsRejected proves an empty prefixed message admits
// nothing instead of sending blank text.
func TestSendPrefixEmptyMessageIsRejected(t *testing.T) {
	stub := &interactiveStub{endpoints: []protocol.Endpoint{{EndpointID: "endpoint-1"}}, reports: map[string]protocol.InventoryReport{"endpoint-1": testInventory()}}
	_, diagnostics := runScope(t, stub, "cd endpoint-1/session-1\n>   \nEOF\nexit\n", ColorPolicy{})
	if !strings.Contains(diagnostics, "payload must not be empty") {
		t.Fatalf("diagnostics=%q", diagnostics)
	}
	if stub.admit != 0 {
		t.Fatalf("empty message admitted %d commands", stub.admit)
	}
}

// TestSendPrefixDirectDispatch proves the dispatcher resolves the prefix before
// tokenisation, so a prefix without a separating space is still one message.
func TestSendPrefixDirectDispatch(t *testing.T) {
	stub := &interactiveStub{endpoints: []protocol.Endpoint{{EndpointID: "endpoint-1"}}, reports: map[string]protocol.InventoryReport{"endpoint-1": testInventory()}}
	state := interactiveState{}
	state.enterSession(protocol.Endpoint{EndpointID: "endpoint-1"}, "session-1", "generation-1")
	lines := make(chan lineReadResult, 1)
	var output, diagnostics strings.Builder
	if _, err := executeInteractiveLine(context.Background(), stub, &state, ">tight message", lines, &output, &output, &diagnostics, InteractiveOptions{LineLimit: 8192}); err != nil {
		t.Fatalf("executeInteractiveLine: %v", err)
	}
	if stub.admit != 1 || len(stub.intents) != 1 {
		t.Fatalf("admitted %d commands with %d intents", stub.admit, len(stub.intents))
	}
	if got, want := string(stub.intents[0].Payload), `{"text":"tight message"}`; got != want {
		t.Fatalf("payload=%s want %s", got, want)
	}
}
