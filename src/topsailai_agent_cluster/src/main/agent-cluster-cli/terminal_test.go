package main

import (
	"os"
	"strings"
	"testing"
)

// TestTerminalOutputUnknownWidth preserves in-memory and redirected output.
func TestTerminalOutputUnknownWidth(t *testing.T) {
	var out strings.Builder
	if (terminalOutput{Writer: &out}).TerminalWidth() != 0 {
		t.Fatal("builder has terminal width")
	}
	f, err := os.Open(os.DevNull)
	if err != nil {
		t.Fatal(err)
	}
	defer f.Close()
	if (terminalOutput{Writer: f}).TerminalWidth() != 0 {
		t.Fatal("file has terminal width")
	}
}
