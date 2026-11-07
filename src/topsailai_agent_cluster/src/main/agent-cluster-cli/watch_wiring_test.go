package main

import (
	"testing"

	"topsailai_agent_cluster/internal/tui"
)

// TestWireEditorReadersProvidesBothSeams proves the shipped wiring supplies the
// tick-capable reader. Without this, watch is rejected in the real binary while
// every unit test still passes, because those tests inject WatchReader directly.
func TestWireEditorReadersProvidesBothSeams(t *testing.T) {
	editor := tui.NewTerminalEditor(nil, nil, func() int { return 80 }, func() (func() error, error) {
		return func() error { return nil }, nil
	})
	options := wireEditorReaders(tui.InteractiveOptions{}, editor)
	if options.ReadLine == nil {
		t.Fatal("wiring did not provide the plain line reader")
	}
	if options.WatchReader == nil {
		t.Fatal("wiring did not provide the tick-capable reader, so watch is unreachable in the shipped binary")
	}
}

// TestWireEditorReadersKeepsPlainReaderWithoutEditor proves a missing editor does
// not fabricate a reader, so watch refuses explicitly instead of degrading.
func TestWireEditorReadersKeepsPlainReaderWithoutEditor(t *testing.T) {
	options := wireEditorReaders(tui.InteractiveOptions{}, nil)
	if options.ReadLine != nil || options.WatchReader != nil {
		t.Fatalf("wiring invented a reader without an editor: %#v", options)
	}
}
