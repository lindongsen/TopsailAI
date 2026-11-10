package tui

import (
	"strings"
	"testing"

	"topsailai_agent_cluster/internal/protocol"
)

// TestListFullAliasRewritesTailIntoFullFlag proves the shorthand prepends the
// full flag instead of owning a second parser, so every other argument keeps the
// meaning it has under "list".
func TestListFullAliasRewritesTailIntoFullFlag(t *testing.T) {
	cases := []struct {
		name     string
		rest     string
		wantRest string
	}{
		{name: "bare", rest: "", wantRest: "--full"},
		{name: "clean flag", rest: "--clean", wantRest: "--full --clean"},
		{name: "endpoint token", rest: "endpoint-1", wantRest: "--full endpoint-1"},
		{name: "surrounding space", rest: "   ", wantRest: "--full"},
	}
	for _, testCase := range cases {
		t.Run(testCase.name, func(t *testing.T) {
			if got := listFullRest(testCase.rest); got != testCase.wantRest {
				t.Fatalf("listFullRest(%q)=%q want=%q", testCase.rest, got, testCase.wantRest)
			}
		})
	}
}

// TestListFullAliasInheritsListGrammar proves the rewritten tail parses with the
// canonical grammar, so the shorthand cannot drift into a second set of rules.
func TestListFullAliasInheritsListGrammar(t *testing.T) {
	cases := []struct {
		name       string
		rest       string
		wantFilter string
		wantClean  bool
		wantFull   bool
	}{
		{name: "bare implies full", rest: "", wantFull: true},
		{name: "clean is forwarded", rest: "--clean", wantClean: true, wantFull: true},
		{name: "endpoint is forwarded", rest: "endpoint-1", wantFilter: "endpoint-1", wantFull: true},
		{name: "both are forwarded", rest: "--clean endpoint-1", wantFilter: "endpoint-1", wantClean: true, wantFull: true},
	}
	for _, testCase := range cases {
		t.Run(testCase.name, func(t *testing.T) {
			parsed, err := parseListArguments(listFullRest(testCase.rest))
			if err != nil {
				t.Fatalf("parseListArguments: %v", err)
			}
			if !parsed.Full {
				t.Fatal("full was not implied by the shorthand")
			}
			if parsed.Clean != testCase.wantClean {
				t.Fatalf("clean=%v want=%v", parsed.Clean, testCase.wantClean)
			}
			if parsed.Filter != testCase.wantFilter {
				t.Fatalf("filter=%q want=%q", parsed.Filter, testCase.wantFilter)
			}
		})
	}
}

// TestListFullAliasRejectsRepeatedFullFlag proves a repeated full flag stays a
// usage error, because the shorthand already states full and a second flag is a
// contradiction rather than a harmless duplicate.
func TestListFullAliasRejectsRepeatedFullFlag(t *testing.T) {
	if _, err := parseListArguments(listFullRest("--full")); err == nil {
		t.Fatal("repeated --full was accepted")
	}
}

// TestListFullAliasRejectsRepeatedFullFlagInRepl proves the REPL reports the
// usage line and never renders a table for the contradictory form.
func TestListFullAliasRejectsRepeatedFullFlagInRepl(t *testing.T) {
	stub := scopeStub()
	_, diagnostics := runScope(t, stub, listFullAlias+" --full\nquit\n", ColorPolicy{})
	if !strings.Contains(diagnostics, "usage: list") {
		t.Fatalf("diagnostics=%q", diagnostics)
	}
}

// TestListFullAliasStaysOutOfAliasRegistry proves the shorthand is a form rather
// than an alias entry. Registering it as an alias would resolve the word to
// "list" alone and drop the flag, silently rendering the truncated table that
// looks complete while hiding the tail of every over-wide value.
func TestListFullAliasStaysOutOfAliasRegistry(t *testing.T) {
	if _, registered := commandAliases[listFullAlias]; registered {
		t.Fatalf("commandAliases registered %q, which drops the full flag", listFullAlias)
	}
	if got := canonicalCommandName(listFullAlias); got != listFullAlias {
		t.Fatalf("canonicalCommandName(%q)=%q want the unchanged spelling", listFullAlias, got)
	}
}

