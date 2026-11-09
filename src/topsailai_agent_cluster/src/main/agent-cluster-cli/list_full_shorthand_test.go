package main

import (
	"encoding/json"
	"strings"
	"testing"

	"topsailai_agent_cluster/internal/tui"
)

// listFullBaseArgs returns the standalone arguments shared by every list
// rendering case, so a test varies only the spelling under test.
func listFullBaseArgs(serverURL string) []string {
	return []string{"--server-url", serverURL, "--token", "test-token", "--endpoint", "endpoint-1"}
}

// TestListFullFlagKeepsFullValues proves the standalone --full flag stops the
// column caps from clipping a value, so the per-command request works without
// the startup --no-truncate option.
func TestListFullFlagKeepsFullValues(t *testing.T) {
	server := newNoTruncateServer(t)
	defer server.Close()
	sessionID := noTruncateSessionID()
	args := append(listFullBaseArgs(server.URL), "list", "--full")
	var output, diagnostics strings.Builder
	if err := runWithIO(args, strings.NewReader(""), &output, &diagnostics, false, nil); err != nil {
		t.Fatalf("list --full failed: %v diagnostics=%q", err, diagnostics.String())
	}
	if !strings.Contains(output.String(), sessionID) {
		t.Fatalf("list --full truncated the value: %q", output.String())
	}
	if strings.Contains(output.String(), "...") {
		t.Fatalf("list --full emitted a truncation marker: %q", output.String())
	}
}

// TestListFullShorthandMatchesFullFlag proves lf renders exactly what
// "list --full" renders, so the shorthand is one spelling of one behaviour
// rather than a second implementation that can drift.
func TestListFullShorthandMatchesFullFlag(t *testing.T) {
	server := newNoTruncateServer(t)
	defer server.Close()
	var flagOutput, shorthandOutput, diagnostics strings.Builder
	flagArgs := append(listFullBaseArgs(server.URL), "list", "--full")
	if err := runWithIO(flagArgs, strings.NewReader(""), &flagOutput, &diagnostics, false, nil); err != nil {
		t.Fatalf("list --full failed: %v diagnostics=%q", err, diagnostics.String())
	}
	shorthandArgs := append(listFullBaseArgs(server.URL), tui.ListFullAlias)
	if err := runWithIO(shorthandArgs, strings.NewReader(""), &shorthandOutput, &diagnostics, false, nil); err != nil {
		t.Fatalf("%s failed: %v diagnostics=%q", tui.ListFullAlias, err, diagnostics.String())
	}
	if flagOutput.String() != shorthandOutput.String() {
		t.Fatalf("shorthand output differs from list --full:\nfull=%q\nshorthand=%q", flagOutput.String(), shorthandOutput.String())
	}
}

// TestListFullShorthandIsNotTheBoundedList proves the shorthand actually changes
// the rendering. Without this case a shorthand that silently resolved to plain
// list would pass every other test, because a truncated table still looks like a
// complete one.
func TestListFullShorthandIsNotTheBoundedList(t *testing.T) {
	server := newNoTruncateServer(t)
	defer server.Close()
	sessionID := noTruncateSessionID()
	var boundedOutput, shorthandOutput, diagnostics strings.Builder
	boundedArgs := append(listFullBaseArgs(server.URL), "list", "--clean")
	if err := runWithIO(boundedArgs, strings.NewReader(""), &boundedOutput, &diagnostics, false, nil); err != nil {
		t.Fatalf("bounded list failed: %v diagnostics=%q", err, diagnostics.String())
	}
	if strings.Contains(boundedOutput.String(), sessionID) {
		t.Fatalf("bounded list kept the over-cap value, so this case cannot detect a dropped flag: %q", boundedOutput.String())
	}
	shorthandArgs := append(listFullBaseArgs(server.URL), tui.ListFullAlias)
	if err := runWithIO(shorthandArgs, strings.NewReader(""), &shorthandOutput, &diagnostics, false, nil); err != nil {
		t.Fatalf("%s failed: %v diagnostics=%q", tui.ListFullAlias, err, diagnostics.String())
	}
	if !strings.Contains(shorthandOutput.String(), sessionID) {
		t.Fatalf("shorthand degraded into the bounded list: %q", shorthandOutput.String())
	}
}

// TestListFullShorthandAcceptsClean proves the shorthand inherits the list
// grammar instead of defining its own, so --clean still works beside it.
func TestListFullShorthandAcceptsClean(t *testing.T) {
	server := newNoTruncateServer(t)
	defer server.Close()
	sessionID := noTruncateSessionID()
	args := append(listFullBaseArgs(server.URL), tui.ListFullAlias, "--clean")
	var output, diagnostics strings.Builder
	if err := runWithIO(args, strings.NewReader(""), &output, &diagnostics, false, nil); err != nil {
		t.Fatalf("%s --clean failed: %v diagnostics=%q", tui.ListFullAlias, err, diagnostics.String())
	}
	if !strings.Contains(output.String(), sessionID) {
		t.Fatalf("%s --clean lost the full layout: %q", tui.ListFullAlias, output.String())
	}
}

// TestListFullShorthandRejectsRepeatedFullFlag proves the shorthand refuses a
// flag it already implies, because the operator who typed it twice cannot tell
// which one took effect.
func TestListFullShorthandRejectsRepeatedFullFlag(t *testing.T) {
	args := append(listFullBaseArgs("http://127.0.0.1:1"), tui.ListFullAlias, "--full")
	var output, diagnostics strings.Builder
	err := runWithIO(args, strings.NewReader(""), &output, &diagnostics, false, nil)
	if err == nil {
		t.Fatalf("repeated --full was accepted")
	}
	if !strings.Contains(err.Error(), "full is implied; drop --full") {
		t.Fatalf("error=%v does not explain the contradiction", err)
	}
	if !strings.Contains(err.Error(), tui.ListFullAlias) {
		t.Fatalf("error=%v does not name the typed spelling", err)
	}
}

