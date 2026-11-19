package tui

import (
	"context"
	"encoding/json"
	"strings"
	"testing"

	"topsailai_agent_cluster/internal/protocol"
)

// shellHistoryLine builds the one-element channel the menu reads its answer from.
func shellHistoryLine(answer string) <-chan lineReadResult {
	results := make(chan lineReadResult, 1)
	results <- lineReadResult{line: answer}
	return results
}

// TestShellHistoryCandidatesFiltersAndOrders proves the menu offers only
// prefixed commands, newest first, and never offers the bare prefix itself.
//
// The bare prefix is load-bearing: it is recorded like any other command, so
// offering it would let the operator select a row that reopens this same menu.
func TestShellHistoryCandidatesFiltersAndOrders(t *testing.T) {
	commands := []string{
		"list",
		"!git status",
		"cd 3",
		"!",
		"!ls -la",
		"logs -f",
		"!  ",
	}
	got := shellHistoryCandidates(commands)
	want := []string{"!ls -la", "!git status"}
	if len(got) != len(want) {
		t.Fatalf("candidates = %q, want %q", got, want)
	}
	for index := range want {
		if got[index] != want[index] {
			t.Fatalf("candidates = %q, want %q", got, want)
		}
	}
}

// TestShellHistoryCandidatesCapsAtTen proves the filter runs before the cut.
//
// Filtering after the cut would return fewer than ten rows whenever ordinary
// commands occupy the tail, which is the common case because most REPL input is
// not a shell command.
func TestShellHistoryCandidatesCapsAtTen(t *testing.T) {
	commands := make([]string, 0, 40)
	for index := 0; index < 20; index++ {
		commands = append(commands, "list")
	}
	for index := 0; index < 15; index++ {
		commands = append(commands, "!echo "+string(rune('a'+index)))
	}
	got := shellHistoryCandidates(commands)
	if len(got) != shellHistoryLimit {
		t.Fatalf("candidates = %d, want %d", len(got), shellHistoryLimit)
	}
	// Newest first, so the last recorded command is row one.
	if got[0] != "!echo o" {
		t.Fatalf("first candidate = %q, want the newest command", got[0])
	}
}

// TestShellHistoryCandidatesEmpty proves an empty recall list yields no rows
// rather than a menu with nothing to choose.
func TestShellHistoryCandidatesEmpty(t *testing.T) {
	if got := shellHistoryCandidates(nil); len(got) != 0 {
		t.Fatalf("candidates = %q, want none", got)
	}
	if got := shellHistoryCandidates([]string{"list", "cd 1"}); len(got) != 0 {
		t.Fatalf("candidates = %q, want none for a list without shell commands", got)
	}
}

// TestResolveShellHistoryChoice proves a number resolves against the printed
// slice and every other answer is refused instead of being run.
func TestResolveShellHistoryChoice(t *testing.T) {
	candidates := []string{"!git status", "!ls -la"}
	cases := []struct {
		name    string
		answer  string
		want    string
		wantErr bool
	}{
		{name: "first row", answer: "1", want: "!git status"},
		{name: "second row", answer: "2", want: "!ls -la"},
		{name: "padded number", answer: " 2 ", want: "!ls -la"},
		{name: "empty cancels", answer: "", want: ""},
		{name: "cancel word", answer: "cancel", want: ""},
		{name: "zero is out of range", answer: "0", wantErr: true},
		{name: "past the end", answer: "3", wantErr: true},
		{name: "not a number", answer: "!rm -rf x", wantErr: true},
	}
	for _, testCase := range cases {
		t.Run(testCase.name, func(t *testing.T) {
			got, err := resolveShellHistoryChoice(candidates, testCase.answer)
			if testCase.wantErr {
				if err == nil {
					t.Fatalf("resolveShellHistoryChoice(%q) = %q, want error", testCase.answer, got)
				}
				return
			}
			if err != nil {
				t.Fatalf("resolveShellHistoryChoice(%q) error: %v", testCase.answer, err)
			}
			if got != testCase.want {
				t.Fatalf("resolveShellHistoryChoice(%q) = %q, want %q", testCase.answer, got, testCase.want)
			}
		})
	}
}

