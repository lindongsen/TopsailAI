package main

import (
	"go/ast"
	"go/parser"
	"go/token"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

// navigationDocument is the manual procedure whose navigation claims this guard
// pins. It is the only manual document that describes the scope prompt, the
// session-entry output and the row-reading commands.
const navigationDocument = "tests/manual/live-tmux/navigation.md"

// functionSource returns the source text of one named function. A guard that
// asserts what a function does must read the function, not a copy of its
// behaviour, so the body is sliced out of the parsed file instead of being
// re-implemented here.
func functionSource(t *testing.T, root, relative, name string) string {
	t.Helper()
	path := filepath.Join(root, relative)
	source, err := os.ReadFile(path)
	if err != nil {
		t.Fatalf("read %s: %v", relative, err)
	}
	files := token.NewFileSet()
	file, err := parser.ParseFile(files, path, source, 0)
	if err != nil {
		t.Fatalf("parse %s: %v", relative, err)
	}
	for _, decl := range file.Decls {
		fn, ok := decl.(*ast.FuncDecl)
		if !ok || fn.Name.Name != name || fn.Body == nil {
			continue
		}
		start := files.Position(fn.Pos()).Offset
		end := files.Position(fn.End()).Offset
		return string(source[start:end])
	}
	t.Fatalf("%s declares no function %s, so this guard read nothing", relative, name)
	return ""
}

// caseLine returns the line number and text of one manual case row, so a
// failure names the row a tester would follow.
func caseLine(t *testing.T, document, caseID string) (int, string) {
	t.Helper()
	for index, line := range strings.Split(document, "\n") {
		if strings.HasPrefix(line, "| "+caseID+" |") {
			return index + 1, line
		}
	}
	t.Fatalf("%s holds no %s row, so this guard checked nothing", navigationDocument, caseID)
	return 0, ""
}

// paragraphContaining returns the line number and text of the prose paragraph
// that carries an anchor phrase. A claim that spans a wrapped sentence cannot be
// checked one line at a time, so the paragraph is the unit.
func paragraphContaining(t *testing.T, document, anchor string) (int, string) {
	t.Helper()
	offset := 0
	for _, paragraph := range strings.Split(document, "\n\n") {
		if index := strings.Index(paragraph, anchor); index >= 0 {
			return lineAt(document, offset+index), paragraph
		}
		offset += len(paragraph) + 2
	}
	t.Fatalf("%s holds no paragraph containing %q, so this guard checked nothing", navigationDocument, anchor)
	return 0, ""
}

// TestNavigationDocumentStatesTheSessionPromptShape pins the prompt NAV-04
// describes. The prompt is built by renderPrompt, so the shape is read from that
// function: the scope name, then a bracketed hostname and provider session ID,
// a dash when the provider session ID is unknown, and an exclamation mark when
// the selection is invalidated. A document that names a different element sends
// a tester looking for output the CLI never prints.
func TestNavigationDocumentStatesTheSessionPromptShape(t *testing.T) {
	root := repoRoot(t)
	body := functionSource(t, root, "internal/tui/style.go", "renderPrompt")
	for _, fragment := range []string{`"["`, `"/"`, `"-"`, `"!"`, `"]"`} {
		if !strings.Contains(body, fragment) {
			t.Fatalf("renderPrompt no longer builds the session prompt from %s, so this guard checked nothing", fragment)
		}
	}

	document := readRepoFile(t, root, navigationDocument)
	line, text := caseLine(t, document, "NAV-04")
	if !strings.Contains(text, "session[") || !strings.Contains(text, "provider-session-id") {
		t.Fatalf("%s:%d does not state the prompt as session[<hostname>/<provider-session-id>], which is what renderPrompt builds, so a tester cannot recognise the prompt", navigationDocument, line)
	}
	if strings.Contains(text, "provider label") {
		t.Fatalf("%s:%d names a provider label, but renderPrompt prints the endpoint hostname and the provider session ID and no label exists in the CLI, so a tester looks for output that never appears", navigationDocument, line)
	}
}

// sentenceContaining returns the sentence that carries an anchor phrase. A claim
// and the diagnostic it quotes can sit in the same paragraph, so a paragraph-wide
// search is satisfied by the quoted message instead of by the claim. The sentence
// is the smallest unit that still survives a wrapped line.
func sentenceContaining(t *testing.T, paragraph, anchor string) string {
	t.Helper()
	for _, sentence := range strings.Split(paragraph, ". ") {
		if strings.Contains(sentence, anchor) {
			return sentence
		}
	}
	t.Fatalf("no sentence in the paragraph contains %q, so this guard checked nothing", anchor)
	return ""
}

// TestNavigationDocumentStatesTheSessionEntryOutput pins what entering a session
// prints. autoFollowAfterAction arms a live tail when the client can stream and
// the input mode can observe a keypress, and renders one bounded snapshot only as
// the announced fallback. A document that promises a snapshot describes the
// degraded path as if it were the normal one, so a tester reports the tail as a
// defect.
func TestNavigationDocumentStatesTheSessionEntryOutput(t *testing.T) {
	root := repoRoot(t)
	body := functionSource(t, root, "internal/tui/interactive_ops.go", "autoFollowAfterAction")
	if !strings.Contains(body, "armFollowStream") {
		t.Fatalf("autoFollowAfterAction no longer arms a live tail, so this guard checked nothing")
	}
	if !strings.Contains(body, "renderAutomaticSnapshot") {
		t.Fatalf("autoFollowAfterAction no longer renders a fallback snapshot, so this guard checked nothing")
	}

	document := readRepoFile(t, root, navigationDocument)
	line, paragraph := paragraphContaining(t, document, "Entering session scope")
	// The claim sentence must name the tail. Searching the whole paragraph would
	// be satisfied by the quoted fallback diagnostic, which also contains the
	// words "live tail", so the claim itself is the unit that is checked.
	claim := sentenceContaining(t, paragraph, "Entering session scope")
	if !strings.Contains(claim, "arms one live tail") {
		t.Fatalf("%s:%d does not say that entering a session arms one live tail, which is what autoFollowAfterAction does, so a tester expects a snapshot and reports the tail as a defect", navigationDocument, line)
	}
	if strings.Contains(claim, "snapshot") {
		t.Fatalf("%s:%d describes the entry as a snapshot, but autoFollowAfterAction arms a live tail and only falls back to a snapshot, so the normal path is described as the degraded one", navigationDocument, line)
	}
	if !strings.Contains(paragraph, "degrades to one bounded snapshot") {
		t.Fatalf("%s:%d does not describe the announced snapshot fallback, so a tester in an input mode that cannot stop a tail cannot tell the fallback from a defect", navigationDocument, line)
	}
}

// TestNavigationDocumentStatesThatReadingARowKeepsTheSelection pins NAV-09. Both
// logs and show resolve a row and read that row's session; neither enters it, so
// the selected session and the prompt are unchanged. A document that says the row
// is selected makes a tester check the prompt and report a defect that is not
// there.
func TestNavigationDocumentStatesThatReadingARowKeepsTheSelection(t *testing.T) {
	root := repoRoot(t)
	// interactiveLogs lives in interactive_ops.go and interactiveShow in
	// interactive.go, so each is read from the file that declares it.
	for _, target := range []struct{ file, name string }{
		{"internal/tui/interactive_ops.go", "interactiveLogs"},
		{"internal/tui/interactive.go", "interactiveShow"},
	} {
		body := functionSource(t, root, target.file, target.name)
		if strings.Contains(body, "enterSession") || strings.Contains(body, "state.Scope =") {
			t.Fatalf("%s now changes the selected session, so the NAV-09 claim must be revisited instead of pinned", target.name)
		}
	}

	document := readRepoFile(t, root, navigationDocument)
	line, text := caseLine(t, document, "NAV-09")
	if !strings.Contains(text, "without changing the selected session") {
		t.Fatalf("%s:%d does not say that reading a row keeps the selected session, which is what interactiveLogs and interactiveShow do, so a tester checks the prompt and reports a defect that is not there", navigationDocument, line)
	}
	if strings.Contains(text, "the session at that row is selected") {
		t.Fatalf("%s:%d says the row's session is selected, but logs and show only read it, so a tester expects a prompt change that never happens", navigationDocument, line)
	}
}
