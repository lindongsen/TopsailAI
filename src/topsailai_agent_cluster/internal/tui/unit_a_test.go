package tui

import (
	"context"
	"fmt"
	"sort"
	"strings"
	"testing"
)

func TestUnitAContextHelpAndHelpAll(t *testing.T) {
	var workspace, all strings.Builder
	if err := PrintScopedCommandHelp(&workspace, "", ScopeWorkspace); err != nil {
		t.Fatal(err)
	}
	if strings.Contains(workspace.String(), "inject <text>") || strings.Contains(workspace.String(), "interrupt [soft|hard]") {
		t.Fatalf("workspace help exposed session commands: %q", workspace.String())
	}
	if !strings.Contains(workspace.String(), "Start example:") || !strings.Contains(workspace.String(), "Run help all") {
		t.Fatalf("context guidance missing: %q", workspace.String())
	}
	if err := PrintScopedCommandHelp(&all, "all", ScopeWorkspace); err != nil {
		t.Fatal(err)
	}
	for _, name := range []string{"inject <text>", "interrupt [soft|hard] [message]", "Aliases: ", ">=send", "?=help", "l=list", "btw=inject", "control=interrupt", "r=refresh", "q=quit"} {
		if !strings.Contains(all.String(), name) {
			t.Fatalf("help all missing %q: %q", name, all.String())
		}
	}
}
func TestUnitAHelpAliasesAndErrorShape(t *testing.T) {
	stub := inputStub()
	var output, diagnostics strings.Builder
	input := "r\nhelp all\nbad\nq\n"
	if err := RunInteractive(context.Background(), stub, strings.NewReader(input), &output, &diagnostics, InteractiveOptions{}); err != nil {
		t.Fatal(err)
	}
	if stub.inventoryCalls < 2 {
		t.Fatalf("r did not refresh inventory: %d calls", stub.inventoryCalls)
	}
	if !strings.Contains(output.String(), "All commands:") {
		t.Fatalf("help all was not rendered: %q", output.String())
	}
	lines := strings.Split(strings.TrimSuffix(diagnostics.String(), "\n"), "\n")
	if len(lines) != 3 || !strings.HasPrefix(lines[0], "error:") || !strings.HasPrefix(lines[1], "usage:") || !strings.HasPrefix(lines[2], "next:") {
		t.Fatalf("error is not three-line actionable format: %q", diagnostics.String())
	}
}

func TestUnitAPrimaryHelpHidesCompatibilityAliases(t *testing.T) {
	var output strings.Builder
	if err := PrintScopedCommandHelp(&output, "", ScopeSession); err != nil {
		t.Fatal(err)
	}
	if strings.Contains(output.String(), "btw") || strings.Contains(output.String(), "control") {
		t.Fatalf("primary session help exposed compatibility aliases: %q", output.String())
	}
	if err := PrintScopedCommandHelp(&output, "all", ScopeSession); err != nil {
		t.Fatal(err)
	}
	for _, name := range []string{"inject <text>", "interrupt [soft|hard] [message]"} {
		if !strings.Contains(output.String(), name) {
			t.Fatalf("canonical command missing from help all: %q", name)
		}
	}
}

func TestUnitAStartupGuide(t *testing.T) {
	output, diagnostics := runStartup(t, startupStub(), "quit\n", InteractiveOptions{})
	if diagnostics != "" {
		t.Fatalf("unexpected diagnostics: %q", diagnostics)
	}
	if !strings.Contains(output, "list: view sessions | <n> or cd <n>: select | start: launch agent | help: commands | q: quit") {
		t.Fatalf("startup guide missing: %q", output)
	}
}

