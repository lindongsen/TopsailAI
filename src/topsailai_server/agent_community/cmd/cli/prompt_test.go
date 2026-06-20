// Package main provides unit tests for prompt-aware output helpers.
package main

import (
	"bytes"
	"io"
	"os"
	"strings"
	"testing"
)

func captureStdout(t *testing.T, fn func()) string {
	t.Helper()
	old := os.Stdout
	r, w, err := os.Pipe()
	if err != nil {
		t.Fatalf("failed to create pipe: %v", err)
	}
	os.Stdout = w
	defer func() { os.Stdout = old }()

	fn()

	_ = w.Close()
	var buf bytes.Buffer
	if _, err := io.Copy(&buf, r); err != nil {
		t.Fatalf("failed to copy stdout: %v", err)
	}
	return buf.String()
}

func TestPromptPrintln_NoReadline(t *testing.T) {
	// Ensure no global readline state is registered.
	promptState = nil

	out := captureStdout(t, func() {
		promptPrintln("hello", "world")
	})

	if !strings.Contains(out, "hello world") {
		t.Errorf("expected output to contain 'hello world', got %q", out)
	}
}

func TestPromptPrintf_NoReadline(t *testing.T) {
	promptState = nil

	out := captureStdout(t, func() {
		promptPrintf("value=%d name=%s", 42, "acs")
	})

	if out != "value=42 name=acs" {
		t.Errorf("expected 'value=42 name=acs', got %q", out)
	}
}

func TestPromptPrintLines_NoReadline(t *testing.T) {
	promptState = nil

	out := captureStdout(t, func() {
		promptPrintLines("line1", "line2")
	})

	expected := "line1\nline2\n"
	if out != expected {
		t.Errorf("expected %q, got %q", expected, out)
	}
}

func TestSetPromptState(t *testing.T) {
	// Reset global state before and after.
	oldState := promptState
	defer func() { promptState = oldState }()
	promptState = nil

	state := &CLIState{}
	setPromptState(state)

	if promptState != state {
		t.Error("setPromptState did not update promptState")
	}
}

func TestActiveReadline_NilState(t *testing.T) {
	oldState := promptState
	defer func() { promptState = oldState }()
	promptState = nil

	if rl := activeReadline(); rl != nil {
		t.Errorf("activeReadline() = %v, want nil", rl)
	}
}

func TestActiveReadline_NormalReadline(t *testing.T) {
	oldState := promptState
	defer func() { promptState = oldState }()

	state := &CLIState{rl: nil}
	setPromptState(state)

	if rl := activeReadline(); rl != nil {
		t.Errorf("activeReadline() = %v, want nil", rl)
	}
}
