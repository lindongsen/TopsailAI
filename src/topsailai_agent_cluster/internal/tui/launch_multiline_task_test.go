package tui

import (
	"context"
	"encoding/json"
	"strings"
	"testing"
)

// launchMultiLineTaskInput drives the wizard through the endpoint choice, the
// project choice and then a multi-line task block.
const launchMultiLineTaskInput = "1\n\nfirst line\n  indented line\nEOF\n"

// runLaunchMultiLineTask executes one wizard run and returns both streams.
func runLaunchMultiLineTask(t *testing.T, input string, options InteractiveOptions) (string, string, *launchStub) {
	t.Helper()
	stub := &launchStub{interactiveStub: startupStub()}
	lines, done, stop := startInputReader(strings.NewReader(input), 8192)
	defer func() { stop(); done.Wait() }()
	var out, trusted strings.Builder
	if err := projectLaunch(context.Background(), stub, stub, &interactiveState{}, "endpoint-1", lines, &out, &trusted, options); err != nil {
		t.Fatalf("projectLaunch: %v", err)
	}
	return out.String(), trusted.String(), stub
}

// TestLaunchMultiLineTaskEchoesVerbatim proves an empty task answer enters
// multi-line mode and the accepted task is echoed verbatim with colour, so the
// operator can verify exactly what will be sent.
func TestLaunchMultiLineTaskEchoesVerbatim(t *testing.T) {
	out, trusted, stub := runLaunchMultiLineTask(t, launchMultiLineTaskInput, InteractiveOptions{Color: ColorPolicy{Enabled: true}})
	if stub.admit != 1 || len(stub.intents) != 1 {
		t.Fatalf("admit=%d intents=%d", stub.admit, len(stub.intents))
	}
	var payload map[string]string
	if err := json.Unmarshal(stub.intents[0].Payload, &payload); err != nil {
		t.Fatalf("payload=%s error=%v", stub.intents[0].Payload, err)
	}
	if got, want := payload["task"], "first line\n  indented line"; got != want {
		t.Fatalf("task=%q want=%q", got, want)
	}
	if strings.Contains(payload["task"], MultiLineTerminator) {
		t.Fatalf("terminator leaked into the task: %q", payload["task"])
	}
	if !strings.Contains(out, MultiLineTaskHint) {
		t.Fatalf("multi-line hint missing from output: %q", out)
	}
	// The echo carries the header and every body line, each styled, and it
	// preserves the body's own indentation.
	if !strings.Contains(trusted, ansiBoldCyan+TaskEchoHeader+ansiReset) {
		t.Fatalf("echo header missing or unstyled: %q", trusted)
	}
	for _, line := range []string{"first line", "  indented line"} {
		if !strings.Contains(trusted, ansiGreen+line+ansiReset) {
			t.Fatalf("echo line %q missing or unstyled: %q", line, trusted)
		}
	}
}

// TestLaunchMultiLineTaskEchoIsPlainWithoutColor proves the echo is byte
// identical plain text when colour is disabled, so a piped run stays clean.
func TestLaunchMultiLineTaskEchoIsPlainWithoutColor(t *testing.T) {
	_, trusted, stub := runLaunchMultiLineTask(t, launchMultiLineTaskInput, InteractiveOptions{})
	if stub.admit != 1 {
		t.Fatalf("admit=%d", stub.admit)
	}
	if strings.Contains(trusted, "\x1b[") {
		t.Fatalf("plain echo carries ANSI styling: %q", trusted)
	}
	if got, want := trusted, TaskEchoHeader+"\nfirst line\n  indented line\n"; got != want {
		t.Fatalf("echo=%q want=%q", got, want)
	}
}

// TestLaunchMultiLineTaskEndsAtEndOfInput proves Ctrl+D finishes the block
// without a terminator line and still echoes the accepted task.
func TestLaunchMultiLineTaskEndsAtEndOfInput(t *testing.T) {
	_, trusted, stub := runLaunchMultiLineTask(t, "1\n\nonly line\n", InteractiveOptions{})
	if stub.admit != 1 || len(stub.intents) != 1 {
		t.Fatalf("admit=%d intents=%d", stub.admit, len(stub.intents))
	}
	var payload map[string]string
	if err := json.Unmarshal(stub.intents[0].Payload, &payload); err != nil {
		t.Fatalf("payload=%s error=%v", stub.intents[0].Payload, err)
	}
	if got, want := payload["task"], "only line"; got != want {
		t.Fatalf("task=%q want=%q", got, want)
	}
	if !strings.Contains(trusted, TaskEchoHeader+"\nonly line\n") {
		t.Fatalf("echo=%q", trusted)
	}
}

