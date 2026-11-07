package tui

import (
	"context"
	"strings"
	"testing"
)

// TestQReturnsToWorkspaceFromEndpointScope proves q leaves endpoint scope and
// re-renders the workspace table instead of exiting the REPL.
func TestQReturnsToWorkspaceFromEndpointScope(t *testing.T) {
	output, diagnostics := runNav(t, singleHostStub(), "cd ai-dev\nq\nquit\n")
	if diagnostics != "" {
		t.Fatalf("unexpected diagnostics: %q", diagnostics)
	}
	if lastPrompt(output) != "workspace>" {
		t.Fatalf("q did not return to workspace scope: prompt=%q output=%q", lastPrompt(output), output)
	}
	// The REPL must still be alive after q, so the following quit is the line
	// that ends the session. Two workspace prompts prove q did not exit.
	if count := strings.Count(output, "workspace> "); count != 2 {
		t.Fatalf("q exited the REPL instead of navigating: workspace prompts=%d output=%q", count, output)
	}
}

// TestQReturnsToWorkspaceFromSessionScope proves q leaves session scope and
// re-renders the workspace table instead of exiting the REPL.
func TestQReturnsToWorkspaceFromSessionScope(t *testing.T) {
	output, diagnostics := runNav(t, singleHostStub(), "cd ai-dev/endpoint-1/res-1\nq\nquit\n")
	if diagnostics != "" {
		t.Fatalf("unexpected diagnostics: %q", diagnostics)
	}
	if lastPrompt(output) != "workspace>" {
		t.Fatalf("q did not return to workspace scope: prompt=%q output=%q", lastPrompt(output), output)
	}
	if count := strings.Count(output, "workspace> "); count != 2 {
		t.Fatalf("q exited the REPL instead of navigating: workspace prompts=%d output=%q", count, output)
	}
}

// TestQInWorkspaceScopeStillQuits proves the workspace-scope meaning of q is
// unchanged, so an operator keeps a one-key exit at the root scope.
func TestQInWorkspaceScopeStillQuits(t *testing.T) {
	output, diagnostics := runNav(t, singleHostStub(), "q\nlist\n")
	if diagnostics != "" {
		t.Fatalf("unexpected diagnostics: %q", diagnostics)
	}
	if count := strings.Count(output, "workspace> "); count != 1 {
		t.Fatalf("q did not exit the REPL in workspace scope: workspace prompts=%d output=%q", count, output)
	}
}

// TestPrefixedQReturnsToWorkspace proves the optional command prefix never
// changes the scope-aware meaning of q.
func TestPrefixedQReturnsToWorkspace(t *testing.T) {
	output, diagnostics := runNav(t, singleHostStub(), "cd ai-dev\n/q\nquit\n")
	if diagnostics != "" {
		t.Fatalf("unexpected diagnostics: %q", diagnostics)
	}
	if lastPrompt(output) != "workspace>" {
		t.Fatalf("/q did not return to workspace scope: prompt=%q output=%q", lastPrompt(output), output)
	}
	if count := strings.Count(output, "workspace> "); count != 2 {
		t.Fatalf("/q exited the REPL instead of navigating: workspace prompts=%d output=%q", count, output)
	}
}

// TestQuitAndExitStillLeaveEveryScope proves the unambiguous exit spellings are
// unaffected, so the scope-aware q never traps an operator in a scope. The prompt
// count is the discriminator: a trailing list would render a second prompt, so an
// exit spelling that silently failed to leave the REPL cannot pass this test.
func TestQuitAndExitStillLeaveEveryScope(t *testing.T) {
	for _, tc := range []struct {
		name   string
		input  string
		prompt string
	}{
		{"quit-from-endpoint", "cd ai-dev\nquit\nlist\n", "endpoint[ai-dev/endpoint-1]> "},
		{"quit-from-session", "cd ai-dev/endpoint-1/res-1\nquit\nlist\n", "session[ai-dev/provider-res-1]> "},
		{"exit-from-endpoint", "cd ai-dev\nexit\nlist\n", "endpoint[ai-dev/endpoint-1]> "},
		{"exit-from-session", "cd ai-dev/endpoint-1/res-1\nexit\nlist\n", "session[ai-dev/provider-res-1]> "},
	} {
		t.Run(tc.name, func(t *testing.T) {
			output, diagnostics := runNav(t, singleHostStub(), tc.input)
			if diagnostics != "" {
				t.Fatalf("unexpected diagnostics: %q", diagnostics)
			}
			if count := strings.Count(output, tc.prompt); count != 1 {
				t.Fatalf("%s rendered %d %q prompts, want 1: the trailing list ran, so the exit spelling did not leave the REPL: output=%q", tc.name, count, tc.prompt, output)
			}
		})
	}
}

