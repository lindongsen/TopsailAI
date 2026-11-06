package tui

import (
	"context"
	"io"
	"strings"
	"testing"
)

// TestReadMultiLineBlockTerminators pins both documented terminators and proves
// the terminator line never becomes message content.
func TestReadMultiLineBlockTerminators(t *testing.T) {
	cases := []struct {
		name  string
		input string
		want  string
		lines int
	}{
		{name: "eof line", input: "first\nsecond\nEOF\n", want: "first\nsecond", lines: 2},
		{name: "ctrl d", input: "first\nsecond\n", want: "first\nsecond", lines: 2},
		{name: "single line eof", input: "only\nEOF\n", want: "only", lines: 1},
		{name: "single line ctrl d", input: "only", want: "only", lines: 1},
		{name: "blank lines preserved", input: "a\n\nb\nEOF\n", want: "a\n\nb", lines: 3},
		{name: "carriage returns stripped", input: "a\r\nb\r\nEOF\r\n", want: "a\nb", lines: 2},
		{name: "eof word inside text", input: "the EOF marker\nEOF\n", want: "the EOF marker", lines: 1},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			block, err := ReadMultiLineBlock(strings.NewReader(tc.input), 8192)
			if err != nil {
				t.Fatalf("ReadMultiLineBlock(%q) error=%v", tc.input, err)
			}
			if block.Text != tc.want {
				t.Fatalf("text=%q want=%q", block.Text, tc.want)
			}
			if block.Lines != tc.lines {
				t.Fatalf("lines=%d want=%d", block.Lines, tc.lines)
			}
			if strings.Contains(block.Text, MultiLineTerminator+"\n") || block.Text == MultiLineTerminator {
				t.Fatalf("terminator leaked into payload %q", block.Text)
			}
		})
	}
}

// TestReadMultiLineBlockRejectsEmpty proves an immediately terminated block is
// an explicit error rather than an empty submission.
func TestReadMultiLineBlockRejectsEmpty(t *testing.T) {
	for _, input := range []string{"EOF\n", "", "\n\nEOF\n", "   \nEOF\n"} {
		if _, err := ReadMultiLineBlock(strings.NewReader(input), 8192); err == nil {
			t.Fatalf("input %q accepted an empty block", input)
		}
	}
}

// TestReadMultiLineBlockBounds proves the block body and one physical line are
// both bounded, so an oversized message never reaches admission.
func TestReadMultiLineBlockBounds(t *testing.T) {
	oversizedLine := strings.Repeat("x", 64) + "\nEOF\n"
	if _, err := ReadMultiLineBlock(strings.NewReader(oversizedLine), 16); err == nil {
		t.Fatal("oversized line accepted")
	}
	// The block bound is independent of the per-line bound, so it is exercised
	// through the internal reader with an explicit small block limit.
	lines := []string{"aaaa", "bbbb", "cccc"}
	index := 0
	next := func() (lineReadResult, bool) {
		if index >= len(lines) {
			return lineReadResult{line: MultiLineTerminator}, true
		}
		line := lines[index]
		index++
		return lineReadResult{line: line}, true
	}
	if _, err := readMultiLineBlock(next, 8); err == nil {
		t.Fatal("oversized block accepted")
	}
}

// TestReadMultiLineBlockRequiresStream proves a nil stream fails closed.
func TestReadMultiLineBlockRequiresStream(t *testing.T) {
	if _, err := ReadMultiLineBlock(nil, 8192); err == nil {
		t.Fatal("nil stream accepted")
	}
}

// TestReadInteractiveMultiLineCtrlDEndsBlockOnly proves Ctrl+D finishes the
// block without recording a prompt failure that would end the REPL session.
func TestReadInteractiveMultiLineCtrlDEndsBlockOnly(t *testing.T) {
	source := make(chan lineReadResult, 3)
	source <- lineReadResult{line: "first"}
	source <- lineReadResult{line: "second"}
	source <- lineReadResult{err: io.EOF}
	var out strings.Builder
	block, err := readInteractiveMultiLine(context.Background(), source, &out, InteractiveOptions{LineLimit: 8192})
	if err != nil {
		t.Fatalf("readInteractiveMultiLine error=%v", err)
	}
	if block.Text != "first\nsecond" {
		t.Fatalf("text=%q want %q", block.Text, "first\nsecond")
	}
	if !strings.Contains(out.String(), MultiLineHint) {
		t.Fatalf("hint missing from %q", out.String())
	}
}

// TestReadInteractiveMultiLineTerminatorLine proves the EOF line ends an
// interactive block and is excluded from the payload.
func TestReadInteractiveMultiLineTerminatorLine(t *testing.T) {
	source := make(chan lineReadResult, 2)
	source <- lineReadResult{line: "body"}
	source <- lineReadResult{line: MultiLineTerminator}
	var out strings.Builder
	block, err := readInteractiveMultiLine(context.Background(), source, &out, InteractiveOptions{LineLimit: 8192})
	if err != nil {
		t.Fatalf("readInteractiveMultiLine error=%v", err)
	}
	if block.Text != "body" {
		t.Fatalf("text=%q want %q", block.Text, "body")
	}
}

// TestReadInteractiveMultiLineUnavailable proves a missing input source fails
// closed instead of returning an empty block.
func TestReadInteractiveMultiLineUnavailable(t *testing.T) {
	var out strings.Builder
	if _, err := readInteractiveMultiLine(context.Background(), nil, &out, InteractiveOptions{}); err == nil {
		t.Fatal("missing input source accepted")
	}
}

