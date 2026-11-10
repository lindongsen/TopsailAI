package tui

import (
	"bufio"
	"context"
	"errors"
	"fmt"
	"io"
	"os"
	"strings"
	"time"
)

// TerminalInput is an owned terminal descriptor supporting cancellable reads.
type TerminalInput interface {
	io.Reader
	SetReadDeadline(time.Time) error
}

// TerminalEditor owns editing history, not the terminal descriptor itself.
// Calls must be serialized by the REPL; enable returns an exact restoration closure.
type TerminalEditor struct {
	input  TerminalInput
	output io.Writer
	width  func() int
	enable func() (func() error, error)
	editor *lineEditor
	// actions supplies the advertised control actions for dotted completion. It
	// reads a cache and never performs network I/O, because completion runs
	// inside the keystroke handler. A nil source completes no action.
	actions func() []string
	// blockRows and blockCursorRow record the input block rendered last time, so
	// the next redraw returns to its first row instead of appending a second copy.
	blockRows      int
	blockCursorRow int
}

// NewTerminalEditor injects terminal operations at the CLI boundary.
func NewTerminalEditor(input TerminalInput, output io.Writer, width func() int, enable func() (func() error, error)) *TerminalEditor {
	return &TerminalEditor{input: input, output: output, width: width, enable: enable}
}

// SetActionSource injects the advertised control actions used by dotted
// completion. The source must read a cache rather than query the Server, because
// it is called from the keystroke handler. A nil source disables action
// completion and leaves command-word completion unchanged.
func (t *TerminalEditor) SetActionSource(actions func() []string) {
	t.actions = actions
}

// The editor is both the plain and the tick-capable reader. These assertions keep
// the two seams satisfied by one type, so a caller cannot wire one without the
// other and silently disable auto-refresh in the shipped binary.
var (
	_ InteractiveLineReader = (*TerminalEditor)(nil).ReadLine
	_ WatchLineReader       = (*TerminalEditor)(nil)
)

// ReadLine restores terminal state on every return and never returns partial text on failure.
func (t *TerminalEditor) ReadLine(ctx context.Context, prompt string, history bool, limit int) (line string, overflow bool, err error) {
	return t.readLine(ctx, prompt, history, limit, nil)
}

// ReadLineWithWatch observes an auto-refresh loop while it waits for a key.
// The first decoded key stops the loop before it is applied, so a moving table
// can never rebind a row number under an operator who has started typing.
func (t *TerminalEditor) ReadLineWithWatch(ctx context.Context, prompt string, history bool, limit int, watch WatchSession) (line string, overflow bool, err error) {
	return t.readLine(ctx, prompt, history, limit, watch)
}

