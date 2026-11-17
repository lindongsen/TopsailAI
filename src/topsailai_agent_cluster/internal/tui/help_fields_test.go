package tui

import (
	"strings"
	"testing"
)

// fieldHelpKeys returns the column name each fieldHelp entry documents, taken
// from the text before the first colon.
func fieldHelpKeys() []string {
	keys := make([]string, 0, len(fieldHelp))
	for _, entry := range fieldHelp {
		name, _, found := strings.Cut(entry, ":")
		if !found {
			continue
		}
		keys = append(keys, strings.TrimSpace(name))
	}
	return keys
}

// TestEveryRenderedColumnIsDocumented enforces the rule that every column the
// table can print has a fieldHelp entry. The table and the help text are two
// separate lists, so a column can be added to allColumns and silently stay
// undocumented; this test makes that omission fail instead of shipping. It reads
// allColumns rather than a copy of the header names, so a renamed or added
// column is covered without editing the test.
func TestEveryRenderedColumnIsDocumented(t *testing.T) {
	documented := make(map[string]bool, len(fieldHelp))
	for _, key := range fieldHelpKeys() {
		documented[key] = true
	}
	for _, column := range allColumns {
		if !documented[column.header] {
			t.Errorf("column %q is rendered but has no fieldHelp entry", column.header)
		}
	}
}

// TestFieldHelpHasNoStaleEntry is the other half of the same rule: a fieldHelp
// entry for a column the table no longer prints describes something the operator
// cannot see, so it must be removed with the column.
func TestFieldHelpHasNoStaleEntry(t *testing.T) {
	rendered := make(map[string]bool, len(allColumns))
	for _, column := range allColumns {
		rendered[column.header] = true
	}
	for _, key := range fieldHelpKeys() {
		if !rendered[key] {
			t.Errorf("fieldHelp documents %q, which is not a rendered column", key)
		}
	}
}

// TestMessagesFieldHelpStatesTheFormatAndTheCache proves the MESSAGES entry says
// what the cell contains and how fresh it is. The format is the part an operator
// cannot guess from the header alone: "7/3" is only readable once the order is
// stated, and the dash is only readable once it is distinguished from zero.
func TestMessagesFieldHelpStatesTheFormatAndTheCache(t *testing.T) {
	var entry string
	for _, candidate := range fieldHelp {
		if strings.HasPrefix(candidate, "MESSAGES:") {
			entry = candidate
			break
		}
	}
	if entry == "" {
		t.Fatal("fieldHelp has no MESSAGES entry")
	}
	for _, want := range []string{
		"inbound/outbound",
		"read live from the provider",
		"a dash means the counts were never measured, which is not the same as zero",
		"Inbound is printed first",
		"watch caches a count for 30s",
		"list and refresh read it uncached",
	} {
		if !strings.Contains(entry, want) {
			t.Errorf("MESSAGES field help missing %q: %q", want, entry)
		}
	}
}

// TestEveryTableCommandHelpPrintsTheFields proves the field list is reachable
// from each command that renders the table, not only from list. An operator
// looking at the watch table runs help watch, so a field list that only list
// prints leaves the column they are asking about unexplained.
func TestEveryTableCommandHelpPrintsTheFields(t *testing.T) {
	for _, target := range []string{"list", "refresh", "watch"} {
		var scoped strings.Builder
		if err := PrintScopedCommandHelp(&scoped, target, ScopeWorkspace); err != nil {
			t.Fatalf("PrintScopedCommandHelp(%q): %v", target, err)
		}
		if !strings.Contains(scoped.String(), "Fields:") {
			t.Errorf("interactive help %q has no Fields section: %q", target, scoped.String())
		}
		if !strings.Contains(scoped.String(), "MESSAGES: inbound/outbound") {
			t.Errorf("interactive help %q does not document MESSAGES: %q", target, scoped.String())
		}
	}
}

// TestStandaloneTableCommandHelpPrintsTheFields covers the standalone surface,
// which shares the renderer. Only list and refresh are dispatched there: watch is
// interactive-only because it waits for a keypress to stop, so it has no
// standalone help to check and is covered by the scoped test instead.
func TestStandaloneTableCommandHelpPrintsTheFields(t *testing.T) {
	for _, target := range []string{"list", "refresh"} {
		var out strings.Builder
		if err := PrintNonInteractiveCommandHelp(&out, target); err != nil {
			t.Fatalf("PrintNonInteractiveCommandHelp(%q): %v", target, err)
		}
		if !strings.Contains(out.String(), "Fields:") {
			t.Errorf("standalone help %q has no Fields section: %q", target, out.String())
		}
		if !strings.Contains(out.String(), "MESSAGES: inbound/outbound") {
			t.Errorf("standalone help %q does not document MESSAGES: %q", target, out.String())
		}
	}
}

// TestCommandsWithoutATablePrintNoFields keeps the widened gate from leaking: a
// command that prints no table must not advertise columns it never shows, because
// a field list there would describe a surface the operator cannot reach.
func TestCommandsWithoutATablePrintNoFields(t *testing.T) {
	for _, target := range []string{"send", "logs", "info", "status", "stop"} {
		var out strings.Builder
		if err := PrintScopedCommandHelp(&out, target, ScopeSession); err != nil {
			t.Fatalf("PrintScopedCommandHelp(%q): %v", target, err)
		}
		if strings.Contains(out.String(), "Fields:") {
			t.Errorf("help %q prints a Fields section but renders no table: %q", target, out.String())
		}
	}
}

// TestRendersSessionTableNamesEveryTableCommand pins the predicate to the
// commands that actually call renderListRows. A new table command added without
// updating this set would leave its columns undocumented, so the set is asserted
// directly instead of being inferred from the help output it produces.
func TestRendersSessionTableNamesEveryTableCommand(t *testing.T) {
	for _, target := range []string{"list", "refresh", "watch"} {
		if !rendersSessionTable(target) {
			t.Errorf("rendersSessionTable(%q)=false, want true", target)
		}
	}
	for _, target := range []string{"send", "logs", "info", "status", "stop", "start", "cd", "help", ""} {
		if rendersSessionTable(target) {
			t.Errorf("rendersSessionTable(%q)=true, want false", target)
		}
	}
}
