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

// TestLineEditHistoryIsolation keeps prompt values out of retained commands
// while still recording them. Recall and record are separate questions: the
// answer must reach the recorder and must never become recallable.
func TestLineEditHistoryIsolation(t *testing.T) {
	e := newLineEditor(16, 2)
	recorder := &recordingInputRecorder{}
	e.setRecorder(recorder)
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
	// The answer was recorded even though it is not recallable.
	if want := []recordedInput{{InputHistoryKindCommand, "help"}, {InputHistoryKindAnswer, "secret"}}; !recorder.equal(want) {
		t.Fatalf("recorded=%v want=%v", recorder.entries, want)
	}
	typeEditor(e, strings.Repeat("x", 16))
	if got, bad := e.finish(false); got != "" || !bad {
		t.Fatalf("%q %v", got, bad)
	}
	// A rejected input was never accepted, so it is never recorded.
	if len(recorder.entries) != 2 {
		t.Fatalf("rejected input was recorded: %v", recorder.entries)
	}
}

// TestLineEditWrapViewport bounds every wrapped row and keeps the whole text.
// Wrapping is what keeps the head of a long edit visible, so the concatenated
// rows must reproduce the typed text exactly.
func TestLineEditWrapViewport(t *testing.T) {
	for _, value := range []string{"abcdef", "a中文b", "ab\u202ecd", "e\u0301x", strings.Repeat("word ", 40)} {
		e := newLineEditor(4096, 0)
		typeEditor(e, value)
		for cursor := 0; cursor <= len(e.text); cursor++ {
			e.cursor = cursor
			for first := 1; first <= 8; first++ {
				for next := 1; next <= 8; next++ {
					rows, row, column := e.wrapViewport(first, next)
					if len(rows) == 0 {
						t.Fatalf("value=%q first=%d next=%d produced no row", value, first, next)
					}
					if row < 0 || row >= len(rows) || column < 0 {
						t.Fatalf("value=%q cursor row=%d column=%d rows=%d", value, row, column, len(rows))
					}
					for index, text := range rows {
						budget := next
						if index == 0 {
							budget = first
						}
						if displayWidth(text) > budget && len([]rune(text)) > 1 {
							t.Fatalf("value=%q row=%q width=%d budget=%d", value, text, displayWidth(text), budget)
						}
						if strings.ContainsRune(text, '\u202e') {
							t.Fatal("unsafe bidi control rendered")
						}
					}
					if joined := strings.Join(rows, ""); joined != sanitizeTerminal([]byte(value)) {
						t.Fatalf("value=%q joined=%q", value, joined)
					}
				}
			}
		}
	}
}
