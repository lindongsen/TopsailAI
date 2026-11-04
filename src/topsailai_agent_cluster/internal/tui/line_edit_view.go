package tui

import "strings"

type lineEditOutcome uint8

const (
	lineEditContinue lineEditOutcome = iota
	lineEditSubmit
	lineEditInterrupt
	lineEditEOF
)

// apply maps decoded actions to edits without interpreting command text.
func (e *lineEditor) apply(key lineKey, history bool) lineEditOutcome {
	switch key.kind {
	case lineKeyText:
		e.insert(key.text)
	case lineKeyBackspace:
		e.erase(true)
	case lineKeyDelete:
		e.erase(false)
	case lineKeyLeft:
		e.move(-1)
	case lineKeyRight:
		e.move(1)
	case lineKeyHome:
		e.move(-e.cursor)
	case lineKeyEnd:
		e.move(len(e.text) - e.cursor)
	case lineKeyPrevious:
		if history {
			e.recall(true)
		}
	case lineKeyNext:
		if history {
			e.recall(false)
		}
	case lineKeyEnter:
		return lineEditSubmit
	case lineKeyInterrupt:
		return lineEditInterrupt
	case lineKeyEOF:
		if len(e.text) == 0 {
			return lineEditEOF
		}
		e.erase(false)
	}
	return lineEditContinue
}

// finish excludes wizard and confirmation answers from accepted history.
func (e *lineEditor) finish(history bool) (string, bool) {
	if history {
		return e.submit()
	}
	value, rejected := string(e.text), e.overflow
	e.reset()
	if rejected {
		value = ""
	}
	return value, rejected
}

// viewport returns safe single-row text and a cursor column within its budget.
// It horizontally scrolls instead of wrapping long edits into command output.
func (e *lineEditor) viewport(columns int) (string, int) {
	if columns < 1 {
		return "", 0
	}
	start := e.cursor
	used := 0
	for start > 0 {
		width := editRuneWidth(e.text[start-1])
		if used+width >= columns {
			break
		}
		used += width
		start--
	}
	var out strings.Builder
	total := 0
	for _, r := range e.text[start:] {
		width := editRuneWidth(r)
		if total+width > columns {
			break
		}
		if !isSafeTerminalRune(r) {
			r = '�'
		}
		out.WriteRune(r)
		total += width
	}
	return out.String(), used
}

// editRuneWidth matches the existing table display policy for safe terminal text.
func editRuneWidth(r rune) int {
	if !isSafeTerminalRune(r) {
		return 1
	}
	return displayWidth(string(r))
}
