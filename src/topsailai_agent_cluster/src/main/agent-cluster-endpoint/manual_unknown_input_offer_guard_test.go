package main

import (
	"go/ast"
	"go/parser"
	"go/token"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"testing"
)

// offerDocumentPath is the operator procedure this guard pins. Every claim it
// makes about the offer is a claim about internal/tui, so the document is
// compared against the functions rather than trusted.
const offerDocumentPath = "tests/manual/live-tmux/unknown-input-send-offer.md"

// offerSourcePath holds the offer implementation.
const offerSourcePath = "internal/tui/interactive_unknown_input.go"

// offerStylePath holds the confirmation hint and the confirmation prompt.
const offerStylePath = "internal/tui/style.go"

// offerHelpPath holds the two help strings the document cites.
const offerHelpPath = "internal/tui/help.go"

// offerNavigationPath holds the explicit cd row-number diagnostic.
const offerNavigationPath = "internal/tui/navigation.go"

// offerOpsPath holds the shared payload rule the offer applies before asking.
const offerOpsPath = "internal/tui/interactive_ops.go"

// offerSourceConsts reads the string constants of one file, so a documented
// marker or hint is compared with the value the code actually uses.
func offerSourceConsts(t *testing.T, root, relative string) map[string]string {
	t.Helper()
	path := filepath.Join(root, relative)
	source, err := os.ReadFile(path)
	if err != nil {
		t.Fatalf("read %s: %v", relative, err)
	}
	file, err := parser.ParseFile(token.NewFileSet(), path, source, 0)
	if err != nil {
		t.Fatalf("parse %s: %v", relative, err)
	}
	consts := map[string]string{}
	for _, decl := range file.Decls {
		gen, ok := decl.(*ast.GenDecl)
		if !ok || gen.Tok != token.CONST {
			continue
		}
		for _, spec := range gen.Specs {
			value, ok := spec.(*ast.ValueSpec)
			if !ok || len(value.Names) != len(value.Values) {
				continue
			}
			for index, name := range value.Names {
				literal, ok := value.Values[index].(*ast.BasicLit)
				if !ok || literal.Kind != token.STRING {
					continue
				}
				text, err := strconv.Unquote(literal.Value)
				if err != nil {
					continue
				}
				consts[name.Name] = text
			}
		}
	}
	if len(consts) == 0 {
		t.Fatalf("%s declares no string constant, so this guard checked nothing", relative)
	}
	return consts
}

// offerParagraph returns the line number and text of the prose paragraph that
// carries an anchor phrase. A heading is its own paragraph, so the anchor is a
// sentence from the case body rather than the case ID. The failure names the
// document that was searched, because the shared helper in the navigation guard
// names its own document.
func offerParagraph(t *testing.T, document, anchor string) (int, string) {
	t.Helper()
	offset := 0
	for _, paragraph := range strings.Split(document, "\n\n") {
		if index := strings.Index(paragraph, anchor); index >= 0 {
			return lineAt(document, offset+index), paragraph
		}
		offset += len(paragraph) + 2
	}
	t.Fatalf("%s holds no paragraph containing %q, so this guard checked nothing", offerDocumentPath, anchor)
	return 0, ""
}

