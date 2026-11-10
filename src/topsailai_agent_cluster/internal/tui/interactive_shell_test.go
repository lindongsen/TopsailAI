package tui

import (
	"context"
	"encoding/json"
	"strings"
	"testing"

	"topsailai_agent_cluster/internal/protocol"
)

// shellStubAPI advertises command.exec with its real payload version and returns
// a terminal receipt carrying a command.exec result document, so the interactive
// path can be exercised without a live Endpoint.
type shellStubAPI struct {
	interactiveStub
	command map[string]any
}

func (s *shellStubAPI) GetCapabilities(context.Context, string) (protocol.CapabilityDescriptor, error) {
	return protocol.CapabilityDescriptor{
		Revision: "rev-1",
		Capabilities: []protocol.Capability{
			{Name: protocol.OperationCommandExec, Version: protocol.CommandExecPayloadVersion},
		},
	}, nil
}

func (s *shellStubAPI) GetCommand(context.Context, string) (map[string]any, error) {
	return s.command, nil
}

// shellStub returns a stub whose selected session is already pinned, so a shell
// line reaches the command path without a preceding navigation command.
func shellStub(command map[string]any) *shellStubAPI {
	stub := &shellStubAPI{command: command}
	stub.endpoints = []protocol.Endpoint{{EndpointID: "endpoint-1"}}
	stub.reports = map[string]protocol.InventoryReport{"endpoint-1": testInventory()}
	return stub
}

// shellState pins the selection that a shell line targets.
func shellState() *interactiveState {
	state := &interactiveState{}
	state.interactiveSelection = interactiveSelection{
		EndpointID:         "endpoint-1",
		ClusterSessionID:   "session-1",
		ProviderGeneration: "generation-1",
	}
	return state
}

// execResultDocument encodes one command.exec result as the provider response.
func execResultDocument(t *testing.T, result protocol.CommandExecResult) string {
	t.Helper()
	encoded, err := json.Marshal(result)
	if err != nil {
		t.Fatalf("marshal result: %v", err)
	}
	return string(encoded)
}

// TestIsShellLine proves the prefix form is recognised only as a leading prefix.
func TestIsShellLine(t *testing.T) {
	cases := []struct {
		line string
		want bool
	}{
		{line: "!ls", want: true},
		{line: "  !ls -la", want: true},
		{line: "!", want: true},
		{line: "ls", want: false},
		{line: "list", want: false},
		{line: "send !important", want: false},
		{line: "", want: false},
	}
	for _, testCase := range cases {
		if got := isShellLine(testCase.line); got != testCase.want {
			t.Fatalf("isShellLine(%q) = %t, want %t", testCase.line, got, testCase.want)
		}
	}
}

// TestTokenizeCommandLine proves the tokenizer produces an argv array and never
// interprets shell syntax. Every token stays literal, because the Endpoint must
// not receive a command string it would have to parse.
func TestTokenizeCommandLine(t *testing.T) {
	cases := []struct {
		name string
		text string
		want []string
	}{
		{name: "single token", text: "ls", want: []string{"ls"}},
		{name: "several tokens", text: "git status --short", want: []string{"git", "status", "--short"}},
		{name: "collapsed spaces", text: "  ls   -la  ", want: []string{"ls", "-la"}},
		{name: "double quoted space", text: `echo "hello world"`, want: []string{"echo", "hello world"}},
		{name: "single quoted space", text: `echo 'hello world'`, want: []string{"echo", "hello world"}},
		{name: "quoted empty token", text: `echo ""`, want: []string{"echo", ""}},
		{name: "no variable expansion", text: `echo $HOME`, want: []string{"echo", "$HOME"}},
		{name: "no globbing", text: `ls *.go`, want: []string{"ls", "*.go"}},
		{name: "no redirection", text: `echo hi > out.txt`, want: []string{"echo", "hi", ">", "out.txt"}},
		{name: "no pipeline", text: `ls | wc -l`, want: []string{"ls", "|", "wc", "-l"}},
		{name: "no substitution", text: `echo $(id)`, want: []string{"echo", "$(id)"}},
		{name: "no command chaining", text: `ls; rm -rf x`, want: []string{"ls;", "rm", "-rf", "x"}},
	}
	for _, testCase := range cases {
		t.Run(testCase.name, func(t *testing.T) {
			argv, err := tokenizeCommandLine(testCase.text)
			if err != nil {
				t.Fatalf("tokenizeCommandLine(%q) error: %v", testCase.text, err)
			}
			if len(argv) != len(testCase.want) {
				t.Fatalf("argv = %q, want %q", argv, testCase.want)
			}
			for index := range argv {
				if argv[index] != testCase.want[index] {
					t.Fatalf("argv = %q, want %q", argv, testCase.want)
				}
			}
		})
	}
}