// readLine is the single editing loop; a nil watch keeps the plain behaviour.
func (t *TerminalEditor) readLine(ctx context.Context, prompt string, history bool, limit int, watch WatchSession) (line string, overflow bool, err error) {
	if err = ctx.Err(); err != nil {
		return
	}
	restore, err := t.enable()
	if err != nil {
		return "", false, err
	}
	defer func() {
		restoreErr := errors.Join(restore(), t.input.SetReadDeadline(time.Time{}))
		if restoreErr != nil {
			err = errors.Join(err, restoreErr)
		}
		if err != nil {
			line = ""
		}
	}()
	if t.editor == nil || t.editor.limit != max(1, limit)-1 {
		t.editor = newLineEditor(limit, 100)
	}
	t.editor.reset()
	// A new prompt always starts a new input block, so no stale row count from a
	// previous read can move the cursor on the first redraw.
	t.blockRows, t.blockCursorRow = 0, 0
	defer t.editor.reset()
	// Only question-style prompts request a new row; named prompts are already printed.
	// The marker is captured before it is stripped, because a question row is allowed
	// the whole row width while a named prompt keeps the half-row budget.
	questionRow := strings.HasPrefix(prompt, "\n")
	if questionRow {
		prompt = strings.TrimPrefix(prompt, "\n")
		if _, err = io.WriteString(t.output, "\r\n"); err != nil {
			return
		}
	}
	byteReader := &terminalByteReader{ctx: ctx, input: t.input}
	if watch != nil {
		// The read loop polls with a short deadline, so the tick is observed
		// between polls without a second goroutine writing to the terminal.
		byteReader.idle = func() error {
			if watch == nil {
				return nil
			}
			if err := t.applyWatch(watch); err != nil {
				return err
			}
			return t.redraw(prompt, questionRow)
		}
	}
	reader := bufio.NewReaderSize(byteReader, 16)
	for {
		if err = t.redraw(prompt, questionRow); err != nil {
			return
		}
		byteReader.escapeDeadline = time.Time{}
		key, keyErr := readLineKey(reader)
		if keyErr != nil {
			// An ignorable key carries no editing meaning, so the line is kept
			// and the loop continues. Treating it as a read failure would let a
			// stray control byte destroy the operator's session.
			if errors.Is(keyErr, errIgnoredKey) {
				continue
			}
			if _, writeErr := io.WriteString(t.output, "\r\n"); writeErr != nil {
				keyErr = errors.Join(keyErr, writeErr)
			}
			return "", false, keyErr
		}
		// Any decoded key ends the loop before it is applied, so the operator's
		// next action always runs against a table that has stopped moving.
		if watch != nil {
			label := watchStopLabel(watch, OutputColorPolicy(t.output))
			watch.Stop()
			watch = nil
			if _, err = io.WriteString(t.output, label+"\r\n"); err != nil {
				return
			}
		}
		if key.kind == lineKeyTab {
			if history {
				err = t.completeCommand(prompt)
			}
			if err != nil {
				return
			}
			continue
		}
		switch t.editor.apply(key, history) {
		case lineEditContinue:
		case lineEditSubmit:
			line, overflow = t.editor.finish(history)
			// The cursor leaves from the last row of the block, so the submit
			// newline never splits the operator's input in the middle.
			_, err = io.WriteString(t.output, t.blockEndSequence()+"\r\n")
			return
		case lineEditInterrupt:
			_, writeErr := io.WriteString(t.output, t.blockEndSequence()+"^C\r\n")
			return "", false, errors.Join(ErrInteractiveInterrupt, writeErr)
		case lineEditEOF:
			_, writeErr := io.WriteString(t.output, t.blockEndSequence()+"\r\n")
			return "", false, joinTerminalError(io.EOF, writeErr)
		}
	}
}

// blockEndSequence returns the cursor movement that leaves the rendered input
// block below its last row, and forgets the block so the next prompt starts on a
// fresh row. A block that was never rendered needs no movement.
func (t *TerminalEditor) blockEndSequence() string {
	if t.blockRows == 0 {
		return ""
	}
	down := t.blockRows - 1 - t.blockCursorRow
	t.blockRows, t.blockCursorRow = 0, 0
	if down <= 0 {
		return "\r"
	}
	return fmt.Sprintf("\r\x1b[%dB", down)
}

// defaultInputRows bounds the visible input block when the output boundary
// reports no terminal height, so an unknown height never renders unbounded rows.
const defaultInputRows = 20

// eraseBlock returns the cursor to the first row of the last rendered input
// block and clears every row of it. A block that was never rendered writes
// nothing, so the first redraw of a prompt starts on the current row.
func (t *TerminalEditor) eraseBlock() error {
	if t.blockRows == 0 {
		return nil
	}
	var out strings.Builder
	out.WriteString("\r")
	if t.blockCursorRow > 0 {
		fmt.Fprintf(&out, "\x1b[%dA", t.blockCursorRow)
	}
	for row := 0; row < t.blockRows; row++ {
		out.WriteString("\x1b[2K")
		if row < t.blockRows-1 {
			out.WriteString("\r\n")
		}
	}
	if t.blockRows > 1 {
		fmt.Fprintf(&out, "\x1b[%dA", t.blockRows-1)
	}
	out.WriteString("\r")
	t.blockRows, t.blockCursorRow = 0, 0
	_, err := io.WriteString(t.output, out.String())
	return err
}