// TestListRejectsRepeatedFullFlag proves the canonical spelling also rejects a
// repeated flag, so the two spellings agree about what is a usage error.
func TestListRejectsRepeatedFullFlag(t *testing.T) {
	args := append(listFullBaseArgs("http://127.0.0.1:1"), "list", "--full", "--full")
	var output, diagnostics strings.Builder
	err := runWithIO(args, strings.NewReader(""), &output, &diagnostics, false, nil)
	if err == nil {
		t.Fatalf("repeated --full was accepted")
	}
	if !strings.Contains(err.Error(), "list [--clean] [--full]") {
		t.Fatalf("error=%v does not name the list usage line", err)
	}
}

// TestListFullShorthandUsageNamesItsOwnSpelling proves a usage error answers with
// the spelling the operator typed, so lf never reports a command they did not run.
func TestListFullShorthandUsageNamesItsOwnSpelling(t *testing.T) {
	args := append(listFullBaseArgs("http://127.0.0.1:1"), tui.ListFullAlias, "--bogus")
	var output, diagnostics strings.Builder
	err := runWithIO(args, strings.NewReader(""), &output, &diagnostics, false, nil)
	if err == nil {
		t.Fatalf("unknown option was accepted")
	}
	if !strings.Contains(err.Error(), tui.ListFullAlias) {
		t.Fatalf("error=%v does not name the typed spelling", err)
	}
	if strings.Contains(err.Error(), " list ") {
		t.Fatalf("error=%v answers with the canonical spelling", err)
	}
}

// TestListFullShorthandKeepsStartupNoTruncate proves the per-command flag is ORed
// with the startup option rather than replacing it, so a command that omits the
// flag cannot silently re-enable truncation.
func TestListFullShorthandKeepsStartupNoTruncate(t *testing.T) {
	server := newNoTruncateServer(t)
	defer server.Close()
	sessionID := noTruncateSessionID()
	args := append([]string{"--no-truncate"}, listFullBaseArgs(server.URL)...)
	args = append(args, "list", "--clean")
	var output, diagnostics strings.Builder
	if err := runWithIO(args, strings.NewReader(""), &output, &diagnostics, false, nil); err != nil {
		t.Fatalf("--no-truncate list failed: %v diagnostics=%q", err, diagnostics.String())
	}
	if !strings.Contains(output.String(), sessionID) {
		t.Fatalf("--no-truncate was lost: %q", output.String())
	}
}

// TestListFullShorthandKeepsJSONDocument proves the shorthand does not corrupt
// the machine-readable document, so a --json caller receives the full value
// without any table rendering.
func TestListFullShorthandKeepsJSONDocument(t *testing.T) {
	server := newNoTruncateServer(t)
	defer server.Close()
	sessionID := noTruncateSessionID()
	args := append(listFullBaseArgs(server.URL), tui.ListFullAlias, "--json")
	var output, diagnostics strings.Builder
	if err := runWithIO(args, strings.NewReader(""), &output, &diagnostics, false, nil); err != nil {
		t.Fatalf("%s --json failed: %v diagnostics=%q", tui.ListFullAlias, err, diagnostics.String())
	}
	var document []map[string]any
	if err := json.Unmarshal([]byte(output.String()), &document); err != nil {
		t.Fatalf("--json output is not one JSON document: %v output=%q", err, output.String())
	}
	if len(document) != 1 {
		t.Fatalf("--json output has %d rows, want 1: %q", len(document), output.String())
	}
	if got := document[0]["session_id"]; got != sessionID {
		t.Fatalf("--json session_id=%v want=%q", got, sessionID)
	}
}

// TestListFullShorthandHelpKeepsTypedSpelling proves help answers the shorthand
// with the spelling the operator typed and names the canonical command, so the
// form is discoverable without being advertised as a command of its own.
func TestListFullShorthandHelpKeepsTypedSpelling(t *testing.T) {
	var output, diagnostics strings.Builder
	if err := runWithIO([]string{"help", tui.ListFullAlias}, strings.NewReader(""), &output, &diagnostics, false, nil); err != nil {
		t.Fatalf("help %s: %v", tui.ListFullAlias, err)
	}
	rendered := output.String()
	if !strings.HasPrefix(rendered, tui.ListFullAlias+"\n") {
		t.Fatalf("help heading does not keep the typed spelling: %q", rendered)
	}
	if !strings.Contains(rendered, "Alias of: list") {
		t.Fatalf("help does not name the canonical command: %q", rendered)
	}
	if !strings.Contains(rendered, "--full") {
		t.Fatalf("help does not document --full: %q", rendered)
	}
}

// TestListFullShorthandStaysOffTheOverview proves the shorthand is not advertised
// as a separate command, because it is a form of list rather than a command of
// its own and the overview keeps one spelling per command.
func TestListFullShorthandStaysOffTheOverview(t *testing.T) {
	var output, diagnostics strings.Builder
	if err := runWithIO([]string{"help"}, strings.NewReader(""), &output, &diagnostics, false, nil); err != nil {
		t.Fatalf("help: %v", err)
	}
	// The check is per token, not per substring: "lf" also occurs inside the word
	// "behalf" in the drive description, so a substring match would report a
	// shorthand that the overview never advertises.
	for _, line := range strings.Split(output.String(), "\n") {
		for _, token := range strings.Fields(line) {
			if token == tui.ListFullAlias {
				t.Fatalf("overview advertises the shorthand as a command word: %q", line)
			}
		}
	}
}
