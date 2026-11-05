package tui

import (
	"strings"
	"testing"
)

// TestSessionHelpAccuracy pins context-specific constraints without executing actions.
func TestSessionHelpAccuracy(t *testing.T) {
	var out strings.Builder
	if err := PrintScopedCommandHelp(&out, "", ScopeSession); err != nil {
		t.Fatal(err)
	}
	for _, want := range []string{"status [command-id]", "last submitted command, otherwise current session state", "after confirmation", "explicit endpoint must match", "Bare cd or cd / returns to workspace", "adapter capability support", "internal resource IDs"} {
		if !strings.Contains(out.String(), want) {
			t.Fatalf("missing %q in %q", want, out.String())
		}
	}
	out.Reset()
	if err := PrintScopedCommandHelp(&out, "status", ScopeSession); err != nil {
		t.Fatal(err)
	}
	if !strings.Contains(out.String(), "last submitted command takes precedence") {
		t.Fatal(out.String())
	}
	out.Reset()
	if err := PrintNonInteractiveCommandHelp(&out, "status"); err != nil {
		t.Fatal(err)
	}
	if !strings.Contains(out.String(), "status <command-id>") || strings.Contains(out.String(), "current session state") {
		t.Fatal(out.String())
	}
}