// TestPromptShellHistoryPrintsAndSelects proves the menu prints the numbered rows
// and returns the command the number selected.
func TestPromptShellHistoryPrintsAndSelects(t *testing.T) {
	var out strings.Builder
	chosen, err := promptShellHistory(context.Background(), []string{"!ls -la", "!git status"}, shellHistoryLine("2"), &out, &out, ColorPolicy{})
	if err != nil {
		t.Fatalf("promptShellHistory error: %v", err)
	}
	if chosen != "!ls -la" {
		t.Fatalf("chosen = %q, want !ls -la", chosen)
	}
	rendered := out.String()
	if !strings.Contains(rendered, "1. !git status") || !strings.Contains(rendered, "2. !ls -la") {
		t.Fatalf("menu rows missing: %q", rendered)
	}
	if !strings.Contains(rendered, shellHistoryPrompt) {
		t.Fatalf("menu prompt missing: %q", rendered)
	}
}

// TestPromptShellHistoryCancels proves an empty answer cancels without an error,
// because cancelling a prompt is a decision rather than a failure.
func TestPromptShellHistoryCancels(t *testing.T) {
	var out strings.Builder
	chosen, err := promptShellHistory(context.Background(), []string{"!git status"}, shellHistoryLine(""), &out, &out, ColorPolicy{})
	if err != nil {
		t.Fatalf("promptShellHistory error: %v", err)
	}
	if chosen != "" {
		t.Fatalf("chosen = %q, want cancellation", chosen)
	}
}

// TestPromptShellHistoryRefusesEmptyHistory proves an empty recall list reports
// how to run a command instead of printing an empty menu.
func TestPromptShellHistoryRefusesEmptyHistory(t *testing.T) {
	var out strings.Builder
	_, err := promptShellHistory(context.Background(), []string{"list"}, shellHistoryLine("1"), &out, &out, ColorPolicy{})
	if err == nil {
		t.Fatal("an empty history must be refused")
	}
	if !strings.Contains(err.Error(), "no earlier command was recorded") {
		t.Fatalf("error = %q, want a history hint", err.Error())
	}
	if strings.Contains(out.String(), "1. ") {
		t.Fatalf("an empty history must print no rows: %q", out.String())
	}
}

// TestExecuteInteractiveLineBarePrefixRunsSelectedCommand proves a bare prefix
// opens the menu and the selected command is the one submitted.
func TestExecuteInteractiveLineBarePrefixRunsSelectedCommand(t *testing.T) {
	document := execResultDocument(t, protocol.CommandExecResult{
		Argv:     []string{"git", "status"},
		ExitCode: 0,
		Stdout:   "clean\n",
	})
	stub := shellStub(map[string]any{
		"command_id":        "cmd-1",
		"status":            string(protocol.StatusFinished),
		"delivery_boundary": string(protocol.DeliverySubmitted),
		"effect_certainty":  string(protocol.EffectAcknowledged),
		"provider_response": document,
	})
	state := shellState()
	var output, diagnostics strings.Builder
	options := InteractiveOptions{
		WaitTimeoutMS: 100,
		ShellHistory:  func() []string { return []string{"list", "!ls -la", "!git status"} },
	}
	if _, err := executeInteractiveLine(context.Background(), stub, state, "!", shellHistoryLine("1"), &output, &output, &diagnostics, options); err != nil {
		t.Fatalf("executeInteractiveLine: %v", err)
	}
	if stub.admit != 1 {
		t.Fatalf("admitted %d commands, want 1", stub.admit)
	}
	intent := stub.intents[0]
	if intent.Operation != protocol.OperationCommandExec {
		t.Fatalf("operation = %q, want %q", intent.Operation, protocol.OperationCommandExec)
	}
	var request protocol.CommandExecRequest
	if err := json.Unmarshal(intent.Payload, &request); err != nil {
		t.Fatalf("decode intent payload: %v", err)
	}
	if len(request.Argv) != 2 || request.Argv[0] != "git" || request.Argv[1] != "status" {
		t.Fatalf("payload argv = %q, want [git status]", request.Argv)
	}
	if !strings.Contains(output.String(), "1. !git status") {
		t.Fatalf("menu rows missing: %q", output.String())
	}
}

