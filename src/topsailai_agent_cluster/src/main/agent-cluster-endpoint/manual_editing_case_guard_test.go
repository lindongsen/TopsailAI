package main

import (
	"go/ast"
	"go/parser"
	"go/token"
	"path/filepath"
	"regexp"
	"sort"
	"strings"
	"testing"
)

// This guard exists because tests/manual/live-tmux/editing.md tells a tester what
// the terminal editor must do, and two of its claims are statements about code:
// which candidates a Tab press offers, and what happens to an answer that is not
// a command. Prose keeps reading as fact after the code changes, so both claims
// are recomputed from the source instead of trusted.
//
// It is separate from manual_command_set_guard_test.go, which pins the command
// surface the documents advertise, and from manual_evidence_citation_guard_test.go,
// which pins the files and error codes the manual harness cites. This one pins the
// editing cases: the completion candidate set and the answer-recording rule.

const (
	// editingDocumentFile is the manual case table for terminal editing.
	editingDocumentFile = "tests/manual/live-tmux/editing.md"
	// inputHistorySourceFile holds the recording and recall rules.
	inputHistorySourceFile = "internal/tui/input_history.go"
)

// editingCandidateClaim matches the candidate pair EDIT-02 states.
var editingCandidateClaim = regexp.MustCompile("candidates ([a-z]+) and ([a-z]+)")

// editingAnswerClaim matches a sentence that states what happens to an answer.
var editingAnswerClaim = regexp.MustCompile("answers? recorded but never recallable")

// editingHistoryDenial matches the wording that used to describe an answer, which
// is wrong: an answer is written to the history file and only kept out of recall.
var editingHistoryDenial = regexp.MustCompile("answers? excluded from history")

// TestEditingDocumentStatesTheCompletionCandidates fails when EDIT-02 names a
// candidate set the editor does not offer.
//
// The set is recomputed from commandScopeMatrix and commandAliases, because a
// candidate list copied into prose drifts from the matrix that decides it. The
// document said session "st" offers stop and status, which holds only because
// start is workspace and endpoint only; that exclusion is a fact worth pinning
// rather than trusting.
func TestEditingDocumentStatesTheCompletionCandidates(t *testing.T) {
	truth := loadCommandTruth(t)

	text := readRepoFile(t, repoRoot(t), editingDocumentFile)
	if strings.TrimSpace(text) == "" {
		t.Fatalf("%s is empty, so this guard checked nothing", editingDocumentFile)
	}

	// EDIT-02 types "st" at a session prompt, so the candidate set is every
	// completable word in session scope that starts with "st".
	words := truth.completableFor("session")
	matches := make([]string, 0, len(words))
	for _, word := range words {
		if strings.HasPrefix(word, "st") {
			matches = append(matches, word)
		}
	}
	if len(matches) == 0 {
		t.Fatalf("no session-scope command starts with st, so this guard checked nothing")
	}

	// The candidate set is compared as a set, not as a sequence: the document
	// writes the pair in alphabetical order while the matrix keeps registration
	// order, and neither order is a claim the tester acts on.
	sort.Strings(matches)

	claim := editingCandidateClaim.FindStringSubmatch(text)
	if claim == nil {
		t.Fatalf("%s states no candidate pair for EDIT-02, so this guard checked nothing", editingDocumentFile)
	}
	stated := []string{claim[1], claim[2]}
	sort.Strings(stated)
	if strings.Join(stated, ",") != strings.Join(matches, ",") {
		t.Errorf("%s:%d states the session st candidates as %s, but the scope matrix and alias registry offer %s, so a tester checks for a candidate the editor never shows", editingDocumentFile, lineAt(text, strings.Index(text, claim[0])), strings.Join(stated, " and "), strings.Join(matches, " and "))
	}
}

// TestEditingDocumentStatesHowAnswersAreRecorded fails when the document claims an
// answer is excluded from history.
//
// Record writes an answer to the history file with kind "answer"; only load keeps
// it out of the recall list. A tester who reads "excluded from history" greps the
// file, finds the answer, and reports a defect that is not there.
func TestEditingDocumentStatesHowAnswersAreRecorded(t *testing.T) {
	root := repoRoot(t)
	history := parseRepoGoFile(t, root, inputHistorySourceFile)

	// The premise: Record accepts an answer, and load keeps only commands in the
	// recall list. If either changes, the document's claim is no longer the thing
	// this guard should pin, so the guard fails instead of passing silently.
	if !bodyMentions(functionBody(t, history, "Record"), "InputHistoryKindAnswer") {
		t.Fatalf("%s no longer records an answer, so this guard's premise is gone", inputHistorySourceFile)
	}
	if !bodyMentions(functionBody(t, history, "load"), "InputHistoryKindCommand") {
		t.Fatalf("%s no longer filters recall to commands, so this guard's premise is gone", inputHistorySourceFile)
	}

	text := readRepoFile(t, root, editingDocumentFile)
	if strings.TrimSpace(text) == "" {
		t.Fatalf("%s is empty, so this guard checked nothing", editingDocumentFile)
	}
	if denial := editingHistoryDenial.FindStringIndex(text); denial != nil {
		t.Errorf("%s:%d says an answer is excluded from history, but %s writes it to the history file and only keeps it out of recall, so a tester who greps the file reports a defect that is not there", editingDocumentFile, lineAt(text, denial[0]), inputHistorySourceFile)
	}
	if !editingAnswerClaim.MatchString(text) {
		t.Fatalf("%s states no answer-recording rule, so this guard checked nothing", editingDocumentFile)
	}
}

// completableFor mirrors completableCommands: every canonical command the scope
// permits plus each multi-character alias whose canonical target the scope
// permits. A one-character alias is already complete when typed, so it is never
// offered.
func (truth commandTruth) completableFor(scope string) []string {
	names := truth.namesFor(scope)
	allowed := make(map[string]bool, len(names))
	for _, name := range names {
		allowed[name] = true
	}
	extra := make([]string, 0, len(truth.Aliases))
	for alias, target := range truth.Aliases {
		if len(alias) < 2 || !allowed[target] {
			continue
		}
		extra = append(extra, alias)
	}
	sort.Strings(extra)
	return append(names, extra...)
}

// parseRepoGoFile parses one repository Go file.
func parseRepoGoFile(t *testing.T, root, relative string) *ast.File {
	t.Helper()
	parsed, err := parser.ParseFile(token.NewFileSet(), filepath.Join(root, relative), nil, 0)
	if err != nil {
		t.Fatalf("parse %s: %v", relative, err)
	}
	return parsed
}

// functionBody returns the body of a named function.
func functionBody(t *testing.T, file *ast.File, name string) *ast.BlockStmt {
	t.Helper()
	for _, declaration := range file.Decls {
		function, ok := declaration.(*ast.FuncDecl)
		if !ok || function.Name.Name != name || function.Body == nil {
			continue
		}
		return function.Body
	}
	t.Fatalf("no function %s was found, so this guard checked nothing", name)
	return nil
}

// bodyMentions reports whether a function body names an identifier.
func bodyMentions(body *ast.BlockStmt, needle string) bool {
	found := false
	ast.Inspect(body, func(node ast.Node) bool {
		if identifier, ok := node.(*ast.Ident); ok && identifier.Name == needle {
			found = true
		}
		return !found
	})
	return found
}