// TestLaunchMultiLineTaskRejectsEmptyBlock proves an immediately terminated
// block is an explicit error and admits no command.
func TestLaunchMultiLineTaskRejectsEmptyBlock(t *testing.T) {
	stub := &launchStub{interactiveStub: startupStub()}
	lines, done, stop := startInputReader(strings.NewReader("1\n\nEOF\n"), 8192)
	defer func() { stop(); done.Wait() }()
	var out, trusted strings.Builder
	err := projectLaunch(context.Background(), stub, stub, &interactiveState{}, "endpoint-1", lines, &out, &trusted, InteractiveOptions{})
	if err == nil || err.Error() != "task must not be empty; enter a task or cancel" {
		t.Fatalf("error=%v", err)
	}
	if stub.admit != 0 || len(stub.intents) != 0 {
		t.Fatalf("admit=%d intents=%d", stub.admit, len(stub.intents))
	}
	if strings.Contains(trusted.String(), TaskEchoHeader) {
		t.Fatalf("rejected task was echoed: %q", trusted.String())
	}
}

// TestLaunchMultiLineTaskRejectsOversizedBlock proves the task payload bound is
// enforced while reading, so an oversized task never reaches admission.
func TestLaunchMultiLineTaskRejectsOversizedBlock(t *testing.T) {
	stub := &launchStub{interactiveStub: startupStub()}
	// Each line stays under the per-line bound, so the block bound is what
	// rejects the task.
	input := "1\n\n" + strings.Repeat(strings.Repeat("x", 4000)+"\n", 3) + "EOF\n"
	lines, done, stop := startInputReader(strings.NewReader(input), 8192)
	defer func() { stop(); done.Wait() }()
	var out, trusted strings.Builder
	err := projectLaunch(context.Background(), stub, stub, &interactiveState{}, "endpoint-1", lines, &out, &trusted, InteractiveOptions{})
	if err == nil || !strings.Contains(err.Error(), "task exceeds the maximum length") {
		t.Fatalf("error=%v", err)
	}
	if stub.admit != 0 || len(stub.intents) != 0 {
		t.Fatalf("admit=%d intents=%d", stub.admit, len(stub.intents))
	}
}

// TestLaunchSingleLineTaskIsNotEchoed proves the single-line answer keeps its
// previous behaviour: nothing was typed in multi-line mode, so nothing is echoed.
func TestLaunchSingleLineTaskIsNotEchoed(t *testing.T) {
	_, trusted, stub := runLaunchMultiLineTask(t, "1\ndo work\n", InteractiveOptions{})
	if stub.admit != 1 {
		t.Fatalf("admit=%d", stub.admit)
	}
	if strings.Contains(trusted, TaskEchoHeader) {
		t.Fatalf("single-line task was echoed: %q", trusted)
	}
}

// TestLaunchMultiLineTaskSanitizesEcho proves operator-supplied escape
// sequences never reach the terminal, while the payload keeps the raw text.
func TestLaunchMultiLineTaskSanitizesEcho(t *testing.T) {
	_, trusted, stub := runLaunchMultiLineTask(t, "1\n\nsafe \x1b[31mred\nEOF\n", InteractiveOptions{Color: ColorPolicy{Enabled: true}})
	if stub.admit != 1 {
		t.Fatalf("admit=%d", stub.admit)
	}
	if strings.Contains(trusted, "\x1b[31m") {
		t.Fatalf("echo leaked an operator escape sequence: %q", trusted)
	}
	var payload map[string]string
	if err := json.Unmarshal(stub.intents[0].Payload, &payload); err != nil {
		t.Fatalf("payload=%s error=%v", stub.intents[0].Payload, err)
	}
	if !strings.Contains(payload["task"], "safe ") {
		t.Fatalf("payload lost the task text: %q", payload["task"])
	}
}