// TestListFullAliasKeepsListTabCompletion proves the shorthand does not enter the
// completion list, so "l" still resolves to the advertised spellings only.
func TestListFullAliasKeepsListTabCompletion(t *testing.T) {
	candidates := completableCommands(ScopeEndpoint)
	matches := make([]string, 0, 3)
	for _, candidate := range candidates {
		if strings.HasPrefix(candidate, "l") {
			matches = append(matches, candidate)
		}
	}
	want := []string{"list", "logs"}
	if len(matches) != len(want) {
		t.Fatalf("l candidates=%v want=%v", matches, want)
	}
	for index, candidate := range matches {
		if candidate != want[index] {
			t.Fatalf("l candidates=%v want=%v", matches, want)
		}
	}
	for _, candidate := range candidates {
		if candidate == listFullAlias {
			t.Fatalf("completion list advertises %q", listFullAlias)
		}
	}
}

// TestListFullAliasMatchesListHelp proves help answers the shorthand with the
// canonical body, so the shorthand never advertises a different contract, while
// the heading keeps the spelling the operator typed.
func TestListFullAliasMatchesListHelp(t *testing.T) {
	var aliasHelp, canonicalHelp strings.Builder
	if err := PrintScopedCommandHelp(&aliasHelp, listFullAlias, ScopeEndpoint); err != nil {
		t.Fatalf("PrintScopedCommandHelp(%q): %v", listFullAlias, err)
	}
	if err := PrintScopedCommandHelp(&canonicalHelp, "list", ScopeEndpoint); err != nil {
		t.Fatalf("PrintScopedCommandHelp(list): %v", err)
	}
	aliasHeading, aliasBody := splitHelpHeading(aliasHelp.String())
	canonicalHeading, canonicalBody := splitHelpHeading(canonicalHelp.String())
	if aliasHeading != listFullAlias {
		t.Fatalf("alias heading=%q want=%q", aliasHeading, listFullAlias)
	}
	if canonicalHeading != "list" {
		t.Fatalf("canonical heading=%q want=list", canonicalHeading)
	}
	if aliasBody != canonicalBody {
		t.Fatalf("alias help body differs from canonical body: alias=%q canonical=%q", aliasBody, canonicalBody)
	}
}

// TestListFullAliasIsDocumentedInListHelp proves the shorthand and the flag are
// discoverable from the canonical help, so an operator who never heard of the
// shorthand can still find it.
func TestListFullAliasIsDocumentedInListHelp(t *testing.T) {
	var help strings.Builder
	if err := PrintScopedCommandHelp(&help, "list", ScopeEndpoint); err != nil {
		t.Fatalf("PrintScopedCommandHelp: %v", err)
	}
	rendered := help.String()
	if !strings.Contains(rendered, listFullAlias+": shorthand for list --full") {
		t.Fatalf("list help does not document %q: %q", listFullAlias, rendered)
	}
	if !strings.Contains(rendered, "--full") {
		t.Fatalf("list help does not document --full: %q", rendered)
	}
}

// TestListFullAliasInheritsListScope proves the shorthand is available wherever
// "list" is available, because it is a form of that command rather than a
// command of its own.
func TestListFullAliasInheritsListScope(t *testing.T) {
	for _, kind := range []ScopeKind{ScopeWorkspace, ScopeEndpoint, ScopeSession} {
		available := availableCommands(kind)
		found := false
		for _, name := range available {
			if name == "list" {
				found = true
				break
			}
		}
		if !found {
			t.Fatalf("list is unavailable in %v scope, so this test cannot prove inheritance", kind)
		}
	}
	stub := scopeStub()
	_, diagnostics := runScope(t, stub, listFullAlias+"\nquit\n", ColorPolicy{})
	if strings.Contains(diagnostics, "unavailable in") {
		t.Fatalf("shorthand was rejected in workspace scope: %q", diagnostics)
	}
}

