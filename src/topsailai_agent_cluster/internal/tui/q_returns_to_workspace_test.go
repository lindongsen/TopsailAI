package tui

import (
	"context"
	"strings"
	"testing"
)

// TestQuitReturnsToWorkspaceFromEndpointScope proves quit leaves endpoint scope
// and re-renders the workspace table instead of exiting the REPL.
func TestQuitReturnsToWorkspaceFromEndpointScope(t *testing.T) {
	output, diagnostics := runNav(t, singleHostStub(), "cd ai-dev\nquit\nexit\n")
	if diagnostics != "" {
		t.Fatalf("unexpected diagnostics: %q", diagnostics)
	}
	if lastPrompt(output) != "workspace>" {
		t.Fatalf("quit did not return to workspace scope: prompt=%q output=%q", lastPrompt(output), output)
	}
	// The REPL must still be alive after quit, so the following exit is the line
	// that ends the session. Two workspace prompts prove quit did not exit.
	if count := strings.Count(output, "workspace> "); count != 2 {
		t.Fatalf("quit exited the REPL instead of navigating: workspace prompts=%d output=%q", count, output)
	}
}

// TestQuitReturnsToWorkspaceFromSessionScope proves quit leaves session scope and
// re-renders the workspace table instead of exiting the REPL.
func TestQuitReturnsToWorkspaceFromSessionScope(t *testing.T) {
	output, diagnostics := runNav(t, singleHostStub(), "cd ai-dev/endpoint-1/res-1\nquit\nexit\n")
	if diagnostics != "" {
		t.Fatalf("unexpected diagnostics: %q", diagnostics)
	}
	if lastPrompt(output) != "workspace>" {
		t.Fatalf("quit did not return to workspace scope: prompt=%q output=%q", lastPrompt(output), output)
	}
	if count := strings.Count(output, "workspace> "); count != 2 {
		t.Fatalf("quit exited the REPL instead of navigating: workspace prompts=%d output=%q", count, output)
	}
}

// TestQAndQuitAreOneBehaviour proves the q alias and its canonical command are
// indistinguishable, so the operator never has to remember two rules. Each
// spelling is driven from endpoint and session scope and must produce the same
// navigation result.
func TestQAndQuitAreOneBehaviour(t *testing.T) {
	for _, spelling := range []string{"q", "quit"} {
		for _, tc := range []struct {
			name  string
			enter string
		}{
			{"from-endpoint", "cd ai-dev\n"},
			{"from-session", "cd ai-dev/endpoint-1/res-1\n"},
		} {
			t.Run(spelling+"-"+tc.name, func(t *testing.T) {
				output, diagnostics := runNav(t, singleHostStub(), tc.enter+spelling+"\nexit\n")
				if diagnostics != "" {
					t.Fatalf("unexpected diagnostics: %q", diagnostics)
				}
				if lastPrompt(output) != "workspace>" {
					t.Fatalf("%q did not return to workspace scope: prompt=%q output=%q", spelling, lastPrompt(output), output)
				}
				if count := strings.Count(output, "workspace> "); count != 2 {
					t.Fatalf("%q exited the REPL instead of navigating: workspace prompts=%d output=%q", spelling, count, output)
				}
			})
		}
	}
}

// TestQuitInWorkspaceScopeStillQuits proves the workspace-scope meaning of quit
// and q is unchanged, so an operator keeps a one-key exit at the root scope.
func TestQuitInWorkspaceScopeStillQuits(t *testing.T) {
	for _, spelling := range []string{"q", "quit"} {
		t.Run(spelling, func(t *testing.T) {
			output, diagnostics := runNav(t, singleHostStub(), spelling+"\nlist\n")
			if diagnostics != "" {
				t.Fatalf("unexpected diagnostics: %q", diagnostics)
			}
			if count := strings.Count(output, "workspace> "); count != 1 {
				t.Fatalf("%q did not exit the REPL in workspace scope: workspace prompts=%d output=%q", spelling, count, output)
			}
		})
	}
}