// TestTokenizeCommandLineRejects proves malformed input fails instead of being
// guessed at, so a truncated quote never silently changes the argument list.
func TestTokenizeCommandLineRejects(t *testing.T) {
	cases := []struct {
		name    string
		text    string
		wantErr string
	}{
		{name: "unterminated double quote", text: `echo "hello`, wantErr: "unterminated quote"},
		{name: "unterminated single quote", text: `echo 'hello`, wantErr: "unterminated quote"},
		{name: "empty", text: "", wantErr: shellUsage},
		{name: "whitespace only", text: "   ", wantErr: shellUsage},
	}
	for _, testCase := range cases {
		t.Run(testCase.name, func(t *testing.T) {
			argv, err := tokenizeCommandLine(testCase.text)
			if err == nil {
				t.Fatalf("tokenizeCommandLine(%q) = %q, want error", testCase.text, argv)
			}
			if !strings.Contains(err.Error(), testCase.wantErr) {
				t.Fatalf("error = %q, want it to contain %q", err.Error(), testCase.wantErr)
			}
		})
	}
}

// TestShellArgvStripsPrefix proves the program name never carries the prefix,
// because the Endpoint resolves the program from argv[0].
func TestShellArgvStripsPrefix(t *testing.T) {
	argv, err := shellArgv("!git status --short")
	if err != nil {
		t.Fatalf("shellArgv error: %v", err)
	}
	if len(argv) != 3 || argv[0] != "git" || argv[1] != "status" || argv[2] != "--short" {
		t.Fatalf("argv = %q, want [git status --short]", argv)
	}
	if strings.Contains(argv[0], shellPrefix) {
		t.Fatalf("program name %q still carries the prefix", argv[0])
	}
}

// TestShellArgvRejects proves a line without the prefix and a bare prefix are
// both usage errors rather than empty commands.
func TestShellArgvRejects(t *testing.T) {
	for _, line := range []string{"ls", "!", "  !  "} {
		if argv, err := shellArgv(line); err == nil {
			t.Fatalf("shellArgv(%q) = %q, want error", line, argv)
		}
	}
}

// TestCommandExecPayload proves the payload carries the argv array and that an
// invalid array is rejected before admission.
func TestCommandExecPayload(t *testing.T) {
	payload, err := commandExecPayload([]string{"echo", "hello"})
	if err != nil {
		t.Fatalf("commandExecPayload error: %v", err)
	}
	var request protocol.CommandExecRequest
	if err := json.Unmarshal(payload, &request); err != nil {
		t.Fatalf("decode payload: %v", err)
	}
	if len(request.Argv) != 2 || request.Argv[0] != "echo" || request.Argv[1] != "hello" {
		t.Fatalf("argv = %q, want [echo hello]", request.Argv)
	}
	if _, err := commandExecPayload(nil); err == nil {
		t.Fatal("empty argv must be rejected")
	}
	if _, err := commandExecPayload([]string{"echo", "bad\x00token"}); err == nil {
		t.Fatal("control characters must be rejected")
	}
}

