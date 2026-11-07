package main

import (
	"strings"
	"testing"

	"topsailai_agent_cluster/internal/tui"
)

// standaloneCommandName extracts the command word from one advertised help line.
// Flags and placeholders are skipped so a syntax that places flags before the
// command still yields the command word.
func standaloneCommandName(line string) string {
	// The rendered help block indents every line, so the leading indent must be
	// removed before the program name can be stripped. Without this the first
	// field is the program name itself and every line looks like an unknown
	// command.
	rest := strings.TrimPrefix(strings.TrimSpace(line), "agent-cluster-cli ")
	rest = strings.TrimPrefix(rest, "[options] ")
	for _, field := range strings.Fields(rest) {
		if strings.HasPrefix(field, "-") || strings.HasPrefix(field, "[") || strings.HasPrefix(field, "<") {
			continue
		}
		return field
	}
	return ""
}

// TestEveryAdvertisedStandaloneCommandIsDispatched enforces the non-interactive
// first rule structurally: a command may only be advertised if the standalone
// dispatch switch accepts it. Printing a syntax that the CLI rejects as unknown
// would make the help a promise the binary cannot keep.
func TestEveryAdvertisedStandaloneCommandIsDispatched(t *testing.T) {
	lines := tui.NonInteractiveCommandHelpLines()
	if len(lines) == 0 {
		t.Fatal("no standalone commands advertised")
	}
	for _, line := range lines {
		name := standaloneCommandName(line)
		if name == "" {
			t.Fatalf("cannot derive a command name from %q", line)
		}
		var output, diagnostics strings.Builder
		// An unreachable Server keeps the check offline: any transport error is
		// acceptable, but an unknown-command rejection is not.
		args := []string{"--server-url", "http://127.0.0.1:1", "--token", "test-token", name}
		err := runWithIO(args, strings.NewReader(""), &output, &diagnostics, false, nil)
		if err != nil && strings.Contains(err.Error(), "unknown command") {
			t.Fatalf("advertised command %q is not dispatched: %v", name, err)
		}
	}
}

// TestRemovedStandaloneSpellingsStayRejected proves a removed command is not
// silently reinterpreted as a different action.
func TestRemovedStandaloneSpellingsStayRejected(t *testing.T) {
	for _, name := range []string{"table", "use"} {
		var output, diagnostics strings.Builder
		args := []string{"--server-url", "http://127.0.0.1:1", "--token", "test-token", name}
		err := runWithIO(args, strings.NewReader(""), &output, &diagnostics, false, nil)
		if err == nil {
			t.Fatalf("removed command %q was accepted", name)
		}
		if !strings.Contains(err.Error(), "removed") && !strings.Contains(err.Error(), "unknown command") {
			t.Fatalf("removed command %q gave an unexpected error: %v", name, err)
		}
	}
}