// TestSendMultiLineBlockReachesAdmission proves a bare send composes a
// multi-line body, terminates on the EOF line, and submits the joined text.
func TestSendMultiLineBlockReachesAdmission(t *testing.T) {
	stub := inputStub()
	input := "cd endpoint-1/session-1\nsend\nfirst line\nsecond line\nEOF\ny\nquit\n"
	output, errorsOut := runInputScenario(t, stub, input, 8192)
	if errorsOut != "" {
		t.Fatalf("unexpected diagnostics=%q", errorsOut)
	}
	if stub.admit != 1 || len(stub.intents) != 1 {
		t.Fatalf("admissions=%d intents=%d want 1", stub.admit, len(stub.intents))
	}
	want := `{"text":"first line\nsecond line"}`
	if got := string(stub.intents[0].Payload); got != want {
		t.Fatalf("payload=%s want=%s", got, want)
	}
	if !strings.Contains(output, MultiLineHint) {
		t.Fatalf("multi-line hint missing from %q", output)
	}
}

// TestSendMultiLineBlockCtrlDEndsBlockOnly proves Ctrl+D finishes the block
// rather than being reported as a multi-line read failure. The stream then has
// no further input, so the confirmation cannot be answered and nothing is
// admitted; the diagnostic must name the confirmation, not the block.
func TestSendMultiLineBlockCtrlDEndsBlockOnly(t *testing.T) {
	stub := inputStub()
	input := "cd endpoint-1/session-1\nsend\nbody line\n"
	output, errorsOut := runInputScenario(t, stub, input, 8192)
	if stub.admit != 0 {
		t.Fatalf("unanswerable confirmation admitted %d commands", stub.admit)
	}
	if !strings.Contains(errorsOut, "confirmation requires a complete line") {
		t.Fatalf("diagnostics=%q want confirmation diagnostic", errorsOut)
	}
	if strings.Contains(errorsOut, "payload must not be empty") {
		t.Fatalf("Ctrl+D was misreported as an empty block: %q", errorsOut)
	}
	if !strings.Contains(output, MultiLineHint) {
		t.Fatalf("multi-line hint missing from %q", output)
	}
}

// TestSendMultiLineBlockDeclinedAdmitsNothing proves the confirmation gate still
// applies to a multi-line body.
func TestSendMultiLineBlockDeclinedAdmitsNothing(t *testing.T) {
	stub := inputStub()
	input := "cd endpoint-1/session-1\nsend\nbody\nEOF\nn\nquit\n"
	output, errorsOut := runInputScenario(t, stub, input, 8192)
	if errorsOut != "" {
		t.Fatalf("unexpected diagnostics=%q", errorsOut)
	}
	if stub.admit != 0 {
		t.Fatalf("declined multi-line send admitted %d commands", stub.admit)
	}
	if !strings.Contains(output, "send cancelled") {
		t.Fatalf("cancellation line missing from %q", output)
	}
}

// TestReadInteractiveMultiLinePromptReaderCtrlD proves the real terminal path:
// Ctrl+D arrives as io.EOF from the injected prompt reader, finishes the block,
// and never records a prompt failure that would end the REPL session.
func TestReadInteractiveMultiLinePromptReaderCtrlD(t *testing.T) {
	lines := []string{"first", "second"}
	index := 0
	read := func(ctx context.Context, prompt string, history bool, limit int) (string, bool, error) {
		if prompt != multiLinePrompt {
			t.Fatalf("prompt=%q want %q", prompt, multiLinePrompt)
		}
		if history {
			t.Fatal("multi-line body must not enter command history")
		}
		if index >= len(lines) {
			return "", false, io.EOF
		}
		line := lines[index]
		index++
		return line, false, nil
	}
	ctx := context.WithValue(context.Background(), promptReaderKey{}, promptReaderConfig{read: read, limit: 8192})
	var out strings.Builder
	block, err := readInteractiveMultiLine(ctx, nil, &out, InteractiveOptions{LineLimit: 8192})
	if err != nil {
		t.Fatalf("readInteractiveMultiLine error=%v", err)
	}
	if block.Text != "first\nsecond" {
		t.Fatalf("text=%q want %q", block.Text, "first\nsecond")
	}
	if !strings.Contains(out.String(), MultiLineHint) {
		t.Fatalf("hint missing from %q", out.String())
	}
}

// TestReadInteractiveMultiLinePromptReaderTerminator proves the EOF line also
// ends a block read through the terminal prompt reader.
func TestReadInteractiveMultiLinePromptReaderTerminator(t *testing.T) {
	lines := []string{"body", MultiLineTerminator}
	index := 0
	read := func(context.Context, string, bool, int) (string, bool, error) {
		if index >= len(lines) {
			return "", false, io.EOF
		}
		line := lines[index]
		index++
		return line, false, nil
	}
	ctx := context.WithValue(context.Background(), promptReaderKey{}, promptReaderConfig{read: read, limit: 8192})
	var out strings.Builder
	block, err := readInteractiveMultiLine(ctx, nil, &out, InteractiveOptions{LineLimit: 8192})
	if err != nil {
		t.Fatalf("readInteractiveMultiLine error=%v", err)
	}
	if block.Text != "body" {
		t.Fatalf("text=%q want %q", block.Text, "body")
	}
}