// TestPrefixedQuitReturnsToWorkspace proves the optional command prefix never
// changes the scope-aware meaning of quit or its q alias.
func TestPrefixedQuitReturnsToWorkspace(t *testing.T) {
	for _, spelling := range []string{"/q", "/quit"} {
		t.Run(spelling, func(t *testing.T) {
			output, diagnostics := runNav(t, singleHostStub(), "cd ai-dev\n"+spelling+"\nexit\n")
			if diagnostics != "" {
				t.Fatalf("unexpected diagnostics: %q", diagnostics)
			}
			if lastPrompt(output) != "workspace>" {
				t.Fatalf("%s did not return to workspace scope: prompt=%q output=%q", spelling, lastPrompt(output), output)
			}
			if count := strings.Count(output, "workspace> "); count != 2 {
				t.Fatalf("%s exited the REPL instead of navigating: workspace prompts=%d output=%q", spelling, count, output)
			}
		})
	}
}

// TestExitAlwaysLeavesEveryScope proves exit is a separate command that always
// leaves the process, so the scope-aware quit never traps an operator in a scope.
// The prompt count is the discriminator: a trailing list would render a second
// prompt, so an exit that silently failed to leave the REPL cannot pass this test.
func TestExitAlwaysLeavesEveryScope(t *testing.T) {
	for _, tc := range []struct {
		name   string
		input  string
		prompt string
	}{
		{"exit-from-workspace", "exit\nlist\n", "workspace> "},
		{"exit-from-endpoint", "cd ai-dev\nexit\nlist\n", "endpoint[ai-dev/endpoint-1]> "},
		{"exit-from-session", "cd ai-dev/endpoint-1/res-1\nexit\nlist\n", "session[ai-dev/provider-res-1]> "},
	} {
		t.Run(tc.name, func(t *testing.T) {
			output, diagnostics := runNav(t, singleHostStub(), tc.input)
			if diagnostics != "" {
				t.Fatalf("unexpected diagnostics: %q", diagnostics)
			}
			if count := strings.Count(output, tc.prompt); count != 1 {
				t.Fatalf("%s rendered %d %q prompts, want 1: the trailing list ran, so exit did not leave the REPL: output=%q", tc.name, count, tc.prompt, output)
			}
		})
	}
}

// TestQuitWithArgumentIsRejected proves a surplus argument is a usage error rather
// than a silent navigation, so quit can never be read as a navigation target.
func TestQuitWithArgumentIsRejected(t *testing.T) {
	for _, spelling := range []string{"q", "quit"} {
		t.Run(spelling, func(t *testing.T) {
			output, diagnostics := runNav(t, singleHostStub(), "cd ai-dev\n"+spelling+" ai-dev\nexit\n")
			if !strings.Contains(diagnostics, "usage: "+spelling) {
				t.Fatalf("%q with an argument was not rejected: diagnostics=%q", spelling, diagnostics)
			}
			if lastPrompt(output) != "endpoint[ai-dev/endpoint-1]>" {
				t.Fatalf("rejected %q changed the scope: prompt=%q", spelling, lastPrompt(output))
			}
		})
	}
}

// TestQuitClearsPinnedSessionSelection proves returning to workspace scope drops
// the pinned session, so a later session-scoped command cannot act on a session
// the operator has already left.
func TestQuitClearsPinnedSessionSelection(t *testing.T) {
	for _, spelling := range []string{"q", "quit"} {
		t.Run(spelling, func(t *testing.T) {
			stub := singleHostStub()
			state := interactiveState{}
			var output, diagnostics strings.Builder
			for _, line := range []string{"cd ai-dev/endpoint-1/res-1", spelling} {
				quit, err := executeInteractiveLine(context.Background(), stub, &state, line, nil, &output, &output, &diagnostics, InteractiveOptions{})
				if quit || err != nil {
					t.Fatalf("line %q: quit=%t err=%v diagnostics=%q", line, quit, err, diagnostics.String())
				}
			}
			if state.Scope.Kind != ScopeWorkspace {
				t.Fatalf("scope=%v, want workspace", state.Scope.Kind)
			}
			if state.Scope.ClusterSessionID != "" || state.Scope.EndpointID != "" {
				t.Fatalf("%q kept stale scope identity: %+v", spelling, state.Scope)
			}
			if state.interactiveSelection.EndpointID != "" || state.interactiveSelection.ClusterSessionID != "" {
				t.Fatalf("%q kept the pinned selection: %+v", spelling, state.interactiveSelection)
			}
		})
	}
}