// inputRows reports how many rows the input block may occupy. The output
// boundary owns the terminal height, so the editor never probes global state.
func (t *TerminalEditor) inputRows() int {
	if provider, ok := t.output.(interface{ TerminalHeight() int }); ok {
		if height := provider.TerminalHeight(); height > 2 {
			return height - 1
		}
	}
	return defaultInputRows
}

// watchStopLabel names the loop in the stop message. A session that does not
// name itself keeps the auto-refresh wording, so the existing behaviour stays
// byte-identical for every caller that predates follow. A follow session gets
// the shared "log.follow>" prefix, because the operator asked for a way to tell
// these lines apart from agent output; the policy comes from the editor's own
// output boundary, so --no-color and a redirected stream stay plain.
func watchStopLabel(watch WatchSession, policy ColorPolicy) string {
	if labelled, ok := watch.(followStopLabel); ok {
		return renderFollowStatus(labelled.StopLabel(), ansiDim, policy, false)
	}
	return "auto-refresh stopped"
}

// applyWatch prints one pending refresh between keypresses. The whole input
// block is erased first, so the table never overwrites the operator's input.
func (t *TerminalEditor) applyWatch(watch WatchSession) error {
	payload, err := watch.Idle()
	if err != nil {
		return err
	}
	if len(payload) == 0 {
		return nil
	}
	if err := t.eraseBlock(); err != nil {
		return err
	}
	converted := toCRLF(payload)
	if _, err := t.output.Write(converted); err != nil {
		return err
	}
	// The redrawn input block must start on its own row, so a payload that does
	// not end with a newline still leaves the cursor at the beginning of a row.
	if len(converted) == 0 || converted[len(converted)-1] != '\n' {
		_, err = io.WriteString(t.output, "\r\n")
	}
	return err
}

// toCRLF converts bare newlines to CRLF. The terminal is in raw mode, where a
// newline moves down without returning to the first column, so an unconverted
// table would print as a staircase.
func toCRLF(payload []byte) []byte {
	converted := make([]byte, 0, len(payload)+16)
	for index := 0; index < len(payload); index++ {
		if payload[index] == '\n' && (index == 0 || payload[index-1] != '\r') {
			converted = append(converted, '\r')
		}
		converted = append(converted, payload[index])
	}
	return converted
}

