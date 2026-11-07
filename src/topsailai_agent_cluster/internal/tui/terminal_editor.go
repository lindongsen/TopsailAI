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
}

// NewTerminalEditor injects terminal operations at the CLI boundary.
func NewTerminalEditor(input TerminalInput, output io.Writer, width func() int, enable func() (func() error, error)) *TerminalEditor {
	return &TerminalEditor{input: input, output: output, width: width, enable: enable}
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
	defer t.editor.reset()
	// Only question-style prompts request a new row; named prompts are already printed.
	if strings.HasPrefix(prompt, "\n") {
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
			return t.redraw(prompt)
		}
	}
	reader := bufio.NewReaderSize(byteReader, 16)
	for {
		if err = t.redraw(prompt); err != nil {
			return
		}
		byteReader.escapeDeadline = time.Time{}
		key, keyErr := readLineKey(reader)
		if keyErr != nil {
			if _, writeErr := io.WriteString(t.output, "\r\n"); writeErr != nil {
				keyErr = errors.Join(keyErr, writeErr)
			}
			return "", false, keyErr
		}
		// Any decoded key ends the loop before it is applied, so the operator's
		// next action always runs against a table that has stopped moving.
		if watch != nil {
			watch.Stop()
			watch = nil
			if _, err = io.WriteString(t.output, "auto-refresh stopped\r\n"); err != nil {
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
			_, err = io.WriteString(t.output, "\r\n")
			return
		case lineEditInterrupt:
			_, writeErr := io.WriteString(t.output, "^C\r\n")
			return "", false, errors.Join(ErrInteractiveInterrupt, writeErr)
		case lineEditEOF:
			_, writeErr := io.WriteString(t.output, "\r\n")
			return "", false, joinTerminalError(io.EOF, writeErr)
		}
	}
}

// clearPromptLine erases the prompt row before a refresh is printed, so the
// table never overwrites the operator's partially typed input.
const clearPromptLine = "\r\x1b[2K"

// applyWatch prints one pending refresh between keypresses. The prompt row is
// cleared first, so the table never overwrites the operator's input line.
func (t *TerminalEditor) applyWatch(watch WatchSession) error {
	payload, err := watch.Idle()
	if err != nil {
		return err
	}
	if len(payload) == 0 {
		return nil
	}
	if _, err := io.WriteString(t.output, clearPromptLine); err != nil {
		return err
	}
	_, err = t.output.Write(toCRLF(payload))
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

// redraw uses horizontal scrolling with a reserved final column to prevent wrapping.
func (t *TerminalEditor) redraw(prompt string) error {
	width := t.width()
	if width < 4 {
		width = 4
	}
	green := strings.HasPrefix(prompt, ansiBoldGreen) && strings.HasSuffix(prompt, ansiReset+" ")
	if green {
		prompt = strings.TrimSuffix(strings.TrimPrefix(prompt, ansiBoldGreen), ansiReset+" ") + " "
	}
	prompt = clipCell(prompt, max(1, width/2))
	promptWidth := displayWidth(prompt)
	budget := width - promptWidth - 1
	text, cursor := t.editor.viewport(budget)
	if green {
		prompt = ansiBoldGreen + prompt + ansiReset
	}
	_, err := fmt.Fprintf(t.output, "\r\x1b[2K%s%s\r\x1b[%dC", prompt, text, promptWidth+cursor)
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
