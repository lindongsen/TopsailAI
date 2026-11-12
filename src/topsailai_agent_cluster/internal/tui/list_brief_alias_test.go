package tui

import (
	"strings"
	"testing"

	"topsailai_agent_cluster/internal/protocol"
)

// TestListBriefAliasRewritesTailIntoBriefFlag proves the shorthand prepends the
// brief flag instead of owning a second parser, so every other argument keeps
// the meaning it has under "list".
func TestListBriefAliasRewritesTailIntoBriefFlag(t *testing.T) {
	cases := []struct {
		name     string
		rest     string
		wantRest string
	}{
		{name: "bare", rest: "", wantRest: "--brief"},
		{name: "clean flag", rest: "--clean", wantRest: "--brief --clean"},
		{name: "endpoint token", rest: "endpoint-1", wantRest: "--brief endpoint-1"},
		{name: "surrounding space", rest: "   ", wantRest: "--brief"},
		{name: "full flag is independent", rest: "--full", wantRest: "--brief --full"},
	}
	for _, testCase := range cases {
		t.Run(testCase.name, func(t *testing.T) {
			if got := listBriefRest(testCase.rest); got != testCase.wantRest {
				t.Fatalf("listBriefRest(%q)=%q want=%q", testCase.rest, got, testCase.wantRest)
			}
		})
	}
}

// TestListBriefAliasInheritsListGrammar proves the rewritten tail parses with
// the canonical grammar, so the shorthand cannot drift into a second set of
// rules.
func TestListBriefAliasInheritsListGrammar(t *testing.T) {
	cases := []struct {
		name       string
		rest       string
		wantFilter string
		wantClean  bool
		wantFull   bool
	}{
		{name: "bare implies brief", rest: ""},
		{name: "clean is forwarded", rest: "--clean", wantClean: true},
		{name: "endpoint is forwarded", rest: "endpoint-1", wantFilter: "endpoint-1"},
		{name: "both are forwarded", rest: "--clean endpoint-1", wantFilter: "endpoint-1", wantClean: true},
		{name: "full combines with brief", rest: "--full", wantFull: true},
	}
	for _, testCase := range cases {
		t.Run(testCase.name, func(t *testing.T) {
			parsed, err := parseListArguments(listBriefRest(testCase.rest))
			if err != nil {
				t.Fatalf("parseListArguments: %v", err)
			}
			if !parsed.Brief {
				t.Fatal("brief was not implied by the shorthand")
			}
			if parsed.Clean != testCase.wantClean {
				t.Fatalf("clean=%v want=%v", parsed.Clean, testCase.wantClean)
			}
			if parsed.Full != testCase.wantFull {
				t.Fatalf("full=%v want=%v", parsed.Full, testCase.wantFull)
			}
			if parsed.Filter != testCase.wantFilter {
				t.Fatalf("filter=%q want=%q", parsed.Filter, testCase.wantFilter)
			}
		})
	}
}

// TestListBriefAliasRejectsRepeatedBriefFlag proves a repeated brief flag stays
// a usage error, because the shorthand already states brief and a second flag is
// a contradiction rather than a harmless duplicate.
func TestListBriefAliasRejectsRepeatedBriefFlag(t *testing.T) {
	if _, err := parseListArguments(listBriefRest("--brief")); err == nil {
		t.Fatal("repeated --brief was accepted")
	}
}

// TestListBriefAliasRejectsRepeatedBriefFlagInRepl proves the REPL reports the
// usage line and never renders a table for the contradictory form.
func TestListBriefAliasRejectsRepeatedBriefFlagInRepl(t *testing.T) {
	stub := scopeStub()
	_, diagnostics := runScope(t, stub, listBriefAlias+" --brief\nquit\n", ColorPolicy{})
	if !strings.Contains(diagnostics, "usage: list") {
		t.Fatalf("diagnostics=%q", diagnostics)
	}
}

// TestListBriefAliasStaysOutOfAliasRegistry proves the shorthand is a form
// rather than an alias entry. Registering it as an alias would resolve the word
// to "list" alone and drop the column set, silently rendering the wide table
// that looks complete while showing every column the operator asked to hide.
func TestListBriefAliasStaysOutOfAliasRegistry(t *testing.T) {
	if _, registered := commandAliases[listBriefAlias]; registered {
		t.Fatalf("commandAliases registered %q, which drops the brief flag", listBriefAlias)
	}
	if got := canonicalCommandName(listBriefAlias); got != listBriefAlias {
		t.Fatalf("canonicalCommandName(%q)=%q want the unchanged spelling", listBriefAlias, got)
	}
}

