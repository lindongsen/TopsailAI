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
	// recorder persists every submitted input. It is a seam rather than a direct
	// file write, so the editor stays free of filesystem and process state and a
	// test can observe what was recorded without touching a real file.
	recorder InputRecorder
}

// InputRecorder persists one submitted input. The kind distinguishes a command
// line from a prompt answer, because recording and recalling are different
// questions: every input is recorded, but only a command line is recallable.
type InputRecorder interface {
	Record(kind, text string) error
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

// seedHistory replaces the recall list with previously recorded commands, so a
// restarted REPL can recall what an earlier session typed. The list is bounded by
// the same limit as one session's own history, and the position is moved to the
// end so the first Up recalls the newest command.
func (e *lineEditor) seedHistory(commands []string) {
	e.history = e.history[:0]
	for _, command := range commands {
		if strings.TrimSpace(command) == "" {
			continue
		}
		e.remember(command)
	}
	e.position = len(e.history)
	e.draft = ""
}

// setRecorder attaches the persistence seam. A nil recorder keeps the editor
// usable without persistence, so a caller that supplies none loses nothing.
func (e *lineEditor) setRecorder(recorder InputRecorder) {
	e.recorder = recorder
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
// An accepted command line is recorded as a command, so it is recallable in this
// session and available to a later session through the recorder.
func (e *lineEditor) submit() (string, bool) {
	value, rejected := string(e.text), e.overflow
	if rejected {
		value = ""
	}
	if !rejected && strings.TrimSpace(value) != "" && e.historyLimit > 0 {
		e.remember(value)
	}
	if !rejected {
		e.record(InputHistoryKindCommand, value)
	}
	e.reset()
	return value, rejected
}

// record hands one accepted input to the persistence seam. A nil recorder keeps
// the editor usable without persistence, and a rejected input is never recorded
// because it was never accepted. The error is deliberately not propagated: the
// store has already reported it to its diagnostics writer, and a history failure
// must never turn an accepted command into a failed one.
func (e *lineEditor) record(kind, value string) {
	if e.recorder == nil || strings.TrimSpace(value) == "" {
		return
	}
	_ = e.recorder.Record(kind, value)
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
