package main

import (
	"os"
	"strings"
	"testing"

	"topsailai_agent_cluster/internal/tui"
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

// TestResolveOutputColorFollowsStdoutNotStdin proves the colour decision belongs to
// the output stream. A redirected stdout must stay plain even when stdin is an
// interactive terminal, because escape sequences are written to stdout and a pipe
// or file cannot render them. Before this seam existed, `list` emitted 58 SGR
// sequences into a non-TTY stdout whenever stdin was a terminal.
func TestResolveOutputColorFollowsStdoutNotStdin(t *testing.T) {
	var out strings.Builder
	if got := resolveOutputColor(&out, false); got.Enabled {
		t.Fatalf("redirected stdout enabled colour: %+v", got)
	}
}

// TestResolveOutputColorHonoursNoColorFlag proves --no-color still wins on a real
// terminal, so the boundary decision never overrides the explicit operator flag.
func TestResolveOutputColorHonoursNoColorFlag(t *testing.T) {
	var out strings.Builder
	if got := resolveOutputColor(&out, true); got.Enabled {
		t.Fatalf("--no-color enabled colour: %+v", got)
	}
}

// TestTerminalOutputReportsItsColorPolicy proves the boundary exposes the policy it
// was resolved with, so a renderer reached through a generic writer honours it
// instead of probing global terminal state.
func TestTerminalOutputReportsItsColorPolicy(t *testing.T) {
	enabled := tui.ColorPolicy{Enabled: true}
	out := terminalOutput{Writer: &strings.Builder{}, color: enabled}
	if got := out.ColorPolicy(); got != enabled {
		t.Fatalf("boundary policy=%+v want %+v", got, enabled)
	}
	if got := tui.OutputColorPolicy(out); got != enabled {
		t.Fatalf("OutputColorPolicy=%+v want %+v", got, enabled)
	}
}

// TestListKeepsStdoutPlainWhenStdinIsATerminal proves the whole `list` command
// honours the output boundary. It runs the real command against a stub server with
// terminal=true (a TTY stdin) and a plain builder (a redirected stdout), which is
// the exact combination that used to leak escape sequences into a pipe.
func TestListKeepsStdoutPlainWhenStdinIsATerminal(t *testing.T) {
	server := newListBehaviorServer(t)
	defer server.Close()
	var output, diagnostics strings.Builder
	err := runWithIO([]string{"--server-url", server.URL, "--token", "test-token", "--endpoint", "endpoint-1", "list"}, strings.NewReader(""), &output, &diagnostics, true, nil)
	if err != nil {
		t.Fatalf("list failed: %v diagnostics=%q", err, diagnostics.String())
	}
	if strings.Contains(output.String(), "\x1b[") {
		t.Fatalf("redirected stdout received escape sequences: %q", output.String())
	}
	if !strings.Contains(output.String(), "SESSION_STATUS") {
		t.Fatalf("plain list dropped the state column: %q", output.String())
	}
}
