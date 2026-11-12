package main

import (
	"context"
	"encoding/json"
	"io"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"topsailai_agent_cluster/internal/tui"
)

// historyWiringInput supplies terminal bytes without changing process terminal state.
type historyWiringInput struct {
	io.Reader
}

// SetReadDeadline satisfies the editor's cancellable terminal boundary.
func (input *historyWiringInput) SetReadDeadline(time.Time) error { return nil }

// TestWireEditorHistoryRecordsThroughShippedComposition proves the CLI attaches
// its resolved store to the editor it returns. Store and editor tests cannot
// detect a missing production attachment because they inject the dependency
// directly; this test goes through the same helper as interactiveEditor.
func TestWireEditorHistoryRecordsThroughShippedComposition(t *testing.T) {
	path := filepath.Join(t.TempDir(), "history.jsonl")
	history := tui.NewInputHistory(path, tui.InputHistoryLimits{}, io.Discard)
	input := &historyWiringInput{Reader: strings.NewReader("list --full\r")}
	editor := tui.NewTerminalEditor(input, io.Discard, func() int { return 80 }, func() (func() error, error) {
		return func() error { return nil }, nil
	})

	wired := wireEditorHistory(editor, history)
	line, overflow, err := wired.ReadLine(context.Background(), "workspace> ", true, 64)
	if err != nil || overflow || line != "list --full" {
		t.Fatalf("line=%q overflow=%v err=%v", line, overflow, err)
	}

	content, err := os.ReadFile(path)
	if err != nil {
		t.Fatalf("read history: %v", err)
	}
	var entry tui.InputHistoryEntry
	if err := json.Unmarshal(content, &entry); err != nil {
		t.Fatalf("decode history %q: %v", string(content), err)
	}
	if entry.Kind != tui.InputHistoryKindCommand || entry.Text != "list --full" {
		t.Fatalf("entry=%+v", entry)
	}
}

// TestWireEditorHistoryKeepsMissingEditorUnavailable proves history wiring does
// not fabricate an editor when interactive terminal support is unavailable.
func TestWireEditorHistoryKeepsMissingEditorUnavailable(t *testing.T) {
	if got := wireEditorHistory(nil, tui.NewInputHistory(filepath.Join(t.TempDir(), "history.jsonl"), tui.InputHistoryLimits{}, io.Discard)); got != nil {
		t.Fatalf("editor=%v want nil", got)
	}
}
