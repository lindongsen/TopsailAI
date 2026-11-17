package tui

import (
	"strings"
	"testing"
)

// fieldHelpKeysOf returns the column name each entry documents, taken from the
// text before the first colon.
func fieldHelpKeysOf(entries []string) []string {
	keys := make([]string, 0, len(entries))
	for _, entry := range entries {
		name, _, found := strings.Cut(entry, ":")
		if !found {
			continue
		}
		keys = append(keys, strings.TrimSpace(name))
	}
	return keys
}

// tableLayouts pairs each table with the columns it prints and the field list that
// documents them. Every table is listed here, so the coverage rule below applies to
// all of them rather than only to the session table.
func tableLayouts() []struct {
	name    string
	columns []tableColumn
	fields  []string
} {
	return []struct {
		name    string
		columns []tableColumn
		fields  []string
	}{
		{"session", allColumns, fieldHelp},
		{"history", historyColumns, historyFieldHelp},
		{"endpoint", endpointColumns, endpointFieldHelp},
		{"model", modelCatalogColumns, modelFieldHelp},
	}
}

// TestEveryRenderedColumnInEveryTableIsDocumented applies the coverage rule to
// every table, not only the session table. It reads the real column slices rather
// than a copy of the header names, so a renamed or added column is covered without
// editing the test.
func TestEveryRenderedColumnInEveryTableIsDocumented(t *testing.T) {
	for _, layout := range tableLayouts() {
		documented := make(map[string]bool, len(layout.fields))
		for _, key := range fieldHelpKeysOf(layout.fields) {
			documented[key] = true
		}
		for _, column := range layout.columns {
			if !documented[column.header] {
				t.Errorf("%s column %q is rendered but has no field help entry", layout.name, column.header)
			}
		}
	}
}

// TestNoFieldHelpEntryIsStale is the other half: an entry for a column a table no
// longer prints describes something the operator cannot see.
func TestNoFieldHelpEntryIsStale(t *testing.T) {
	for _, layout := range tableLayouts() {
		rendered := make(map[string]bool, len(layout.columns))
		for _, column := range layout.columns {
			rendered[column.header] = true
		}
		for _, key := range fieldHelpKeysOf(layout.fields) {
			if !rendered[key] {
				t.Errorf("%s field help documents %q, which is not a rendered column", layout.name, key)
			}
		}
	}
}

// TestNoTwoTablesShareOneFieldList keeps each table documented by its own list. A
// shared list would document columns a table never prints, which is the same defect
// as documenting none of them.
func TestNoTwoTablesShareOneFieldList(t *testing.T) {
	layouts := tableLayouts()
	for i := range layouts {
		for j := i + 1; j < len(layouts); j++ {
			if strings.Join(layouts[i].fields, "\n") == strings.Join(layouts[j].fields, "\n") {
				t.Errorf("the %s and %s tables share one field list", layouts[i].name, layouts[j].name)
			}
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

// TestTableFieldHelpNamesEveryTableCommand pins the predicate to the commands
// that actually render a table. A new table command added without updating this
// set would leave its columns undocumented, so the set is asserted directly
// instead of being inferred from the help output it produces.
func TestTableFieldHelpNamesEveryTableCommand(t *testing.T) {
	for _, target := range []string{"list", "refresh", "watch", "history", "endpoints", "model"} {
		if got := tableFieldHelp(target); len(got) == 0 {
			t.Errorf("tableFieldHelp(%q) is empty, want a field list", target)
		}
	}
	for _, target := range []string{"send", "logs", "info", "status", "stop", "start", "cd", "help", ""} {
		if got := tableFieldHelp(target); len(got) != 0 {
			t.Errorf("tableFieldHelp(%q) returned %d fields, want none", target, len(got))
		}
	}
}

// TestTableFieldHelpSelectsTheLayoutThatMatchesTheTable keeps the two tables from
// sharing one list. A history row has no generation and no data-status stamp, so
// lending it the session list would document columns it never prints, and lending
// the session table the history list would drop the columns it does print.
func TestTableFieldHelpSelectsTheLayoutThatMatchesTheTable(t *testing.T) {
	session := strings.Join(tableFieldHelp("list"), "\n")
	history := strings.Join(tableFieldHelp("history"), "\n")
	if session == history {
		t.Fatal("the session and history tables share one field list")
	}
	for _, want := range []string{"DATA_STATUS:", "DRIVER:", "MESSAGES:"} {
		if !strings.Contains(session, want) {
			t.Errorf("session field list is missing %q", want)
		}
		if strings.Contains(history, want) {
			t.Errorf("history field list documents %q, a column history never prints", want)
		}
	}
	for _, want := range []string{"LIVE:", "RESUMABLE:", "PROVIDER_STATUS:"} {
		if !strings.Contains(history, want) {
			t.Errorf("history field list is missing %q", want)
		}
		if strings.Contains(session, want) {
			t.Errorf("session field list documents %q, a column the session table never prints", want)
		}
	}
}

// TestHistoryHelpPrintsItsFields proves the history command actually renders the
// list it is assigned, on both surfaces. The predicate returning a list is not
// evidence that the renderer used it, so the rendered output is asserted.
func TestHistoryHelpPrintsItsFields(t *testing.T) {
	var interactive strings.Builder
	if err := PrintScopedCommandHelp(&interactive, "history", ScopeWorkspace); err != nil {
		t.Fatalf("PrintScopedCommandHelp(history): %v", err)
	}
	var standalone strings.Builder
	if err := PrintCommandHelp(&standalone, "history"); err != nil {
		t.Fatalf("PrintCommandHelp(history): %v", err)
	}
	for name, out := range map[string]string{"interactive": interactive.String(), "standalone": standalone.String()} {
		if !strings.Contains(out, "Fields:") {
			t.Fatalf("%s help history has no Fields section: %q", name, out)
		}
		for _, want := range []string{"LIVE:", "RESUMABLE:", "PROVIDER_STATUS:"} {
			if !strings.Contains(out, want) {
				t.Errorf("%s help history is missing %q", name, want)
			}
		}
		if strings.Contains(out, "DATA_STATUS:") {
			t.Errorf("%s help history documents DATA_STATUS, a column history never prints", name)
		}
	}
}