func TestUnitACommandMetadataIsConsistent(t *testing.T) {
	matrixNames := make(map[string]bool, len(commandScopeMatrix))
	for _, rule := range commandScopeMatrix {
		if matrixNames[rule.Name] {
			t.Fatalf("duplicate command %q in scope matrix", rule.Name)
		}
		matrixNames[rule.Name] = true
		if _, ok := commandHelpCatalog[rule.Name]; !ok {
			t.Fatalf("registered command %q has no help descriptor", rule.Name)
		}
	}
	if len(matrixNames) != len(commandHelpCatalog) {
		t.Fatalf("canonical command/help descriptor count mismatch: matrix=%d help=%d", len(matrixNames), len(commandHelpCatalog))
	}
	for name := range commandHelpCatalog {
		if !matrixNames[name] {
			t.Fatalf("help descriptor %q is not a registered canonical command", name)
		}
	}
	for alias, canonical := range commandAliases {
		if !matrixNames[canonical] {
			t.Fatalf("alias %q targets unregistered command %q", alias, canonical)
		}
		for _, scope := range scopeHelpOrder {
			if commandAllowed(alias, scope) != commandAllowed(canonical, scope) {
				t.Fatalf("alias %q scope behavior differs from %q in %s", alias, canonical, scope)
			}
		}
		var aliasHelp, canonicalHelp strings.Builder
		if err := PrintScopedCommandHelp(&aliasHelp, alias, ScopeWorkspace); err != nil {
			t.Fatalf("help %q: %v", alias, err)
		}
		if err := PrintScopedCommandHelp(&canonicalHelp, canonical, ScopeWorkspace); err != nil {
			t.Fatalf("help %q: %v", canonical, err)
		}
		if aliasHelp.String() != canonicalHelp.String() {
			t.Fatalf("alias %q help differs from canonical %q", alias, canonical)
		}
	}
	for _, scope := range scopeHelpOrder {
		got := availableCommands(scope)
		for _, name := range got {
			if _, ok := commandHelpCatalog[name]; !ok {
				t.Fatalf("%s scope lists command %q without help", scope, name)
			}
		}
	}
	var all strings.Builder
	if err := PrintScopedCommandHelp(&all, "all", ScopeWorkspace); err != nil {
		t.Fatal(err)
	}
	lines := strings.Split(strings.TrimSuffix(all.String(), "\n"), "\n")
	var actualCommands, actualAliases []string
	inAliases := false
	for _, line := range lines {
		if strings.HasPrefix(line, "Aliases: ") {
			inAliases = true
			actualAliases = strings.Split(strings.TrimPrefix(line, "Aliases: "), ", ")
			continue
		}
		if !inAliases && strings.HasPrefix(line, "  ") {
			actualCommands = append(actualCommands, strings.TrimSpace(line))
		}
	}
	var expectedCommands []string
	for _, name := range commandHelpOrder {
		entry := commandHelpCatalog[name]
		expectedCommands = append(expectedCommands, entry.syntax+"   scopes: "+strings.Join(commandScopes(name), ", ")+"   "+entry.description)
	}
	sort.Strings(actualCommands)
	sort.Strings(expectedCommands)
	if len(actualCommands) != len(uniqueStrings(actualCommands)) || !equalStrings(actualCommands, expectedCommands) {
		t.Fatalf("help all command rows=%v, want exact unique set=%v", actualCommands, expectedCommands)
	}
	var expectedAliases []string
	for alias, canonical := range commandAliases {
		expectedAliases = append(expectedAliases, alias+"="+canonical)
	}
	sort.Strings(actualAliases)
	sort.Strings(expectedAliases)
	if len(actualAliases) != len(uniqueStrings(actualAliases)) || !equalStrings(actualAliases, expectedAliases) {
		t.Fatalf("help all aliases=%v, want exact unique set=%v", actualAliases, expectedAliases)
	}
}

func uniqueStrings(values []string) []string {
	unique := make(map[string]struct{}, len(values))
	for _, value := range values {
		unique[value] = struct{}{}
	}
	result := make([]string, 0, len(unique))
	for value := range unique {
		result = append(result, value)
	}
	return result
}

func equalStrings(left, right []string) bool {
	if len(left) != len(right) {
		return false
	}
	for index := range left {
		if left[index] != right[index] {
			return false
		}
	}
	return true
}

func TestUnitANonInteractiveAliasHelpRetainsDescriptions(t *testing.T) {
	for _, alias := range []string{"btw", "control"} {
		var detail strings.Builder
		if err := PrintNonInteractiveCommandHelp(&detail, alias); err != nil {
			t.Fatal(err)
		}
		if !strings.Contains(detail.String(), "Description: ") || strings.HasSuffix(strings.TrimSpace(detail.String()), "Description:") {
			t.Fatalf("help %s has empty description: %q", alias, detail.String())
		}
	}
	var overview strings.Builder
	if err := PrintNonInteractiveCommandHelp(&overview, ""); err != nil {
		t.Fatal(err)
	}
	for _, alias := range []string{"btw", "control"} {
		prefix := "agent-cluster-cli [options] " + alias + " <endpoint> <resource> [text] [generation]"
		found := 0
		for _, line := range strings.Split(overview.String(), "\n") {
			if !strings.HasPrefix(line, prefix) {
				continue
			}
			found++
			description := strings.TrimSpace(strings.TrimPrefix(line, prefix))
			if description == "" {
				t.Fatalf("overview %s has empty description: %q", alias, overview.String())
			}
			canonical := commandAliases[alias]
			if want := commandHelpCatalog[canonical].description; description != want {
				t.Fatalf("overview %s description=%q, want %q", alias, description, want)
			}
		}
		if found != 1 {
			t.Fatalf("overview has %d rows for alias %s, want exactly one: %q", found, alias, overview.String())
		}
	}
}

// assertActionableError verifies the new three-line diagnostic contract without
// weakening the original error reason assertion.
func assertActionableError(t *testing.T, got, firstLine string) {
	t.Helper()
	lines := strings.Split(strings.TrimSuffix(got, "\n"), "\n")
	if len(lines) != 3 || lines[0] != firstLine || !strings.HasPrefix(lines[1], "usage: ") || !strings.HasPrefix(lines[2], "next: ") {
		t.Fatalf("diagnostic=%q, want first line %q followed by usage and next", got, firstLine)
	}
}

