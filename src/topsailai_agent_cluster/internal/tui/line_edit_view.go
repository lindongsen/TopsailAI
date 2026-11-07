package tui

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

// wrapViewport returns the soft-wrapped rows of the current text together with
// the cursor row and column. The first row carries the prompt, so it has its own
// budget; every continuation row uses the full terminal width. Wrapping keeps the
// head of a long edit visible instead of scrolling it out of view.
func (e *lineEditor) wrapViewport(firstColumns, nextColumns int) ([]string, int, int) {
	if firstColumns < 1 {
		firstColumns = 1
	}
	if nextColumns < 1 {
		nextColumns = 1
	}
	rows := [][]rune{{}}
	budgets := []int{firstColumns}
	row, used := 0, 0
	cursorRow, cursorColumn := 0, 0
	for index, r := range e.text {
		if index == e.cursor {
			cursorRow, cursorColumn = row, used
		}
		// Unsafe runes are dropped, matching sanitizeTerminal, so the rendered
		// block stays byte-identical to the sanitized form of the typed text.
		if !isSafeTerminalRune(r) {
			continue
		}
		width := editRuneWidth(r)
		// A row that already holds text wraps before the rune that would exceed
		// its budget. A rune wider than an empty row is still placed, because
		// dropping it would hide typed text and stall the cursor.
		if used > 0 && used+width > budgets[row] {
			row++
			rows = append(rows, nil)
			budgets = append(budgets, nextColumns)
			used = 0
		}
		rows[row] = append(rows[row], r)
		used += width
	}
	if e.cursor >= len(e.text) {
		cursorRow, cursorColumn = row, used
	}
	text := make([]string, len(rows))
	for index, rowRunes := range rows {
		text[index] = string(rowRunes)
	}
	return text, cursorRow, cursorColumn
}

// editRuneWidth matches the existing table display policy. Unsafe runes never
// reach this function, because wrapViewport drops them before measuring.
func editRuneWidth(r rune) int {
	return displayWidth(string(r))
}