// TestQuitReturnsToWorkspacePredicate pins the dispatch rule itself. It keys on
// the canonical command, so the q alias cannot drift into a second rule, and exit
// must never navigate.
func TestQuitReturnsToWorkspacePredicate(t *testing.T) {
	for _, tc := range []struct {
		name string
		kind ScopeKind
		want bool
	}{
		{"workspace", ScopeWorkspace, false},
		{"endpoint", ScopeEndpoint, true},
		{"session", ScopeSession, true},
	} {
		if got := quitReturnsToWorkspace("quit", tc.kind); got != tc.want {
			t.Fatalf("%s scope: quitReturnsToWorkspace=%t, want %t", tc.name, got, tc.want)
		}
	}
	for _, spelling := range []string{"exit", "list", "help", ""} {
		if quitReturnsToWorkspace(spelling, ScopeEndpoint) {
			t.Fatalf("canonical command %q must not navigate back", spelling)
		}
	}
	// The alias must resolve to the canonical command, so q and quit share one rule.
	if canonicalCommandName("q") != "quit" {
		t.Fatalf("q no longer resolves to quit: %q", canonicalCommandName("q"))
	}
	if canonicalCommandName("exit") == "quit" {
		t.Fatalf("exit must not be an alias of quit, or it would inherit navigation")
	}
}

// TestScopedHelpDescribesScopeAwareQuit proves the help surface never advertises
// quit or q as an unconditional exit outside workspace scope, and that exit is
// documented as the unconditional way out.
func TestScopedHelpDescribesScopeAwareQuit(t *testing.T) {
	for _, kind := range []ScopeKind{ScopeEndpoint, ScopeSession} {
		var out strings.Builder
		if err := PrintScopedCommandHelp(&out, "quit", kind); err != nil {
			t.Fatalf("%s quit help: %v", kind, err)
		}
		if !strings.Contains(out.String(), "return to workspace scope") {
			t.Fatalf("%s quit help does not describe the navigation: %q", kind, out.String())
		}
		if !strings.Contains(out.String(), "exit") {
			t.Fatalf("%s quit help does not point at exit: %q", kind, out.String())
		}
		var exitHelp strings.Builder
		if err := PrintScopedCommandHelp(&exitHelp, "exit", kind); err != nil {
			t.Fatalf("%s exit help: %v", kind, err)
		}
		if !strings.Contains(exitHelp.String(), "leave interactive mode from every scope") {
			t.Fatalf("%s exit help does not state the unconditional exit: %q", kind, exitHelp.String())
		}
	}
	var workspace strings.Builder
	if err := PrintScopedCommandHelp(&workspace, "quit", ScopeWorkspace); err != nil {
		t.Fatalf("workspace quit help: %v", err)
	}
	if strings.Contains(workspace.String(), "return to workspace scope") {
		t.Fatalf("workspace quit help must not describe navigation: %q", workspace.String())
	}
	var scopeModel strings.Builder
	if err := PrintScopedCommandHelp(&scopeModel, "scope", ScopeWorkspace); err != nil {
		t.Fatalf("scope help: %v", err)
	}
	if !strings.Contains(scopeModel.String(), "quit, q") {
		t.Fatalf("scope model help does not list quit and q together: %q", scopeModel.String())
	}
	if !strings.Contains(scopeModel.String(), "exit") {
		t.Fatalf("scope model help does not list exit: %q", scopeModel.String())
	}
}
