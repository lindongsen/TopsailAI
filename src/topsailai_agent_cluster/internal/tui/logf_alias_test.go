package tui

import (
	"strings"
	"testing"
)

// TestLogfAliasArmsFollowStream proves the shorthand reaches the same follow
// path as "logs -f", so the operator gets a stream instead of a snapshot. A
// snapshot would be the dangerous outcome: it looks complete while silently
// missing everything written after it.
func TestLogfAliasArmsFollowStream(t *testing.T) {
	stub := &followStub{interactiveStub: *scopeStub(), blockOpen: true}
	output, diagnostics := runScope(t, stub, "cd host-one/endpoint-1/res-1\nlogf\nquit\n", ColorPolicy{})
	if diagnostics != "" {
		t.Fatalf("unexpected diagnostics: %q", diagnostics)
	}
	if !strings.Contains(output, "log.follow> res-1 (any key stops)") {
		t.Fatalf("follow not armed: %q", output)
	}
	// The armed stream must not add a snapshot read, so the shorthand cannot be
	// silently served by the one-shot path.
	if stub.outputCalls != 1 {
		t.Fatalf("snapshot reads=%d want=1", stub.outputCalls)
	}
}

// TestLogfAliasRewritesTailIntoFollowFlag proves the shorthand prepends the
// follow flag instead of owning a second parser, so every other argument keeps
// the meaning it has under "logs".
func TestLogfAliasRewritesTailIntoFollowFlag(t *testing.T) {
	cases := []struct {
		name     string
		rest     string
		wantRest string
	}{
		{name: "bare", rest: "", wantRest: "-f"},
		{name: "line budget", rest: "-n 7", wantRest: "-f -n 7"},
		{name: "session token", rest: "res_abc", wantRest: "-f res_abc"},
		{name: "row number", rest: "1", wantRest: "-f 1"},
	}
	for _, testCase := range cases {
		t.Run(testCase.name, func(t *testing.T) {
			if got := logsFollowRest(testCase.rest); got != testCase.wantRest {
				t.Fatalf("logsFollowRest(%q)=%q want=%q", testCase.rest, got, testCase.wantRest)
			}
		})
	}
}

// TestLogfAliasInheritsLogsGrammar proves the rewritten tail parses with the
// canonical grammar, so the shorthand cannot drift into a second set of rules.
func TestLogfAliasInheritsLogsGrammar(t *testing.T) {
	cases := []struct {
		name       string
		rest       string
		wantLines  int
		wantFollow bool
		wantTarget string
	}{
		{name: "bare follows with the fallback budget", rest: "", wantLines: 300, wantFollow: true},
		{name: "line budget is forwarded", rest: "-n 7", wantLines: 7, wantFollow: true},
		{name: "session token is forwarded", rest: "res_abc", wantLines: 300, wantFollow: true, wantTarget: "res_abc"},
	}
	for _, testCase := range cases {
		t.Run(testCase.name, func(t *testing.T) {
			target, maxLines, follow, err := parseLogsArgs(logsFollowRest(testCase.rest), 300)
			if err != nil {
				t.Fatalf("parseLogsArgs: %v", err)
			}
			if !follow {
				t.Fatal("follow was not implied by the shorthand")
			}
			if maxLines != testCase.wantLines {
				t.Fatalf("maxLines=%d want=%d", maxLines, testCase.wantLines)
			}
			if target != testCase.wantTarget {
				t.Fatalf("target=%q want=%q", target, testCase.wantTarget)
			}
		})
	}
}

// TestLogfAliasRejectsRepeatedFollowFlag proves a repeated follow flag stays a
// usage error, because the shorthand already states follow and a second flag is a
// contradiction rather than a harmless duplicate.
func TestLogfAliasRejectsRepeatedFollowFlag(t *testing.T) {
	for _, rest := range []string{"-f", "--follow"} {
		t.Run(rest, func(t *testing.T) {
			if _, _, _, err := parseLogsArgs(logsFollowRest(rest), 300); err == nil {
				t.Fatalf("repeated follow flag %q was accepted", rest)
			}
		})
	}
}

