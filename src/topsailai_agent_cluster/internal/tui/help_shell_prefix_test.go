package tui

import (
	"strings"
	"testing"
)

// TestContextHelpDocumentsBareShellPrefix proves both scopes that can run the
// prefix form advertise the bare-prefix menu.
//
// The menu is a form of the prefix rather than a command word, so it has no entry
// in the command table and no syntax line. The workflow text is therefore the only
// place an operator can discover it, and a scope that can run the form but does
// not mention the menu leaves the feature undiscoverable.
func TestContextHelpDocumentsBareShellPrefix(t *testing.T) {
	for _, kind := range []ScopeKind{ScopeSession, ScopeEndpoint} {
		var out strings.Builder
		if err := printContextHelp(&out, kind); err != nil {
			t.Fatalf("printContextHelp(%s): %v", kind, err)
		}
		rendered := out.String()
		if !strings.Contains(rendered, "A bare ! prints the ten most recent ! commands") {
			t.Fatalf("%s help does not document the bare prefix menu: %q", kind, rendered)
		}
		if !strings.Contains(rendered, "leave the answer empty to cancel") {
			t.Fatalf("%s help does not document cancellation: %q", kind, rendered)
		}
	}
}

// TestContextHelpOmitsBareShellPrefixInWorkspaceScope proves workspace scope does
// not advertise a form it refuses.
//
// Advertising it would send the operator to a command that fails, and the failure
// would describe a missing scope rather than a missing feature.
func TestContextHelpOmitsBareShellPrefixInWorkspaceScope(t *testing.T) {
	var out strings.Builder
	if err := printContextHelp(&out, ScopeWorkspace); err != nil {
		t.Fatalf("printContextHelp(workspace): %v", err)
	}
	if strings.Contains(out.String(), "A bare ! prints") {
		t.Fatalf("workspace help advertises a form it refuses: %q", out.String())
	}
}