// TestListBriefAliasKeepsListTabCompletion proves the shorthand does not enter
// the completion list, so "l" still resolves to the advertised spellings only.
func TestListBriefAliasKeepsListTabCompletion(t *testing.T) {
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
		if candidate == listBriefAlias {
			t.Fatalf("completion list advertises %q", listBriefAlias)
		}
	}
}

// TestListBriefAliasMatchesListHelp proves help answers the shorthand with the
// canonical body, so the shorthand never advertises a different contract, while
// the heading keeps the spelling the operator typed.
func TestListBriefAliasMatchesListHelp(t *testing.T) {
	var aliasHelp, canonicalHelp strings.Builder
	if err := PrintScopedCommandHelp(&aliasHelp, listBriefAlias, ScopeEndpoint); err != nil {
		t.Fatalf("PrintScopedCommandHelp(%q): %v", listBriefAlias, err)
	}
	if err := PrintScopedCommandHelp(&canonicalHelp, "list", ScopeEndpoint); err != nil {
		t.Fatalf("PrintScopedCommandHelp(list): %v", err)
	}
	aliasHeading, aliasBody := splitHelpHeading(aliasHelp.String())
	canonicalHeading, canonicalBody := splitHelpHeading(canonicalHelp.String())
	if aliasHeading != listBriefAlias {
		t.Fatalf("alias heading=%q want=%q", aliasHeading, listBriefAlias)
	}
	if canonicalHeading != "list" {
		t.Fatalf("canonical heading=%q want=list", canonicalHeading)
	}
	if aliasBody != canonicalBody {
		t.Fatalf("alias help body differs from canonical body: alias=%q canonical=%q", aliasBody, canonicalBody)
	}
}

// TestListBriefAliasIsDocumentedInListHelp proves the shorthand and the flag are
// discoverable from the canonical help, so an operator who never heard of the
// shorthand can still find it.
func TestListBriefAliasIsDocumentedInListHelp(t *testing.T) {
	var help strings.Builder
	if err := PrintScopedCommandHelp(&help, "list", ScopeEndpoint); err != nil {
		t.Fatalf("PrintScopedCommandHelp: %v", err)
	}
	rendered := help.String()
	if !strings.Contains(rendered, listBriefAlias+": shorthand for list --brief") {
		t.Fatalf("list help does not document %q: %q", listBriefAlias, rendered)
	}
	if !strings.Contains(rendered, "--brief") {
		t.Fatalf("list help does not document --brief: %q", rendered)
	}
}

// TestListBriefAliasIsAdvertisedInStandaloneSyntax pins the standalone syntax
// line, which is a separate hardcoded override rather than the catalog entry.
// The interactive body documented --brief while the standalone Syntax line still
// omitted it, so an operator reading `help list` from the standalone command was
// told the flag did not exist. Asserting the exact line is what keeps the two
// surfaces from disagreeing again.
func TestListBriefAliasIsAdvertisedInStandaloneSyntax(t *testing.T) {
	var help strings.Builder
	if err := PrintNonInteractiveCommandHelp(&help, "list"); err != nil {
		t.Fatalf("PrintNonInteractiveCommandHelp: %v", err)
	}
	rendered := help.String()
	want := "Syntax: agent-cluster-cli [options] [--endpoint <id>] list [--clean] [-a|--all] [--full] [--brief]"
	if !strings.Contains(rendered, want) {
		t.Fatalf("standalone list syntax does not advertise --brief: %q", rendered)
	}
}

// TestListBriefAliasInheritsListScope proves the shorthand is available wherever
// "list" is available, because it is a form of that command rather than a
// command of its own.
func TestListBriefAliasInheritsListScope(t *testing.T) {
	stub := scopeStub()
	_, diagnostics := runScope(t, stub, listBriefAlias+"\nquit\n", ColorPolicy{})
	if strings.Contains(diagnostics, "unavailable in") {
		t.Fatalf("shorthand was rejected in workspace scope: %q", diagnostics)
	}
}

// briefRenderWorkspace is a distinctive workspace path, so a brief table that
// accidentally kept PROJECT_WORKSPACE is detectable by value as well as by
// header. A distinctive value cannot be confused with a default.
const briefRenderWorkspace = "/srv/brief-render-workspace-must-not-be-printed"

// briefRenderStub serves one endpoint whose session carries a distinctive
// workspace path and display name, so both the identifying columns and the
// dropped columns are observable in the rendered bytes.
func briefRenderStub() *interactiveStub {
	report := scopeInventory("res-1", "generation-1")
	report.Sessions[0].ProviderProjectWorkspace = briefRenderWorkspace
	report.Sessions[0].ProviderDisplayName = "brief-render-session"
	return &interactiveStub{
		endpoints: []protocol.Endpoint{{EndpointID: "endpoint-1", Hostname: "host-one"}},
		reports:   map[string]protocol.InventoryReport{"endpoint-1": report},
	}
}