// TestOfferDocumentStatesTheQuestionRowTheCliPrints pins the question row text
// and the diagnostic text against the constants and the format string the offer
// uses, so a tester compares the terminal with the real wording.
func TestOfferDocumentStatesTheQuestionRowTheCliPrints(t *testing.T) {
	root := repoRoot(t)
	document := readRepoFile(t, root, offerDocumentPath)
	if strings.TrimSpace(document) == "" {
		t.Fatalf("%s is empty, so this guard checked nothing", offerDocumentPath)
	}
	consts := offerSourceConsts(t, root, offerSourcePath)
	marker, ok := consts["sendOfferMarker"]
	if !ok {
		t.Fatalf("%s declares no sendOfferMarker, so the question row cannot be pinned", offerSourcePath)
	}
	styleConsts := offerSourceConsts(t, root, offerStylePath)
	hint, ok := styleConsts["confirmationHint"]
	if !ok {
		t.Fatalf("%s declares no confirmationHint, so the question row cannot be pinned", offerStylePath)
	}
	question := marker + "send the text above as a message? " + hint
	if !strings.Contains(document, question) {
		t.Fatalf("%s does not state the question row %q, which is what offerSendForUnknownInput prints, so a tester cannot recognise the offer", offerDocumentPath, question)
	}
	body := functionSource(t, root, offerSourcePath, "offerSendForUnknownInput")
	if !strings.Contains(body, `"unknown command %q (try help)"`) {
		t.Fatalf("%s no longer formats the unknown-command diagnostic as unknown command %%q (try help), so the documented diagnostic is stale", offerSourcePath)
	}
	if !strings.Contains(document, `unknown command "hello" (try help)`) {
		t.Fatalf("%s does not state the diagnostic unknown command \"hello\" (try help), which is what the offer returns when the answer is not yes", offerDocumentPath)
	}
}

// TestOfferDocumentStatesTheScopeGate pins the session-scope-only gate, so the
// document cannot claim the offer appears in a scope where send is unavailable.
func TestOfferDocumentStatesTheScopeGate(t *testing.T) {
	root := repoRoot(t)
	document := readRepoFile(t, root, offerDocumentPath)
	body := functionSource(t, root, offerSourcePath, "offerSendForUnknownInput")
	if !strings.Contains(body, "state.Scope.Kind != ScopeSession") {
		t.Fatalf("%s no longer gates the offer on session scope, so the documented scope rule is stale", offerSourcePath)
	}
	if !strings.Contains(document, "## OFFER-04") {
		t.Fatalf("%s holds no OFFER-04 case, so this guard checked nothing", offerDocumentPath)
	}
	line, paragraph := offerParagraph(t, document, "Type `hello world` then Enter in each scope")
	if !strings.Contains(paragraph, "because `send` is unavailable outside session scope") {
		t.Fatalf("%s:%d does not say the offer is absent outside session scope because send is unavailable there, which is what the scope gate does", offerDocumentPath, line)
	}
	if !strings.Contains(document, "no question") {
		t.Fatalf("%s does not say the other scopes print no question, so a tester expects an offer that never appears", offerDocumentPath)
	}
}

// TestOfferDocumentStatesThePreviewBound pins the preview bound, so a tester who
// types a long line does not report the truncated row as a payload defect.
func TestOfferDocumentStatesThePreviewBound(t *testing.T) {
	root := repoRoot(t)
	document := readRepoFile(t, root, offerDocumentPath)
	body := functionSource(t, root, offerSourcePath, "offerSendForUnknownInput")
	if !strings.Contains(body, "maxSendOfferPreview") {
		t.Fatalf("%s no longer bounds the preview, so the documented preview rule is stale", offerSourcePath)
	}
	consts := offerSourceConsts(t, root, offerSourcePath)
	bound, ok := consts["maxSendOfferPreview"]
	if ok {
		t.Fatalf("maxSendOfferPreview is a string constant %q, so this guard cannot read the numeric bound", bound)
	}
	declared := readRepoFile(t, root, offerSourcePath)
	if !strings.Contains(declared, "const maxSendOfferPreview = 512") {
		t.Fatalf("%s no longer declares maxSendOfferPreview = 512, so the documented bound is stale", offerSourcePath)
	}
	if !strings.Contains(document, "512 bytes") {
		t.Fatalf("%s does not state the 512 byte preview bound, so a tester reports the truncated message row as a payload defect", offerDocumentPath)
	}
	if !strings.Contains(document, "the payload actually sent stays the whole line") {
		t.Fatalf("%s does not say the sent payload stays the whole line, so a tester reads the preview as the payload", offerDocumentPath)
	}
}