// TestLogfAliasRejectsRepeatedFollowFlagInRepl proves the REPL reports the usage
// line and never opens a stream for the contradictory form.
func TestLogfAliasRejectsRepeatedFollowFlagInRepl(t *testing.T) {
	stub := &followStub{interactiveStub: *scopeStub(), blockOpen: true}
	_, diagnostics := runScope(t, stub, "cd host-one/endpoint-1/res-1\nlogf -f\nquit\n", ColorPolicy{})
	if !strings.Contains(diagnostics, "usage: logs") {
		t.Fatalf("diagnostics=%q", diagnostics)
	}
	if stub.startCount() != 0 {
		t.Fatalf("streams opened=%d", stub.startCount())
	}
}

// TestLogfAliasStaysOutOfAliasRegistry proves the shorthand is a form rather than
// an alias entry. Registering it as an alias would make "lo" ambiguous between
// "logs" and "logf", so Tab would stop completing the far more common "logs".
func TestLogfAliasStaysOutOfAliasRegistry(t *testing.T) {
	if _, registered := commandAliases[logsFollowAlias]; registered {
		t.Fatalf("commandAliases registered %q, which makes lo ambiguous", logsFollowAlias)
	}
	if got := canonicalCommandName(logsFollowAlias); got != logsFollowAlias {
		t.Fatalf("canonicalCommandName(%q)=%q want the unchanged spelling", logsFollowAlias, got)
	}
}

// TestLogfAliasKeepsLogsTabCompletion proves the shorthand does not enter the
// completion list, so "lo" still resolves uniquely to "logs".
func TestLogfAliasKeepsLogsTabCompletion(t *testing.T) {
	candidates := completableCommands(ScopeEndpoint)
	matches := make([]string, 0, 2)
	for _, candidate := range candidates {
		if strings.HasPrefix(candidate, "lo") {
			matches = append(matches, candidate)
		}
	}
	if len(matches) != 1 || matches[0] != "logs" {
		t.Fatalf("lo candidates=%v want [logs]", matches)
	}
	for _, candidate := range candidates {
		if candidate == logsFollowAlias {
			t.Fatalf("completion list advertises %q", logsFollowAlias)
		}
	}
}

// TestLogfAliasMatchesLogsHelp proves help answers the shorthand with the
// canonical body, so the shorthand never advertises a different contract, while
// the heading keeps the spelling the operator typed.
func TestLogfAliasMatchesLogsHelp(t *testing.T) {
	var aliasHelp, canonicalHelp strings.Builder
	if err := PrintScopedCommandHelp(&aliasHelp, logsFollowAlias, ScopeEndpoint); err != nil {
		t.Fatalf("PrintScopedCommandHelp(%q): %v", logsFollowAlias, err)
	}
	if err := PrintScopedCommandHelp(&canonicalHelp, "logs", ScopeEndpoint); err != nil {
		t.Fatalf("PrintScopedCommandHelp(logs): %v", err)
	}
	aliasHeading, aliasBody := splitHelpHeading(aliasHelp.String())
	canonicalHeading, canonicalBody := splitHelpHeading(canonicalHelp.String())
	if aliasHeading != logsFollowAlias {
		t.Fatalf("alias heading=%q want=%q", aliasHeading, logsFollowAlias)
	}
	if canonicalHeading != "logs" {
		t.Fatalf("canonical heading=%q want=logs", canonicalHeading)
	}
	if aliasBody != canonicalBody {
		t.Fatalf("alias help body differs from canonical body: alias=%q canonical=%q", aliasBody, canonicalBody)
	}
}

// TestLogfAliasIsDocumentedInLogsHelp proves the shorthand is discoverable from
// the canonical help, so an operator who never heard of it can still find it.
func TestLogfAliasIsDocumentedInLogsHelp(t *testing.T) {
	var help strings.Builder
	if err := PrintScopedCommandHelp(&help, "logs", ScopeEndpoint); err != nil {
		t.Fatalf("PrintScopedCommandHelp: %v", err)
	}
	if !strings.Contains(help.String(), logsFollowAlias+": shorthand for logs -f") {
		t.Fatalf("logs help does not document %q: %q", logsFollowAlias, help.String())
	}
}

// TestLogfAliasInheritsLogsScope proves the shorthand is unavailable wherever
// "logs" is unavailable, because it is a form of that command rather than a
// command of its own.
func TestLogfAliasInheritsLogsScope(t *testing.T) {
	stub := scopeStub()
	_, diagnostics := runScope(t, stub, logsFollowAlias+"\nquit\n", ColorPolicy{})
	if !strings.Contains(diagnostics, `command "logs" is unavailable in workspace scope`) {
		t.Fatalf("diagnostics=%q", diagnostics)
	}
}