// TestTableOptionsForOrsFullIntoBoundary proves the per-command request is ORed
// with the boundary value rather than replacing it, so the startup --no-truncate
// option survives a command that did not repeat the request.
func TestTableOptionsForOrsFullIntoBoundary(t *testing.T) {
	cases := []struct {
		name         string
		boundaryFull bool
		commandFull  bool
		wantFull     bool
	}{
		{name: "neither", boundaryFull: false, commandFull: false, wantFull: false},
		{name: "command only", boundaryFull: false, commandFull: true, wantFull: true},
		{name: "boundary only", boundaryFull: true, commandFull: false, wantFull: true},
		{name: "both", boundaryFull: true, commandFull: true, wantFull: true},
	}
	for _, testCase := range cases {
		t.Run(testCase.name, func(t *testing.T) {
			boundary := &fullBoundaryWriter{full: testCase.boundaryFull}
			options := tableOptionsFor(boundary, ColorPolicy{}, listArguments{Full: testCase.commandFull}, nil)
			if options.Full != testCase.wantFull {
				t.Fatalf("Full=%v want=%v", options.Full, testCase.wantFull)
			}
		})
	}
}

// fullBoundaryWriter reports a fixed Full value, so the OR behaviour can be
// observed without depending on how a real terminal is detected.
type fullBoundaryWriter struct {
	full bool
}

// Write discards the rendered bytes; the test only inspects the layout decision.
func (w *fullBoundaryWriter) Write(p []byte) (int, error) {
	return len(p), nil
}

// TableLayout reports the configured Full value and an unbounded width, so the
// test isolates the OR from width detection.
func (w *fullBoundaryWriter) TableLayout() TableLayout {
	return TableLayout{Width: 0, Full: w.full}
}

// longWorkspacePath exceeds workspaceColumnCap, so a bounded render must clip it
// while a full render must keep it. The value is distinctive rather than merely
// long, because a distinctive value cannot be confused with a default.
const longWorkspacePath = "/srv/very-long-project-workspace-name-for-full-render-check"

// fullRenderStub serves one endpoint whose session carries a workspace path
// longer than the column cap, so the rendered bytes prove which layout ran.
func fullRenderStub() *interactiveStub {
	report := scopeInventory("res-1", "generation-1")
	report.Sessions[0].ProviderProjectWorkspace = longWorkspacePath
	return &interactiveStub{
		endpoints: []protocol.Endpoint{{EndpointID: "endpoint-1", Hostname: "host-one"}},
		reports:   map[string]protocol.InventoryReport{"endpoint-1": report},
	}
}

// TestListFullShorthandRendersFullInRepl proves the composed REPL path renders
// the complete value, not only that the tail was rewritten and the option was
// set. A parameter threaded through every layer can still have no consumer, so
// only the rendered bytes prove the flag reaches the renderer.
func TestListFullShorthandRendersFullInRepl(t *testing.T) {
	output, diagnostics := runScope(t, fullRenderStub(), listFullAlias+"\nexit\n", ColorPolicy{})
	if strings.Contains(diagnostics, "error") {
		t.Fatalf("diagnostics=%q", diagnostics)
	}
	if !strings.Contains(output, longWorkspacePath) {
		t.Fatalf("shorthand did not render the complete workspace path: %q", output)
	}
}

// TestListBoundedRenderClipsTheSameValue proves the fixture can express the
// failure mode, so the shorthand test cannot pass for an unrelated reason. The
// startup inventory render is bounded too, so the complete value must be absent
// from the whole stream rather than only from the command segment.
func TestListBoundedRenderClipsTheSameValue(t *testing.T) {
	output, diagnostics := runScope(t, fullRenderStub(), "list\nexit\n", ColorPolicy{})
	if strings.Contains(diagnostics, "error") {
		t.Fatalf("diagnostics=%q", diagnostics)
	}
	if strings.Contains(output, longWorkspacePath) {
		t.Fatalf("bounded list kept the over-cap value: %q", output)
	}
	if !strings.Contains(output, "...") {
		t.Fatalf("bounded list did not clip the value: %q", output)
	}
}