// TestExecuteInteractiveLineBarePrefixCancels proves an empty answer submits
// nothing, so cancelling the menu cannot run the most recent command by accident.
func TestExecuteInteractiveLineBarePrefixCancels(t *testing.T) {
	stub := shellStub(map[string]any{"status": string(protocol.StatusFinished)})
	state := shellState()
	var output, diagnostics strings.Builder
	options := InteractiveOptions{
		WaitTimeoutMS: 100,
		ShellHistory:  func() []string { return []string{"!git status"} },
	}
	if _, err := executeInteractiveLine(context.Background(), stub, state, "!", shellHistoryLine(""), &output, &output, &diagnostics, options); err != nil {
		t.Fatalf("executeInteractiveLine: %v", err)
	}
	if stub.admit != 0 {
		t.Fatalf("admitted %d commands after cancellation, want 0", stub.admit)
	}
}

// TestExecuteInteractiveLineBarePrefixWithoutHistoryKeepsUsage proves a caller
// that supplies no history seam keeps the usage error, so the menu can never
// become a silent no-op.
func TestExecuteInteractiveLineBarePrefixWithoutHistoryKeepsUsage(t *testing.T) {
	stub := shellStub(map[string]any{"status": string(protocol.StatusFinished)})
	state := shellState()
	var output, diagnostics strings.Builder
	_, err := executeInteractiveLine(context.Background(), stub, state, "!", nil, &output, &output, &diagnostics, InteractiveOptions{WaitTimeoutMS: 100})
	if err == nil {
		t.Fatal("a bare prefix without a history seam must report usage")
	}
	if !strings.Contains(err.Error(), shellUsage) {
		t.Fatalf("error = %q, want the usage line", err.Error())
	}
	if stub.admit != 0 {
		t.Fatalf("admitted %d commands, want 0", stub.admit)
	}
}

// TestExecuteInteractiveLineBarePrefixRefusesWorkspaceScope proves the scope is
// checked before the menu is printed, so the operator is never offered a command
// that cannot run.
func TestExecuteInteractiveLineBarePrefixRefusesWorkspaceScope(t *testing.T) {
	stub := shellStub(map[string]any{"status": string(protocol.StatusFinished)})
	state := &interactiveState{}
	var output, diagnostics strings.Builder
	options := InteractiveOptions{
		WaitTimeoutMS: 100,
		ShellHistory:  func() []string { return []string{"!git status"} },
	}
	_, err := executeInteractiveLine(context.Background(), stub, state, "!", shellHistoryLine("1"), &output, &output, &diagnostics, options)
	if err == nil {
		t.Fatal("a bare prefix in workspace scope must fail")
	}
	if !strings.Contains(err.Error(), "requires a session or endpoint scope") {
		t.Fatalf("error = %q, want a scope hint", err.Error())
	}
	if strings.Contains(output.String(), "1. !git status") {
		t.Fatalf("the menu must not be printed without a scope: %q", output.String())
	}
	if stub.admit != 0 {
		t.Fatalf("admitted %d commands, want 0", stub.admit)
	}
}

// TestExecuteInteractiveLineBarePrefixRunsInEndpointScope proves the menu is
// available in endpoint scope, where the selected command carries no target.
func TestExecuteInteractiveLineBarePrefixRunsInEndpointScope(t *testing.T) {
	document := execResultDocument(t, protocol.CommandExecResult{
		Argv:     []string{"ls", "-la"},
		ExitCode: 0,
		Stdout:   "total 0\n",
	})
	stub := shellStub(map[string]any{
		"command_id":        "cmd-1",
		"status":            string(protocol.StatusFinished),
		"delivery_boundary": string(protocol.DeliverySubmitted),
		"effect_certainty":  string(protocol.EffectAcknowledged),
		"provider_response": document,
	})
	state := &interactiveState{}
	state.enterEndpoint(protocol.Endpoint{EndpointID: "endpoint-1", ConnectionState: "online"})
	var output, diagnostics strings.Builder
	options := InteractiveOptions{
		WaitTimeoutMS: 100,
		ShellHistory:  func() []string { return []string{"!ls -la"} },
	}
	if _, err := executeInteractiveLine(context.Background(), stub, state, "!", shellHistoryLine("1"), &output, &output, &diagnostics, options); err != nil {
		t.Fatalf("executeInteractiveLine: %v", err)
	}
	if stub.admit != 1 {
		t.Fatalf("admitted %d commands, want 1", stub.admit)
	}
	if intent := stub.intents[0]; intent.Target != nil {
		t.Fatalf("target = %+v, want no target for an endpoint-scoped command", intent.Target)
	}
}