// assertActionableErrors checks each error reason and its three-line suffix.
func assertActionableErrors(t *testing.T, got string, firstLines ...string) {
	t.Helper()
	lines := strings.Split(strings.TrimSuffix(got, "\n"), "\n")
	if len(lines) != len(firstLines)*3 {
		t.Fatalf("diagnostic=%q, want exactly %d lines", got, len(firstLines)*3)
	}
	for i, first := range firstLines {
		base := i * 3
		if lines[base] != first || !strings.HasPrefix(lines[base+1], "usage: ") || !strings.HasPrefix(lines[base+2], "next: ") {
			t.Fatalf("diagnostic=%q, missing actionable error block %d for %q", got, i+1, first)
		}
	}
}

func TestUnitAHelpDetailsAndUnknownTarget(t *testing.T) {
	var detail strings.Builder
	if err := PrintScopedCommandHelp(&detail, "list", ScopeWorkspace); err != nil {
		t.Fatal(err)
	}
	for _, phrase := range []string{"Syntax: list [endpoint] [--clean]", "Parameters:", "Examples:", "Fields:", "SESSION_ID:"} {
		if !strings.Contains(detail.String(), phrase) {
			t.Fatalf("detailed help missing %q: %q", phrase, detail.String())
		}
	}
	if err := PrintScopedCommandHelp(&detail, "missing", ScopeWorkspace); err == nil || !strings.Contains(err.Error(), "help all") {
		t.Fatalf("unknown help error=%v", err)
	}
}

func TestUnitAHelpAndErrorWriterBranches(t *testing.T) {
	var out strings.Builder
	if err := PrintCommandHelp(&out, "missing"); err == nil {
		t.Fatal("missing help target unexpectedly succeeded")
	}
	if err := PrintNonInteractiveCommandHelp(&out, "interrupt"); err == nil {
		t.Fatal("interactive-only help target unexpectedly succeeded")
	}
	out.Reset()
	if err := writeInteractiveError(&out, "send", fmt.Errorf("usage: send <text>")); err != nil {
		t.Fatal(err)
	}
	assertActionableError(t, out.String(), "error: invalid arguments")
	out.Reset()
	if err := writeInteractiveError(&out, "send", fmt.Errorf("command cmd-1 result unknown; use status cmd-1 to query; timeout")); err != nil {
		t.Fatal(err)
	}
	if !strings.Contains(out.String(), "next: Run status cmd-1 to query the existing command.") {
		t.Fatalf("status recovery guidance missing: %q", out.String())
	}
}

func TestUnitAHelpTargetBranches(t *testing.T) {
	var out strings.Builder
	for _, target := range []string{"scope", "scopes"} {
		out.Reset()
		if err := PrintScopedCommandHelp(&out, target, ScopeWorkspace); err != nil || !strings.Contains(out.String(), "Commands differ by scope") {
			t.Fatalf("scoped target %q: err=%v output=%q", target, err, out.String())
		}
	}
	out.Reset()
	if err := PrintCommandHelp(&out, "scope"); err != nil || !strings.Contains(out.String(), "Commands differ by scope") {
		t.Fatalf("command scope help: err=%v output=%q", err, out.String())
	}
	if err := PrintNonInteractiveCommandHelp(&out, "missing"); err == nil {
		t.Fatal("unknown non-interactive help unexpectedly succeeded")
	}
}

func TestUnitAHelpCatalogRendersEveryPublicTarget(t *testing.T) {
	var out strings.Builder
	for _, name := range commandHelpOrder {
		out.Reset()
		if err := PrintScopedCommandHelp(&out, name, ScopeSession); err != nil {
			t.Fatalf("help %s: %v", name, err)
		}
		if !strings.Contains(out.String(), "Syntax:") {
			t.Fatalf("help %s missing syntax: %q", name, out.String())
		}
	}
	for _, name := range nonInteractiveHelpOrder {
		out.Reset()
		if err := PrintNonInteractiveCommandHelp(&out, name); err != nil {
			t.Fatalf("standalone help %s: %v", name, err)
		}
	}
}

type unitAFailingWriter struct{}

func (unitAFailingWriter) Write([]byte) (int, error) { return 0, fmt.Errorf("unit-a write failure") }

func TestUnitAHelpWriterErrors(t *testing.T) {
	failed := unitAFailingWriter{}
	for _, call := range []func() error{
		func() error { return PrintScopedCommandHelp(failed, "", ScopeWorkspace) },
		func() error { return PrintScopedCommandHelp(failed, "all", ScopeWorkspace) },
		func() error { return PrintCommandHelp(failed, "list") },
		func() error { return PrintNonInteractiveCommandHelp(failed, "list") },
	} {
		if err := call(); err == nil {
			t.Fatal("help writer failure was not returned")
		}
	}
}
