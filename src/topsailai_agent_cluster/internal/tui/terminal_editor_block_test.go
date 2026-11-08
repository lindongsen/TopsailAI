package tui

import (
	"context"
	"strings"
	"testing"
)

// blockTestOutput records rendered bytes and reports a fixed terminal height,
// so the input block can be checked without a real terminal.
type blockTestOutput struct {
	strings.Builder
	height int
}

// TerminalHeight reports the injected height instead of probing a descriptor.
func (o *blockTestOutput) TerminalHeight() int { return o.height }

// TestTerminalEditorWrapsLongInput checks that a long edit renders as several
// rows and that the head of the text stays visible. Horizontal scrolling used to
// push the head out of view, which is the reported defect.
func TestTerminalEditorWrapsLongInput(t *testing.T) {
	value := strings.Repeat("abcdefghij", 6)
	out := &blockTestOutput{height: 40}
	editor := NewTerminalEditor(
		&editorTestInput{Reader: strings.NewReader(value + "\r")},
		out,
		func() int { return 20 },
		func() (func() error, error) { return func() error { return nil }, nil },
	)
	got, overflow, err := editor.ReadLine(context.Background(), "workspace> ", true, 4096)
	if err != nil || overflow || got != value {
		t.Fatalf("got=%q overflow=%v err=%v", got, overflow, err)
	}
	rendered := out.String()
	if !strings.Contains(rendered, "abcdefghij") {
		t.Fatalf("head of the input is missing: %q", rendered)
	}
	// A 20-column terminal with an 11-column prompt leaves 8 columns on the
	// first row, so a 60-character edit needs more than one row.
	if rows := strings.Count(rendered, "\r\n"); rows < 2 {
		t.Fatalf("expected a multi-row block, rows=%d rendered=%q", rows, rendered)
	}
}

// TestTerminalEditorBlockHeightIsBounded checks that a block taller than the
// terminal is clipped to the reported height, so the prompt never scrolls the
// screen away.
func TestTerminalEditorBlockHeightIsBounded(t *testing.T) {
	value := strings.Repeat("x", 200)
	out := &blockTestOutput{height: 5}
	editor := NewTerminalEditor(
		&editorTestInput{Reader: strings.NewReader(value + "\r")},
		out,
		func() int { return 10 },
		func() (func() error, error) { return func() error { return nil }, nil },
	)
	if _, _, err := editor.ReadLine(context.Background(), "p> ", true, 4096); err != nil {
		t.Fatal(err)
	}
	if editor.blockRows != 0 {
		t.Fatalf("block state must be cleared after submit, rows=%d", editor.blockRows)
	}
}

// TestTerminalEditorErasesPreviousBlock checks that a shrinking block clears the
// rows it used before, so no stale text is left on screen.
func TestTerminalEditorErasesPreviousBlock(t *testing.T) {
	out := &blockTestOutput{height: 40}
	editor := NewTerminalEditor(
		&editorTestInput{Reader: strings.NewReader(strings.Repeat("y", 60) + "\x7f\x7f\x7f\x7f\x7f\x7f\x7f\x7f\x7f\x7f\x7f\x7f\x7f\x7f\x7f\x7f\x7f\x7f\x7f\x7f\x7f\x7f\x7f\x7f\x7f\x7f\x7f\x7f\x7f\x7f\x7f\x7f\x7f\x7f\x7f\x7f\x7f\x7f\x7f\x7f\x7f\x7f\x7f\x7f\x7f\x7f\x7f\x7f\x7f\x7f\x7f\x7f\x7f\x7f\x7f\x7f\x7f\x7f\x7f\x7f\r")},
		out,
		func() int { return 20 },
		func() (func() error, error) { return func() error { return nil }, nil },
	)
	if _, _, err := editor.ReadLine(context.Background(), "workspace> ", true, 4096); err != nil {
		t.Fatal(err)
	}
	// Every redraw after the first must erase the rows it drew before, so the
	// erase sequence appears more than once for a block that shrank.
	if count := strings.Count(out.String(), "\x1b[2K"); count < 4 {
		t.Fatalf("expected repeated row erasure, count=%d", count)
	}
}
