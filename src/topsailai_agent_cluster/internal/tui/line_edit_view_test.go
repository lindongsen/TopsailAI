package tui

import (
	"strings"
	"testing"
)

// TestLineEditDispatch checks every editing action and explicit terminal outcome.
func TestLineEditDispatch(t *testing.T) {
	e := newLineEditor(64, 2)
	for _, r := range "abc" {
		e.apply(lineKey{kind: lineKeyText, text: r}, true)
	}
	for _, kind := range []lineKeyKind{lineKeyHome, lineKeyRight, lineKeyDelete, lineKeyEnd, lineKeyBackspace, lineKeyLeft} {
		if got := e.apply(lineKey{kind: kind}, true); got != lineEditContinue {
			t.Fatal(got)
		}
	}
	if string(e.text) != "a" || e.cursor != 0 {
		t.Fatalf("editor=%+v", e)
	}
	if e.apply(lineKey{kind: lineKeyEOF}, true) != lineEditContinue || len(e.text) != 0 {
		t.Fatal("nonempty Ctrl-D must delete")
	}
	for kind, want := range map[lineKeyKind]lineEditOutcome{lineKeyEOF: lineEditEOF, lineKeyEnter: lineEditSubmit, lineKeyInterrupt: lineEditInterrupt} {
		if got := e.apply(lineKey{kind: kind}, true); got != want {
			t.Fatalf("kind=%d got=%d", kind, got)
		}
	}
}

// TestLineEditHistoryIsolation keeps prompt values out of retained commands.
func TestLineEditHistoryIsolation(t *testing.T) {
	e := newLineEditor(16, 2)
	typeEditor(e, "help")
	e.finish(true)
	e.apply(lineKey{kind: lineKeyPrevious}, true)
	if string(e.text) != "help" {
		t.Fatal(string(e.text))
	}
	e.apply(lineKey{kind: lineKeyNext}, true)
	typeEditor(e, "secret")
	e.apply(lineKey{kind: lineKeyPrevious}, false)
	e.apply(lineKey{kind: lineKeyNext}, false)
	if got, bad := e.finish(false); got != "secret" || bad || len(e.history) != 1 {
		t.Fatalf("got=%q bad=%v history=%v", got, bad, e.history)
	}
	typeEditor(e, strings.Repeat("x", 16))
	if got, bad := e.finish(false); got != "" || !bad {
		t.Fatalf("%q %v", got, bad)
	}
}

// TestLineEditViewport bounds text and cursor without terminal control injection.
func TestLineEditViewport(t *testing.T) {
	for _, value := range []string{"abcdef", "a中文b", "ab\u202ecd", "e\u0301x"} {
		e := newLineEditor(100, 0)
		typeEditor(e, value)
		for cursor := 0; cursor <= len(e.text); cursor++ {
			e.cursor = cursor
			for width := 0; width <= 8; width++ {
				text, col := e.viewport(width)
				if displayWidth(text) > width || col < 0 || (width > 0 && col >= width) {
					t.Fatalf("value=%q width=%d text=%q col=%d", value, width, text, col)
				}
				if strings.ContainsRune(text, '\u202e') {
					t.Fatal("unsafe bidi control rendered")
				}
			}
		}
	}
}