// TestOfferDocumentStatesTheRejectedPayloadRule pins the shared payload rule the
// offer applies before asking, so the document cannot promise an offer for a
// payload the send command itself rejects.
func TestOfferDocumentStatesTheRejectedPayloadRule(t *testing.T) {
	root := repoRoot(t)
	document := readRepoFile(t, root, offerDocumentPath)
	body := functionSource(t, root, offerSourcePath, "offerSendForUnknownInput")
	if !strings.Contains(body, `rejectJSONFlagPayload(text, "send")`) {
		t.Fatalf("%s no longer applies rejectJSONFlagPayload before asking, so the documented rejection rule is stale", offerSourcePath)
	}
	rule := functionSource(t, root, offerOpsPath, "rejectJSONFlagPayload")
	if !strings.Contains(rule, `"--json"`) {
		t.Fatalf("%s no longer rejects the --json payload, so the documented rejection rule is stale", offerOpsPath)
	}
	if !strings.Contains(document, "## OFFER-07") {
		t.Fatalf("%s holds no OFFER-07 case, so this guard checked nothing", offerDocumentPath)
	}
	line, paragraph := offerParagraph(t, document, "Expect the plain unknown-command diagnostic and no question")
	if !strings.Contains(paragraph, "`--json`") {
		t.Fatalf("%s:%d does not name the --json payload, which is the one the offer refuses to promise", offerDocumentPath, line)
	}
	if !strings.Contains(paragraph, "no question") {
		t.Fatalf("%s:%d does not say a rejected payload gets no question, so a tester expects an offer that never appears", offerDocumentPath, line)
	}
}

// TestOfferDocumentStatesTheHelpWording pins the two help strings the document
// cites, so the procedure cannot point at help text that no longer exists.
func TestOfferDocumentStatesTheHelpWording(t *testing.T) {
	root := repoRoot(t)
	document := readRepoFile(t, root, offerDocumentPath)
	help := readRepoFile(t, root, offerHelpPath)
	if !strings.Contains(help, "unrecognized text offers this action") {
		t.Fatalf("%s no longer says unrecognized text offers the send action, so the documented help claim is stale", offerHelpPath)
	}
	if !strings.Contains(help, "declining keeps the unknown-command diagnostic") {
		t.Fatalf("%s no longer says declining keeps the diagnostic, so the documented help claim is stale", offerHelpPath)
	}
	if !strings.Contains(document, "## OFFER-05") {
		t.Fatalf("%s holds no OFFER-05 case, so this guard checked nothing", offerDocumentPath)
	}
	line, paragraph := offerParagraph(t, document, "Type `help` then Enter")
	if !strings.Contains(paragraph, "unrecognized text offers the action") {
		t.Fatalf("%s:%d does not state that help says unrecognized text offers the action", offerDocumentPath, line)
	}
	if !strings.Contains(paragraph, "declining keeps the unknown-command diagnostic") {
		t.Fatalf("%s:%d does not state that help says declining keeps the diagnostic", offerDocumentPath, line)
	}
}

// TestOfferDocumentStatesTheExplicitCDDiagnostic pins the explicit cd row-number
// diagnostic, so the document cannot quote a message the CLI never prints.
func TestOfferDocumentStatesTheExplicitCDDiagnostic(t *testing.T) {
	root := repoRoot(t)
	document := readRepoFile(t, root, offerDocumentPath)
	source := readRepoFile(t, root, offerNavigationPath)
	const diagnostic = "row-number navigation is unavailable in session scope; use cd .. or cd <session>"
	if !strings.Contains(source, diagnostic) {
		t.Fatalf("%s no longer prints %q, so the documented diagnostic is stale", offerNavigationPath, diagnostic)
	}
	if !strings.Contains(document, diagnostic) {
		t.Fatalf("%s does not quote the explicit cd diagnostic %q, so a tester cannot recognise the refusal", offerDocumentPath, diagnostic)
	}
	if !strings.Contains(document, "no `row-number navigation is unavailable in session scope` diagnostic") {
		t.Fatalf("%s does not say a bare number prints no row-number diagnostic, which is what the session-scope gate on the numeric rewrite does", offerDocumentPath)
	}
}
