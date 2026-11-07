package main

import (
	"context"
	"encoding/json"
	"strings"
	"testing"

	"topsailai_agent_cluster/internal/protocol"
	"topsailai_agent_cluster/internal/tui"
)

// startPathStub advertises agent.start so a standalone start can reach the
// payload path, and records the admitted intents.
type startPathStub struct {
	actionPathStub
}

func (s *startPathStub) GetCapabilities(context.Context, string) (protocol.CapabilityDescriptor, error) {
	return protocol.CapabilityDescriptor{Revision: "rev-1", Capabilities: []protocol.Capability{
		{Name: protocol.OperationAgentStart},
	}}, nil
}

// runStartAction executes one standalone start with an explicit colour policy.
func runStartAction(t *testing.T, input string, color tui.ColorPolicy, args ...string) (string, string, *startPathStub, error) {
	t.Helper()
	stub := &startPathStub{}
	var out, diagnostics strings.Builder
	err := action(context.Background(), stub, &out, strings.NewReader(input), &diagnostics, color, args, true, false, 100, "profile-1", "rev-1", "", "", "")
	return out.String(), diagnostics.String(), stub, err
}

// TestStandaloneStartWithoutTaskReadsMultiLineBlock proves a start with no task
// enters multi-line task mode and the terminator never becomes task content.
func TestStandaloneStartWithoutTaskReadsMultiLineBlock(t *testing.T) {
	out, _, stub, err := runStartAction(t, "first line\nsecond line\nEOF\n", tui.ColorPolicy{}, "start", "ep", "session")
	if err != nil {
		t.Fatal(err)
	}
	if len(stub.intents) != 1 {
		t.Fatalf("intent count=%d", len(stub.intents))
	}
	var payload map[string]string
	if err := json.Unmarshal(stub.intents[0].Payload, &payload); err != nil {
		t.Fatalf("payload=%s error=%v", stub.intents[0].Payload, err)
	}
	if got, want := payload["task"], "first line\nsecond line"; got != want {
		t.Fatalf("task=%q want=%q", got, want)
	}
	if strings.Contains(payload["task"], tui.MultiLineTerminator) {
		t.Fatalf("terminator leaked into the task: %q", payload["task"])
	}
	if !strings.Contains(out, tui.TaskEchoHeader) {
		t.Fatalf("accepted task was not echoed: %q", out)
	}
}

// TestStandaloneStartMultiLineEndsAtEndOfInput proves Ctrl+D finishes the task
// block without a terminator line.
func TestStandaloneStartMultiLineEndsAtEndOfInput(t *testing.T) {
	_, _, stub, err := runStartAction(t, "only line\n", tui.ColorPolicy{}, "start", "ep", "session")
	if err != nil {
		t.Fatal(err)
	}
	if len(stub.intents) != 1 {
		t.Fatalf("intent count=%d", len(stub.intents))
	}
	var payload map[string]string
	if err := json.Unmarshal(stub.intents[0].Payload, &payload); err != nil {
		t.Fatalf("payload=%s error=%v", stub.intents[0].Payload, err)
	}
	if got, want := payload["task"], "only line"; got != want {
		t.Fatalf("task=%q want=%q", got, want)
	}
}

// TestStandaloneStartEchoesTaskVerbatimWithColor proves the echo reproduces the
// accepted task exactly, with colour, so the operator can verify it.
func TestStandaloneStartEchoesTaskVerbatimWithColor(t *testing.T) {
	out, _, _, err := runStartAction(t, "first line\n  indented line\nEOF\n", tui.ColorPolicy{Enabled: true}, "start", "ep", "session")
	if err != nil {
		t.Fatal(err)
	}
	if !strings.Contains(out, "\x1b[1;36m"+tui.TaskEchoHeader+"\x1b[0m") {
		t.Fatalf("echo header missing or unstyled: %q", out)
	}
	for _, line := range []string{"first line", "  indented line"} {
		if !strings.Contains(out, "\x1b[32m"+line+"\x1b[0m") {
			t.Fatalf("echo line %q missing or unstyled: %q", line, out)
		}
	}
}

// TestStandaloneStartEchoIsPlainWithoutColor proves the echo is byte identical
// plain text when colour is disabled.
func TestStandaloneStartEchoIsPlainWithoutColor(t *testing.T) {
	out, _, _, err := runStartAction(t, "first line\n  indented line\nEOF\n", tui.ColorPolicy{}, "start", "ep", "session")
	if err != nil {
		t.Fatal(err)
	}
	if strings.Contains(out, "\x1b[") {
		t.Fatalf("plain echo carries ANSI styling: %q", out)
	}
	if !strings.Contains(out, tui.TaskEchoHeader+"\nfirst line\n  indented line\n") {
		t.Fatalf("echo=%q", out)
	}
}