// redraw renders the input as a soft-wrapped block, so a long edit keeps its
// head visible instead of scrolling out of a single row. The previous block is
// erased in the same write, so a shorter block never leaves stale rows behind.
// A question row carries the whole question, so it may use the full row instead
// of the half-row budget that keeps a named prompt short; otherwise a long
// question would lose its trailing answer hint.
func (t *TerminalEditor) redraw(prompt string, questionRow bool) error {
	width := t.width()
	if width < 4 {
		width = 4
	}
	green := strings.HasPrefix(prompt, ansiBoldGreen) && strings.HasSuffix(prompt, ansiReset+" ")
	if green {
		prompt = strings.TrimSuffix(strings.TrimPrefix(prompt, ansiBoldGreen), ansiReset+" ") + " "
	}
	budgetWidth := max(1, width/2)
	if questionRow {
		budgetWidth = max(1, width-1)
	}
	// A prompt that carries an answer hint must keep it, because the hint is the
	// only cue telling the operator what to type. That covers a question row and
	// also a named prompt whose name states the accepted answers, such as
	// "send.confirm[y/N]> ". A named prompt without a hint uses the plain clip.
	// Styled prompts are measured and clipped by visible columns, so escape bytes
	// never shift the cursor.
	if questionRow || answerHintIndex(prompt) >= 0 {
		prompt = clipStyledCellKeepHint(prompt, budgetWidth)
	} else {
		prompt = clipStyledCell(prompt, budgetWidth)
	}
	promptWidth := styledDisplayWidth(prompt)
	// The first row shares its width with the prompt; continuation rows use the
	// whole width, and one column stays reserved so a full row never wraps.
	firstBudget := max(1, width-promptWidth-1)
	nextBudget := max(1, width-1)
	rows, cursorRow, cursorColumn := t.editor.wrapViewport(firstBudget, nextBudget)
	// A block taller than the terminal scrolls by whole rows, so the cursor row
	// always stays visible. The first visible row keeps the prompt, because an
	// operator who cannot see the scope prompt cannot tell where input goes.
	start := 0
	if visible := t.inputRows(); len(rows) > visible {
		start = cursorRow - visible + 1
		if start < 0 {
			start = 0
		}
		if start > len(rows)-visible {
			start = len(rows) - visible
		}
	}
	visibleRows := rows[start:]
	if start > 0 {
		// The first visible row is a continuation row whose head scrolled off, so
		// it keeps its tail and marks the hidden part instead of dropping text
		// silently.
		visibleRows = append([]string{clipCellLeft(visibleRows[0], firstBudget)}, visibleRows[1:]...)
	}
	cursorRow -= start
	if green {
		prompt = ansiBoldGreen + prompt + ansiReset
	}
	var out strings.Builder
	// Erase the previous block first, so a block that shrank leaves no stale row.
	out.WriteString("\r")
	if t.blockRows > 0 {
		if t.blockCursorRow > 0 {
			fmt.Fprintf(&out, "\x1b[%dA", t.blockCursorRow)
		}
		out.WriteString("\r")
		for row := 0; row < t.blockRows; row++ {
			out.WriteString("\x1b[2K")
			if row < t.blockRows-1 {
				out.WriteString("\r\n")
			}
		}
		if t.blockRows > 1 {
			fmt.Fprintf(&out, "\x1b[%dA", t.blockRows-1)
		}
		out.WriteString("\r")
	}
	for row, text := range visibleRows {
		if row > 0 {
			out.WriteString("\r\n")
		}
		out.WriteString("\x1b[2K")
		if row == 0 {
			out.WriteString(prompt)
		}
		out.WriteString(text)
	}
	if up := len(visibleRows) - 1 - cursorRow; up > 0 {
		fmt.Fprintf(&out, "\x1b[%dA", up)
	}
	out.WriteString("\r")
	column := cursorColumn
	if cursorRow == 0 {
		column += promptWidth
	}
	if column > 0 {
		fmt.Fprintf(&out, "\x1b[%dC", column)
	}
	t.blockRows, t.blockCursorRow = len(visibleRows), cursorRow
	_, err := io.WriteString(t.output, out.String())
	return err
}

// terminalByteReader prevents read-ahead across prompts and bounds cancellation latency.
type terminalByteReader struct {
	ctx            context.Context
	input          TerminalInput
	escapeDeadline time.Time
	// idle runs between polls, so an auto-refresh loop is observed without a
	// second goroutine writing to the terminal.
	idle func() error
}

// Read polls only terminal deadlines; all other failures retain their identity.
func (r *terminalByteReader) Read(p []byte) (int, error) {
	if len(p) == 0 {
		return 0, nil
	}
	for {
		if err := r.ctx.Err(); err != nil {
			return 0, err
		}
		if !r.escapeDeadline.IsZero() && time.Now().After(r.escapeDeadline) {
			return 0, fmt.Errorf("%w: incomplete escape timeout", errLineKey)
		}
		if err := r.input.SetReadDeadline(time.Now().Add(50 * time.Millisecond)); err != nil {
			return 0, err
		}
		n, err := r.input.Read(p[:1])
		if n > 0 {
			if p[0] == 27 {
				r.escapeDeadline = time.Now().Add(300 * time.Millisecond)
			}
			return n, err
		}
		if errors.Is(err, os.ErrDeadlineExceeded) {
			// A poll timeout is the only idle moment, so it is where a pending
			// refresh is applied. A refresh failure ends the read instead of
			// being swallowed, because the terminal may be unusable.
			if r.idle != nil {
				if idleErr := r.idle(); idleErr != nil {
					return 0, idleErr
				}
			}
			continue
		}
		return n, err
	}
}

// joinTerminalError preserves sentinel equality when no additional failure occurred.
func joinTerminalError(primary, extra error) error {
	if extra == nil {
		return primary
	}
	return errors.Join(primary, extra)
}
