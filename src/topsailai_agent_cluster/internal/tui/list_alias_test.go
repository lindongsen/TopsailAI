package tui

import (
	"context"
	"strings"
	"testing"

	"topsailai_agent_cluster/internal/protocol"
)

// TestListAliasRendersSameTable proves "l" dispatches the list command, so the
// operator sees the same table as the canonical spelling.
func TestListAliasRendersSameTable(t *testing.T) {
	cases := []struct {
		name, input string
		tables      int
	}{
		{"workspace", "l\nexit\n", 2},
		{"endpoint", "cd ai-dev/endpoint-1\nl\nexit\n", 3},
		{"session", "cd ai-dev/endpoint-1/res-1\nl\nexit\n", 2},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			var out, diagnostics strings.Builder
			err := RunInteractive(context.Background(), singleHostStub(), strings.NewReader(c.input), &out, &diagnostics, InteractiveOptions{})
			if err != nil || diagnostics.Len() != 0 {
				t.Fatalf("err=%v diagnostics=%q", err, diagnostics.String())
			}
			if got := strings.Count(out.String(), "SESSION_STATUS"); got != c.tables {
				t.Fatalf("table count=%d want=%d output=%q", got, c.tables, out.String())
			}
		})
	}
}

// TestListAliasMatchesCanonicalHelp proves the alias resolves to the canonical
// help text, so the alias never advertises a different contract.
func TestListAliasMatchesCanonicalHelp(t *testing.T) {
	var aliasHelp, canonicalHelp strings.Builder
	if err := PrintScopedCommandHelp(&aliasHelp, "l", ScopeWorkspace); err != nil {
		t.Fatal(err)
	}
	if err := PrintScopedCommandHelp(&canonicalHelp, "list", ScopeWorkspace); err != nil {
		t.Fatal(err)
	}
	if aliasHelp.String() != canonicalHelp.String() {
		t.Fatalf("alias help differs from canonical help: alias=%q canonical=%q", aliasHelp.String(), canonicalHelp.String())
	}
}

// TestListAliasKeepsListArguments proves the alias forwards its arguments to the
// same parser, so "l --clean" is not silently treated as a bare list.
func TestListAliasKeepsListArguments(t *testing.T) {
	var out, diagnostics strings.Builder
	err := RunInteractive(context.Background(), singleHostStub(), strings.NewReader("l --clean\nexit\n"), &out, &diagnostics, InteractiveOptions{})
	if err != nil || diagnostics.Len() != 0 {
		t.Fatalf("err=%v diagnostics=%q", err, diagnostics.String())
	}
	if strings.Contains(out.String(), "state") {
		t.Fatalf("--clean did not reach the list parser: %q", out.String())
	}
}

// TestListAliasRejectsUnknownArguments proves the alias inherits the canonical
// argument validation instead of accepting anything.
func TestListAliasRejectsUnknownArguments(t *testing.T) {
	var out, diagnostics strings.Builder
	err := RunInteractive(context.Background(), singleHostStub(), strings.NewReader("l --bogus\nexit\n"), &out, &diagnostics, InteractiveOptions{})
	if err != nil {
		t.Fatalf("RunInteractive: %v", err)
	}
	if !strings.Contains(diagnostics.String(), "usage:") {
		t.Fatalf("diagnostics=%q", diagnostics.String())
	}
}

// TestListAliasIsDocumented proves the alias appears in the interactive alias
// registry and in help all, so the spelling is discoverable.
func TestListAliasIsDocumented(t *testing.T) {
	if got := commandAliases["l"]; got != "list" {
		t.Fatalf("commandAliases[l]=%q want list", got)
	}
	var all strings.Builder
	if err := PrintScopedCommandHelp(&all, "all", ScopeWorkspace); err != nil {
		t.Fatal(err)
	}
	if !strings.Contains(all.String(), "l=list") {
		t.Fatalf("help all missing l=list: %q", all.String())
	}
}

// TestListAliasStaysOffStandaloneSurface proves the standalone CLI does not
// advertise or accept the interactive-only spelling.
func TestListAliasStaysOffStandaloneSurface(t *testing.T) {
	var overview strings.Builder
	if err := PrintNonInteractiveCommandHelp(&overview, ""); err != nil {
		t.Fatal(err)
	}
	if strings.Contains(overview.String(), " l ") {
		t.Fatalf("standalone overview advertises l: %q", overview.String())
	}
	if err := PrintNonInteractiveCommandHelp(&overview, "l"); err == nil {
		t.Fatal("standalone help accepted l")
	}
}

// TestListAliasDoesNotShadowLogs proves "l" resolves to list and "logs" keeps its
// own meaning, so the shorter spelling cannot capture the longer command.
func TestListAliasDoesNotShadowLogs(t *testing.T) {
	if got := canonicalCommandName("logs"); got != "logs" {
		t.Fatalf("canonicalCommandName(logs)=%q want logs", got)
	}
	if got := canonicalCommandName("l"); got != "list" {
		t.Fatalf("canonicalCommandName(l)=%q want list", got)
	}
	stub := &interactiveStub{endpoints: []protocol.Endpoint{{EndpointID: "endpoint-1"}}, reports: map[string]protocol.InventoryReport{"endpoint-1": testInventory()}}
	_, diagnostics := runScope(t, stub, "cd endpoint-1/session-1\nl\nexit\n", ColorPolicy{})
	if diagnostics != "" {
		t.Fatalf("diagnostics=%q", diagnostics)
	}
}
