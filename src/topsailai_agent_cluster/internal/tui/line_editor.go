package tui

import (
	"strings"
	"unicode"
	"unicode/utf8"
)

// lineEditor owns bounded editable text; it never touches terminal or global state.
type lineEditor struct {
	text         []rune
	cursor       int
	bytes        int
	limit        int
	overflow     bool
	history      []string
	historyLimit int
	position     int
	draft        string
}

// newLineEditor reserves one byte for the newline used by the input contract.
func newLineEditor(limit, historyLimit int) *lineEditor {
	if limit < 1 {
		limit = 1
	}
	if historyLimit < 0 {
		historyLimit = 0
	}
	return &lineEditor{limit: limit - 1, historyLimit: historyLimit}
}

// insert rejects controls and permanently marks this line on byte overflow.
func (e *lineEditor) insert(r rune) {
	if !utf8.ValidRune(r) || unicode.IsControl(r) {
		return
	}
	n := utf8.RuneLen(r)
	if e.bytes+n > e.limit {
		e.overflow = true
		return
	}
	e.text = append(e.text, 0)
	copy(e.text[e.cursor+1:], e.text[e.cursor:])
	e.text[e.cursor] = r
	e.cursor++
	e.bytes += n
}

// move clamps a relative cursor movement to valid rune boundaries.
func (e *lineEditor) move(delta int) {
	if delta < -e.cursor {
		e.cursor = 0
		return
	}
	if delta > len(e.text)-e.cursor {
		e.cursor = len(e.text)
		return
	}
	e.cursor += delta
}

// erase removes the rune under the cursor or immediately before it.
func (e *lineEditor) erase(backward bool) {
	if backward {
		if e.cursor == 0 {
			return
		}
		e.cursor--
	}
	if e.cursor == len(e.text) {
		return
	}
	e.bytes -= utf8.RuneLen(e.text[e.cursor])
	copy(e.text[e.cursor:], e.text[e.cursor+1:])
	e.text = e.text[:len(e.text)-1]
}

// recall navigates history while preserving the unfinished current draft.
func (e *lineEditor) recall(previous bool) {
	if previous {
		if e.position == 0 {
			return
		}
		if e.position == len(e.history) {
			e.draft = string(e.text)
		}
		e.position--
	} else {
		if e.position == len(e.history) {
			return
		}
		e.position++
	}
	value := e.draft
	if e.position < len(e.history) {
		value = e.history[e.position]
	}
	e.text = []rune(value)
	e.cursor = len(e.text)
	e.bytes = len(value)
}

// submit returns no executable text on overflow and resets the editable line.
func (e *lineEditor) submit() (string, bool) {
	value, rejected := string(e.text), e.overflow
	if rejected {
		value = ""
	}
	if !rejected && strings.TrimSpace(value) != "" && e.historyLimit > 0 {
		e.remember(value)
	}
	e.reset()
	return value, rejected
}

// remember bounds retained history and avoids consecutive duplicates.
func (e *lineEditor) remember(value string) {
	if len(e.history) > 0 && e.history[len(e.history)-1] == value {
		return
	}
	if len(e.history) == e.historyLimit {
		copy(e.history, e.history[1:])
		e.history = e.history[:len(e.history)-1]
	}
	e.history = append(e.history, value)
}

// reset discards drafts and overflow without discarding accepted history.
func (e *lineEditor) reset() {
	e.text = nil
	e.cursor = 0
	e.bytes = 0
	e.overflow = false
	e.position = len(e.history)
	e.draft = ""
}