// TestQWithArgumentIsRejected proves a surplus argument is a usage error rather
// than a silent navigation, so q can never be read as a navigation target.
func TestQWithArgumentIsRejected(t *testing.T) {
	output, diagnostics := runNav(t, singleHostStub(), "cd ai-dev\nq ai-dev\nquit\n")
	if !strings.Contains(diagnostics, "usage: q") {
		t.Fatalf("q with an argument was not rejected: diagnostics=%q", diagnostics)
	}
	if lastPrompt(output) != "endpoint[ai-dev/endpoint-1]>" {
		t.Fatalf("rejected q changed the scope: prompt=%q", lastPrompt(output))
	}
}

// TestQClearsPinnedSessionSelection proves returning to workspace scope drops
// the pinned session, so a later session-scoped command cannot act on a session
// the operator has already left.
func TestQClearsPinnedSessionSelection(t *testing.T) {
	stub := singleHostStub()
	state := interactiveState{}
	var output, diagnostics strings.Builder
	for _, line := range []string{"cd ai-dev/endpoint-1/res-1", "q"} {
		quit, err := executeInteractiveLine(context.Background(), stub, &state, line, nil, &output, &output, &diagnostics, InteractiveOptions{})
		if quit || err != nil {
			t.Fatalf("line %q: quit=%t err=%v diagnostics=%q", line, quit, err, diagnostics.String())
		}
	}
	if state.Scope.Kind != ScopeWorkspace {
		t.Fatalf("scope=%v, want workspace", state.Scope.Kind)
	}
	if state.Scope.SessionID != "" || state.Scope.EndpointID != "" {
		t.Fatalf("q kept stale scope identity: %+v", state.Scope)
	}
	if state.interactiveSelection.EndpointID != "" || state.interactiveSelection.SessionID != "" {
		t.Fatalf("q kept the pinned selection: %+v", state.interactiveSelection)
	}
}

// TestQReturnsToWorkspacePredicate pins the dispatch rule itself, so a future
// alias change cannot silently make q quit from every scope again.
func TestQReturnsToWorkspacePredicate(t *testing.T) {
	for _, tc := range []struct {
		name string
		kind ScopeKind
		want bool
	}{
		{"workspace", ScopeWorkspace, false},
		{"endpoint", ScopeEndpoint, true},
		{"session", ScopeSession, true},
	} {
		if got := qReturnsToWorkspace("q", tc.kind); got != tc.want {
			t.Fatalf("%s scope: qReturnsToWorkspace=%t, want %t", tc.name, got, tc.want)
		}
	}
	for _, spelling := range []string{"quit", "exit", "/q", "Q", ""} {
		if qReturnsToWorkspace(spelling, ScopeEndpoint) {
			t.Fatalf("spelling %q must not navigate back", spelling)
		}
	}
}

// TestScopedHelpDescribesScopeAwareQ proves the help surface never advertises q
// as an unconditional quit outside workspace scope.
func TestScopedHelpDescribesScopeAwareQ(t *testing.T) {
	for _, kind := range []ScopeKind{ScopeEndpoint, ScopeSession} {
		var out strings.Builder
		if err := PrintScopedCommandHelp(&out, "quit", kind); err != nil {
			t.Fatalf("%s quit help: %v", kind, err)
		}
		if !strings.Contains(out.String(), "the q spelling returns to workspace scope") {
			t.Fatalf("%s quit help does not describe the scope-aware q: %q", kind, out.String())
		}
	}
	var workspace strings.Builder
	if err := PrintScopedCommandHelp(&workspace, "quit", ScopeWorkspace); err != nil {
		t.Fatalf("workspace quit help: %v", err)
	}
	if strings.Contains(workspace.String(), "returns to workspace scope") {
		t.Fatalf("workspace quit help must not describe navigation: %q", workspace.String())
	}
	var scopeModel strings.Builder
	if err := PrintScopedCommandHelp(&scopeModel, "scope", ScopeWorkspace); err != nil {
		t.Fatalf("scope help: %v", err)
	}
	if !strings.Contains(scopeModel.String(), "q                     return to workspace scope") {
		t.Fatalf("scope model help does not list q navigation: %q", scopeModel.String())
	}
}
