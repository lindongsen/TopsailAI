package tui

import "testing"

// typeEditor enters Unicode text through the same bounded insertion operation.
func typeEditor(e *lineEditor, value string) {
	for _, r := range value {
		e.insert(r)
	}
}

// TestLineEditorUnicode edits at rune boundaries without changing byte accounting.
func TestLineEditorUnicode(t *testing.T) {
	e := newLineEditor(20, 2)
	typeEditor(e, "a中b")
	e.move(-1)
	e.insert('文')
	e.erase(true)
	e.erase(false)
	e.move(-100)
	e.erase(true)
	e.insert('首')
	e.move(100)
	e.erase(false)
	if string(e.text) != "首a中" || e.bytes != 7 || e.cursor != 3 {
		t.Fatalf("editor=%+v", e)
	}
	got, bad := e.submit()
	if got != "首a中" || bad || e.bytes != 0 {
		t.Fatalf("got=%q bad=%v editor=%+v", got, bad, e)
	}
}

// TestLineEditorOverflow refuses the entire line even after destructive edits.
func TestLineEditorOverflow(t *testing.T) {
	for _, value := range []string{"abcd", "中a"} {
		e := newLineEditor(4, 2)
		typeEditor(e, value)
		e.erase(true)
		e.recall(true)
		got, bad := e.submit()
		if got != "" || !bad || len(e.history) != 0 {
			t.Fatalf("value=%q got=%q bad=%v", value, got, bad)
		}
		typeEditor(e, "中")
		got, bad = e.submit()
		if got != "中" || bad {
			t.Fatalf("exact byte limit: %q %v", got, bad)
		}
	}
}

// TestLineEditorHistory bounds retention and restores an unfinished draft.
func TestLineEditorHistory(t *testing.T) {
	e := newLineEditor(20, 2)
	for _, value := range []string{"one", "one", " ", "two", "three"} {
		typeEditor(e, value)
		e.submit()
	}
	if len(e.history) != 2 || e.history[0] != "two" || e.history[1] != "three" {
		t.Fatalf("history=%v", e.history)
	}
	typeEditor(e, "draft")
	e.recall(false)
	e.recall(true)
	if string(e.text) != "three" {
		t.Fatal(string(e.text))
	}
	e.recall(true)
	e.recall(true)
	if string(e.text) != "two" {
		t.Fatal(string(e.text))
	}
	e.recall(false)
	e.recall(false)
	if string(e.text) != "draft" || e.cursor != 5 || e.bytes != 5 {
		t.Fatalf("editor=%+v", e)
	}
	e.reset()
	if len(e.text) != 0 || e.draft != "" || e.position != 2 {
		t.Fatalf("editor=%+v", e)
	}
}

// TestLineEditorControls rejects terminal controls and invalid Unicode.
func TestLineEditorControls(t *testing.T) {
	e := newLineEditor(10, 0)
	for _, r := range []rune{'\n', '\r', '\t', 27, -1, 0x110000} {
		e.insert(r)
	}
	typeEditor(e, "ok")
	got, bad := e.submit()
	if got != "ok" || bad || len(e.history) != 0 {
		t.Fatalf("%q %v %+v", got, bad, e)
	}
	empty := newLineEditor(-1, -1)
	empty.insert('x')
	if got, bad := empty.submit(); got != "" || !bad {
		t.Fatalf("%q %v", got, bad)
	}
}

// TestLineEditorOverflowHistory preserves rejection across history replacement.
func TestLineEditorOverflowHistory(t *testing.T) {
	e := newLineEditor(4, 1)
	typeEditor(e, "ok")
	e.submit()
	typeEditor(e, "long")
	e.recall(true)
	e.recall(false)
	if got, bad := e.submit(); got != "" || !bad {
		t.Fatalf("%q %v", got, bad)
	}
}