// TestExecuteInteractiveLineRunsShellCommand proves a prefixed line reaches
// command.exec instead of being dispatched as a command named "!echo".
//
// This is the regression the interception position protects: commandAllowed
// returns true for an unknown name, so a later interception point would report
// an unknown command and never admit the intent.
func TestExecuteInteractiveLineRunsShellCommand(t *testing.T) {
	document := execResultDocument(t, protocol.CommandExecResult{
		Argv:     []string{"echo", "hello"},
		ExitCode: 0,
		Stdout:   "hello\n",
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
	if _, err := executeInteractiveLine(context.Background(), stub, state, "!echo hello", nil, &output, &output, &diagnostics, InteractiveOptions{WaitTimeoutMS: 100}); err != nil {
		t.Fatalf("executeInteractiveLine: %v", err)
	}
	if stub.admit != 1 {
		t.Fatalf("admitted %d commands, want 1", stub.admit)
	}
	intent := stub.intents[0]
	if intent.Operation != protocol.OperationCommandExec {
		t.Fatalf("operation = %q, want %q", intent.Operation, protocol.OperationCommandExec)
	}
	if intent.OperationVersion != protocol.CommandExecPayloadVersion {
		t.Fatalf("operation version = %q, want %q", intent.OperationVersion, protocol.CommandExecPayloadVersion)
	}
	if intent.Target == nil || intent.Target.ResourceID != "session-1" || intent.Target.ProviderGeneration != "generation-1" {
		t.Fatalf("target = %+v, want session-1/generation-1", intent.Target)
	}
	var request protocol.CommandExecRequest
	if err := json.Unmarshal(intent.Payload, &request); err != nil {
		t.Fatalf("decode intent payload: %v", err)
	}
	if len(request.Argv) != 2 || request.Argv[0] != "echo" || request.Argv[1] != "hello" {
		t.Fatalf("payload argv = %q, want [echo hello]", request.Argv)
	}
	if strings.Contains(diagnostics.String(), "unknown command") {
		t.Fatalf("prefixed line was dispatched as a command: %q", diagnostics.String())
	}
	if !strings.Contains(output.String(), "stdout:\nhello\n") {
		t.Fatalf("output missing the snapshot: %q", output.String())
	}
}

// TestExecuteInteractiveLineShellRequiresSelection proves the prefix form fails
// with the same actionable message as other session-scoped commands.
func TestExecuteInteractiveLineShellRequiresSelection(t *testing.T) {
	stub := shellStub(map[string]any{"status": string(protocol.StatusFinished)})
	state := &interactiveState{}
	var output, diagnostics strings.Builder
	_, err := executeInteractiveLine(context.Background(), stub, state, "!echo hello", nil, &output, &output, &diagnostics, InteractiveOptions{WaitTimeoutMS: 100})
	if err == nil {
		t.Fatal("shell line without a selection must fail")
	}
	if !strings.Contains(err.Error(), "no session selected") {
		t.Fatalf("error = %q, want a selection hint", err.Error())
	}
	if stub.admit != 0 {
		t.Fatalf("admitted %d commands without a selection", stub.admit)
	}
}

// TestRenderCommandExecResultStripsEscapeSequences proves provider output is
// treated as untrusted: a control sequence must not reach the terminal.
func TestRenderCommandExecResultStripsEscapeSequences(t *testing.T) {
	document := execResultDocument(t, protocol.CommandExecResult{
		Argv:     []string{"echo"},
		ExitCode: 0,
		Stdout:   "plain\x1b[31mred\x1b[0m\n",
	})
	var output strings.Builder
	result := map[string]any{
		"command_id":        "cmd-1",
		"status":            string(protocol.StatusFinished),
		"provider_response": document,
	}
	if err := renderCommandExecResult(&output, result, ColorPolicy{}); err != nil {
		t.Fatalf("renderCommandExecResult: %v", err)
	}
	if strings.Contains(output.String(), "\x1b") {
		t.Fatalf("escape sequence reached the terminal: %q", output.String())
	}
	if !strings.Contains(output.String(), "plainred") {
		t.Fatalf("text content was lost: %q", output.String())
	}
}

// TestRenderCommandExecResultRejectedPrintsNoOutput proves a refusal is never
// rendered as an empty successful result.
func TestRenderCommandExecResultRejectedPrintsNoOutput(t *testing.T) {
	var output strings.Builder
	result := map[string]any{
		"command_id":       "cmd-1",
		"status":           string(protocol.StatusRejected),
		"effect_certainty": string(protocol.EffectNotApplied),
		"error_code":       "policy_denied",
	}
	if err := renderCommandExecResult(&output, result, ColorPolicy{}); err != nil {
		t.Fatalf("renderCommandExecResult: %v", err)
	}
	rendered := output.String()
	if !strings.Contains(rendered, "Status: rejected") || !strings.Contains(rendered, "ErrorCode: policy_denied") {
		t.Fatalf("receipt missing: %q", rendered)
	}
	if strings.Contains(rendered, "stdout:") || strings.Contains(rendered, "exit_code:") {
		t.Fatalf("rejected command rendered an output section: %q", rendered)
	}
}

// TestRenderCommandExecResultReportsUnreadableDocument proves an unusable
// provider document is surfaced instead of being silently dropped.
func TestRenderCommandExecResultReportsUnreadableDocument(t *testing.T) {
	var output strings.Builder
	result := map[string]any{
		"command_id":        "cmd-1",
		"status":            string(protocol.StatusFinished),
		"provider_response": "{not json",
	}
	if err := renderCommandExecResult(&output, result, ColorPolicy{}); err != nil {
		t.Fatalf("renderCommandExecResult: %v", err)
	}
	if !strings.Contains(output.String(), "output unavailable") {
		t.Fatalf("unreadable document was dropped: %q", output.String())
	}
}