// TestStandaloneStartJSONKeepsEchoOffStdout proves --json output stays
// machine-readable: the echo goes to the diagnostics stream instead.
func TestStandaloneStartJSONKeepsEchoOffStdout(t *testing.T) {
	stub := &startPathStub{}
	var out, diagnostics strings.Builder
	err := action(context.Background(), stub, &out, strings.NewReader("body line\nEOF\n"), &diagnostics, tui.ColorPolicy{Enabled: true}, []string{"start", "ep", "session"}, true, true, 100, "profile-1", "rev-1", "", "", "")
	if err != nil {
		t.Fatal(err)
	}
	if strings.Contains(out.String(), tui.TaskEchoHeader) {
		t.Fatalf("echo corrupted the JSON output stream: %q", out.String())
	}
	if !strings.Contains(diagnostics.String(), tui.TaskEchoHeader) {
		t.Fatalf("echo missing from diagnostics: %q", diagnostics.String())
	}
}

// TestStandaloneStartRejectsEmptyBlock proves an immediately terminated block
// is an explicit error and admits no command.
func TestStandaloneStartRejectsEmptyBlock(t *testing.T) {
	for _, input := range []string{"EOF\n", "", "\n\nEOF\n"} {
		_, _, stub, err := runStartAction(t, input, tui.ColorPolicy{}, "start", "ep", "session")
		if err == nil || err.Error() != "payload must not be empty" {
			t.Fatalf("input=%q error=%v", input, err)
		}
		if len(stub.intents) != 0 {
			t.Fatalf("input=%q admitted %d intents", input, len(stub.intents))
		}
	}
}

// TestStandaloneStartRejectsOversizedBlock proves the task payload bound is
// enforced while reading, so an oversized task never reaches admission.
func TestStandaloneStartRejectsOversizedBlock(t *testing.T) {
	input := strings.Repeat(strings.Repeat("x", 4000)+"\n", 3) + "EOF\n"
	_, _, stub, err := runStartAction(t, input, tui.ColorPolicy{}, "start", "ep", "session")
	if err == nil || !strings.Contains(err.Error(), "task exceeds the maximum length") {
		t.Fatalf("error=%v", err)
	}
	if len(stub.intents) != 0 {
		t.Fatalf("admitted %d intents", len(stub.intents))
	}
}

// TestStandaloneStartTaskFlagWinsOverMultiLine proves --task stays authoritative
// and never consumes the command input stream.
func TestStandaloneStartTaskFlagWinsOverMultiLine(t *testing.T) {
	stub := &startPathStub{}
	var out, diagnostics strings.Builder
	input := &unreadableInput{}
	err := action(context.Background(), stub, &out, input, &diagnostics, tui.ColorPolicy{}, []string{"start", "ep", "session"}, true, false, 100, "profile-1", "rev-1", "", "flag task", "")
	if err != nil {
		t.Fatal(err)
	}
	if input.reads != 0 {
		t.Fatalf("--task read the input stream %d times", input.reads)
	}
	if len(stub.intents) != 1 {
		t.Fatalf("intent count=%d", len(stub.intents))
	}
	var payload map[string]string
	if err := json.Unmarshal(stub.intents[0].Payload, &payload); err != nil {
		t.Fatalf("payload=%s error=%v", stub.intents[0].Payload, err)
	}
	if got, want := payload["task"], "flag task"; got != want {
		t.Fatalf("task=%q want=%q", got, want)
	}
	if strings.Contains(out.String(), tui.TaskEchoHeader) {
		t.Fatalf("--task was echoed: %q", out.String())
	}
}

// TestStandaloneStartPositionalTaskWinsOverMultiLine proves the positional task
// stays authoritative and never consumes the command input stream.
func TestStandaloneStartPositionalTaskWinsOverMultiLine(t *testing.T) {
	stub := &startPathStub{}
	var out, diagnostics strings.Builder
	input := &unreadableInput{}
	err := action(context.Background(), stub, &out, input, &diagnostics, tui.ColorPolicy{}, []string{"start", "ep", "session", "positional task"}, true, false, 100, "profile-1", "rev-1", "", "", "")
	if err != nil {
		t.Fatal(err)
	}
	if input.reads != 0 {
		t.Fatalf("positional task read the input stream %d times", input.reads)
	}
	if len(stub.intents) != 1 {
		t.Fatalf("intent count=%d", len(stub.intents))
	}
	var payload map[string]string
	if err := json.Unmarshal(stub.intents[0].Payload, &payload); err != nil {
		t.Fatalf("payload=%s error=%v", stub.intents[0].Payload, err)
	}
	if got, want := payload["task"], "positional task"; got != want {
		t.Fatalf("task=%q want=%q", got, want)
	}
	if strings.Contains(out.String(), tui.TaskEchoHeader) {
		t.Fatalf("positional task was echoed: %q", out.String())
	}
}