// headerLineOf returns the first rendered line that carries the NO header, so a
// test can assert the printed column set instead of the layout decision that
// produced it.
func headerLineOf(t *testing.T, segment string) string {
	t.Helper()
	for _, line := range strings.Split(segment, "\n") {
		if strings.Contains(line, "NO") && strings.Contains(line, "SESSION_NAME") {
			return line
		}
	}
	t.Fatalf("no header line in segment: %q", segment)
	return ""
}

// TestListBriefShorthandRendersOnlyIdentifyingColumns proves the composed REPL
// path prints exactly NO, SESSION_NAME and ENDPOINT. A rewrite test and an
// option test are both unit tests of one link, and a chain of correct links can
// still have no consumer, so only the rendered bytes prove the flag reaches the
// renderer.
func TestListBriefShorthandRendersOnlyIdentifyingColumns(t *testing.T) {
	output, diagnostics := runScope(t, briefRenderStub(), listBriefAlias+"\nexit\n", ColorPolicy{})
	if strings.Contains(diagnostics, "error") {
		t.Fatalf("diagnostics=%q", diagnostics)
	}
	segment := segmentBeforePrompt(output, "workspace> ")
	header := headerLineOf(t, segment)
	for _, want := range []string{"NO", "SESSION_NAME", "ENDPOINT"} {
		if !strings.Contains(header, want) {
			t.Fatalf("brief header %q is missing %q", header, want)
		}
	}
	for _, unwanted := range []string{"SESSION_STATUS", "SESSION_ID", "DRIVER", "PROJECT_WORKSPACE", "DATA_STATUS"} {
		if strings.Contains(header, unwanted) {
			t.Fatalf("brief header %q still prints %q", header, unwanted)
		}
	}
	if strings.Contains(segment, briefRenderWorkspace) {
		t.Fatalf("brief table printed the workspace value: %q", segment)
	}
	if !strings.Contains(segment, "brief-render-session") {
		t.Fatalf("brief table dropped the session name: %q", segment)
	}
}

// TestListWideRenderKeepsTheDroppedColumns proves the fixture can express the
// failure mode, so the brief test cannot pass for an unrelated reason such as a
// fixture that never had the extra columns.
//
// SESSION_ID is deliberately absent from the expected set: the interactive table
// hides it for every layout, so asserting it here would test the hide rule rather
// than the brief column set.
func TestListWideRenderKeepsTheDroppedColumns(t *testing.T) {
	output, diagnostics := runScope(t, briefRenderStub(), "list\nexit\n", ColorPolicy{})
	if strings.Contains(diagnostics, "error") {
		t.Fatalf("diagnostics=%q", diagnostics)
	}
	segment := segmentBeforePrompt(output, "workspace> ")
	header := headerLineOf(t, segment)
	for _, want := range []string{"SESSION_STATUS", "DRIVER", "PROJECT_WORKSPACE", "DATA_STATUS"} {
		if !strings.Contains(header, want) {
			t.Fatalf("wide header %q is missing %q, so the fixture cannot prove the brief layout dropped it", header, want)
		}
	}
}

// TestListBriefShorthandCombinesWithFull proves brief and full are independent
// axes, so "lb --full" prints the three identifying columns without truncating
// them. The workspace column is dropped, so the untruncated value is proven on
// the session name, which is a wide column.
func TestListBriefShorthandCombinesWithFull(t *testing.T) {
	report := scopeInventory("res-1", "generation-1")
	longName := strings.Repeat("n", 200)
	report.Sessions[0].ProviderDisplayName = longName
	stub := &interactiveStub{
		endpoints: []protocol.Endpoint{{EndpointID: "endpoint-1", Hostname: "host-one"}},
		reports:   map[string]protocol.InventoryReport{"endpoint-1": report},
	}
	output, diagnostics := runScope(t, stub, listBriefAlias+" --full\nexit\n", ColorPolicy{})
	if strings.Contains(diagnostics, "error") {
		t.Fatalf("diagnostics=%q", diagnostics)
	}
	segment := segmentBeforePrompt(output, "workspace> ")
	header := headerLineOf(t, segment)
	if strings.Contains(header, "PROJECT_WORKSPACE") {
		t.Fatalf("brief --full header %q still prints PROJECT_WORKSPACE", header)
	}
	if !strings.Contains(segment, longName) {
		t.Fatalf("brief --full truncated the session name: %q", segment)
	}
}