// TestStandaloneStartHintsMultiLineOnTerminal proves a bare start on a terminal
// announces how to finish the task block, so the operator never faces a silent
// wait.
func TestStandaloneStartHintsMultiLineOnTerminal(t *testing.T) {
	var output, diagnostics strings.Builder
	input := strings.NewReader("body line\nEOF\n")
	// The unreachable Server fails the command after the block is read; the hint
	// must already be visible by then.
	_ = runWithIO([]string{"--server-url", "http://127.0.0.1:1", "start", "ep", "res"}, input, &output, &diagnostics, true, nil)
	if !strings.Contains(diagnostics.String(), tui.MultiLineTaskHint) {
		t.Fatalf("diagnostics=%q", diagnostics.String())
	}
}

// TestStandaloneStartWithTaskFlagDoesNotHint proves an explicit --task needs no
// multi-line guidance.
func TestStandaloneStartWithTaskFlagDoesNotHint(t *testing.T) {
	var output, diagnostics strings.Builder
	_ = runWithIO([]string{"--server-url", "http://127.0.0.1:1", "--task", "do work", "start", "ep", "res"}, strings.NewReader(""), &output, &diagnostics, true, nil)
	if strings.Contains(diagnostics.String(), tui.MultiLineTaskHint) {
		t.Fatalf("diagnostics=%q", diagnostics.String())
	}
}

// TestMultiLineHint covers the hint matrix directly, so the guidance stays
// limited to the invocations that actually read a block.
func TestMultiLineHint(t *testing.T) {
	cases := []struct {
		name      string
		operation string
		narg      int
		task      string
		terminal  bool
		want      string
	}{
		{name: "send bare", operation: "send", narg: 3, terminal: true, want: tui.MultiLineHint},
		{name: "send with text", operation: "send", narg: 4, terminal: true},
		{name: "start bare", operation: "start", narg: 3, terminal: true, want: tui.MultiLineTaskHint},
		{name: "start with positional task", operation: "start", narg: 4, terminal: true},
		{name: "start with task flag", operation: "start", narg: 3, task: "do work", terminal: true},
		{name: "start not a terminal", operation: "start", narg: 3, terminal: false},
		{name: "stop", operation: "stop", narg: 4, terminal: true},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			if got := multiLineHint(tc.operation, tc.narg, tc.task, tc.terminal); got != tc.want {
				t.Fatalf("hint=%q want=%q", got, tc.want)
			}
		})
	}
}

// TestTaskEchoWriter covers the stream selection that keeps --json clean.
func TestTaskEchoWriter(t *testing.T) {
	var output, diagnostics strings.Builder
	if got := taskEchoWriter(&output, &diagnostics, false); got != &output {
		t.Fatal("plain mode must echo to the output stream")
	}
	if got := taskEchoWriter(&output, &diagnostics, true); got != &diagnostics {
		t.Fatal("JSON mode must echo to the diagnostics stream")
	}
}

// TestStandaloneStartValidatesProfileBeforeReadingTask proves an incomplete start
// fails before the task block is read, so the operator never types a whole task
// only to have the invocation rejected.
func TestStandaloneStartValidatesProfileBeforeReadingTask(t *testing.T) {
	input := &unreadableInput{}
	var out, diagnostics strings.Builder
	err := action(context.Background(), &startPathStub{}, &out, input, &diagnostics, tui.ColorPolicy{}, []string{"start", "ep", "session"}, true, false, 100, "", "", "", "", "")
	if err == nil {
		t.Fatal("a start without a launch profile must fail")
	}
	if !strings.Contains(err.Error(), "--profile") {
		t.Fatalf("error=%v", err)
	}
	if input.reads != 0 {
		t.Fatalf("the task block was read %d times before the profile check", input.reads)
	}
	if strings.Contains(out.String(), tui.TaskEchoHeader) {
		t.Fatalf("a rejected start must not echo a task: %q", out.String())
	}
}
