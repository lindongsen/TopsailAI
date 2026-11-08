package tui

import (
	"bufio"
	"context"
	"errors"
	"fmt"
	"io"
	"strings"

	"topsailai_agent_cluster/internal/protocol"
)

const (
	// MultiLineTerminator ends a multi-line block when it is the entire line.
	// The provider rejects a standalone EOF line inside a message body, so the
	// terminator can never be legitimate content and is never part of the text.
	MultiLineTerminator = "EOF"
	// MultiLineLimit bounds one accumulated block body in bytes. The provider
	// documents a 1 MiB UTF-8 message bound, so a block cannot exceed it.
	MultiLineLimit = 1 << 20
	// MultiLineHint tells the operator how to finish a multi-line message block.
	MultiLineHint = "Enter message; finish with a standalone EOF line or Ctrl+D"
	// MultiLineTaskHint tells the operator how to finish a multi-line task block.
	MultiLineTaskHint = "Enter task; finish with a standalone EOF line or Ctrl+D"
	// MultiLineContextHint tells the operator how to finish a multi-line context block.
	MultiLineContextHint = "Enter context; finish with a standalone EOF line or Ctrl+D"
	// TaskEchoHeader labels the verbatim echo of an accepted multi-line task.
	TaskEchoHeader = "task:"
	// multiLinePrompt is the continuation prompt of an interactive message block.
	multiLinePrompt = "send> "
	// taskMultiLinePrompt is the continuation prompt of an interactive task block.
	taskMultiLinePrompt = "task> "
	// contextMultiLinePrompt is the continuation prompt of an interactive context block.
	contextMultiLinePrompt = "context> "
	// defaultLineLimit is the per-line bound used when a caller supplies none.
	defaultLineLimit = 8192
)

// multiLineForm carries the surface-specific hint, continuation prompt, body
// bound and body noun of one multi-line block, so the message, task and context
// forms stay distinguishable and each reports its own limit.
type multiLineForm struct {
	hint   string
	prompt string
	limit  int
	noun   string
}

// messageMultiLineForm is the multi-line message form used by send.
var messageMultiLineForm = multiLineForm{hint: MultiLineHint, prompt: multiLinePrompt, limit: MultiLineLimit, noun: "message"}

// taskMultiLineForm is the multi-line task form used by start. The task payload
// bound is smaller than the message bound, so the block fails early with the
// task limit instead of failing later during payload validation.
var taskMultiLineForm = multiLineForm{hint: MultiLineTaskHint, prompt: taskMultiLinePrompt, limit: protocol.MaxInitialTaskBytes, noun: "task"}

// contextMultiLineForm is the multi-line context form used by btw
// alias. Context injection carries the same message payload as send, so it keeps
// the message bound and reports its own noun.
var contextMultiLineForm = multiLineForm{hint: MultiLineContextHint, prompt: contextMultiLinePrompt, limit: MultiLineLimit, noun: "context"}

var (
	// errMultiLineEmpty rejects a block that carries no usable text.
	errMultiLineEmpty = errors.New("payload must not be empty")
	// errMultiLineLineTooLong rejects one physical line above the line bound.
	errMultiLineLineTooLong = errors.New("input line exceeds the maximum length")
)

// MultiLineBlock is one completed multi-line input block.
type MultiLineBlock struct {
	// Text is the joined body without the terminator line.
	Text string
	// Lines is the number of content lines that formed Text.
	Lines int
}

// ReadMultiLineBlock reads one message block from reader until a standalone
// terminator line or the end of input. It is the non-interactive entry point;
// the interactive REPL supplies its own line source instead.
func ReadMultiLineBlock(reader io.Reader, limit int) (MultiLineBlock, error) {
	return readMultiLineBlockFrom(reader, limit, messageMultiLineForm)
}

// ReadTaskMultiLineBlock reads one task block from reader until a standalone
// terminator line or the end of input. The block is bounded by the task payload
// limit, so an oversized task fails here instead of during payload validation.
func ReadTaskMultiLineBlock(reader io.Reader, limit int) (MultiLineBlock, error) {
	return readMultiLineBlockFrom(reader, limit, taskMultiLineForm)
}

// ReadContextMultiLineBlock reads one context block from reader until a
// standalone terminator line or the end of input. Context injection carries the
// same message payload as send, so the block keeps the message bound.
func ReadContextMultiLineBlock(reader io.Reader, limit int) (MultiLineBlock, error) {
	return readMultiLineBlockFrom(reader, limit, contextMultiLineForm)
}

// readMultiLineBlockFrom reads one block of the given form from reader.
func readMultiLineBlockFrom(reader io.Reader, limit int, form multiLineForm) (MultiLineBlock, error) {
	if reader == nil {
		return MultiLineBlock{}, errors.New("multi-line input requires a readable stream")
	}
	buffered := bufio.NewReaderSize(reader, 4096)
	next := func() (lineReadResult, bool) {
		line, overflow, err := readLine(buffered, lineLimitOrDefault(limit))
		return lineReadResult{line: line, overflow: overflow, err: err}, true
	}
	return readMultiLineBlockForm(next, form.limit, form)
}

// readMultiLineBlock consumes lines from next until a standalone terminator line
// or the end of input. The terminator is never part of the returned text.
func readMultiLineBlock(next func() (lineReadResult, bool), limit int) (MultiLineBlock, error) {
	return readMultiLineBlockForm(next, limit, messageMultiLineForm)
}

// readMultiLineBlockForm consumes lines from next until a standalone terminator
// line or the end of input. The terminator is never part of the returned text,
// and an oversized body is reported with the form's own noun and bound.
func readMultiLineBlockForm(next func() (lineReadResult, bool), limit int, form multiLineForm) (MultiLineBlock, error) {
	if limit <= 0 {
		limit = form.limit
	}
	var body strings.Builder
	lines := 0
	for {
		result, ok := next()
		if !ok {
			return finishMultiLineBlock(body.String(), lines)
		}
		if result.err != nil && !errors.Is(result.err, io.EOF) {
			return MultiLineBlock{}, result.err
		}
		if result.overflow {
			return MultiLineBlock{}, errMultiLineLineTooLong
		}
		line := strings.TrimSuffix(result.line, "\r")
		// The end of input carries no content of its own, so it must not append
		// an empty line to the body.
		atEnd := errors.Is(result.err, io.EOF)
		if line != MultiLineTerminator && !(atEnd && line == "") {
			if lines > 0 {
				body.WriteByte('\n')
			}
			body.WriteString(line)
			lines++
			if body.Len() > limit {
				return MultiLineBlock{}, fmt.Errorf("%s exceeds the maximum length of %d bytes", form.noun, limit)
			}
		}
		// A terminator line and the end of input both finish the block; a line
		// that arrived together with the end of input is still content.
		if line == MultiLineTerminator || atEnd {
			return finishMultiLineBlock(body.String(), lines)
		}
	}
}

// finishMultiLineBlock rejects an empty block instead of submitting nothing.
func finishMultiLineBlock(text string, lines int) (MultiLineBlock, error) {
	if strings.TrimSpace(text) == "" {
		return MultiLineBlock{}, errMultiLineEmpty
	}
	return MultiLineBlock{Text: text, Lines: lines}, nil
}

// lineLimitOrDefault applies the shared per-line bound to an unset limit.
func lineLimitOrDefault(limit int) int {
	if limit <= 0 {
		return defaultLineLimit
	}
	return limit
}

// readInteractiveMultiLine reads one message block from the REPL line source.
func readInteractiveMultiLine(ctx context.Context, source <-chan lineReadResult, out io.Writer, options InteractiveOptions) (MultiLineBlock, error) {
	return readInteractiveMultiLineForm(ctx, source, out, options, messageMultiLineForm)
}

// readInteractiveTaskMultiLine reads one task block from the REPL line source.
func readInteractiveTaskMultiLine(ctx context.Context, source <-chan lineReadResult, out io.Writer, options InteractiveOptions) (MultiLineBlock, error) {
	return readInteractiveMultiLineForm(ctx, source, out, options, taskMultiLineForm)
}

// readInteractiveContextMultiLine reads one context block from the REPL line
// source. It is used by btw when no text is supplied.
func readInteractiveContextMultiLine(ctx context.Context, source <-chan lineReadResult, out io.Writer, options InteractiveOptions) (MultiLineBlock, error) {
	return readInteractiveMultiLineForm(ctx, source, out, options, contextMultiLineForm)
}

// readInteractiveMultiLineForm reads one block of the given form from the REPL
// line source. Ctrl+D ends the block instead of ending the session, so this read
// never records a prompt failure; the block reports its own errors.
func readInteractiveMultiLineForm(ctx context.Context, source <-chan lineReadResult, out io.Writer, options InteractiveOptions, form multiLineForm) (MultiLineBlock, error) {
	read := promptReader(ctx)
	if read == nil && source == nil {
		return MultiLineBlock{}, errors.New("multi-line input is unavailable")
	}
	if _, err := fmt.Fprintln(out, form.hint); err != nil {
		return MultiLineBlock{}, err
	}
	limit := lineLimitOrDefault(options.LineLimit)
	next := func() (lineReadResult, bool) {
		if read != nil {
			line, overflow, err := read(ctx, form.prompt, false, limit)
			return lineReadResult{line: line, overflow: overflow, err: err}, true
		}
		select {
		case <-ctx.Done():
			return lineReadResult{err: ctx.Err()}, true
		case result, ok := <-source:
			return result, ok
		}
	}
	return readMultiLineBlockForm(next, form.limit, form)
}

// writeMultiLineEcho prints one accepted multi-line body verbatim so the operator
// can verify exactly what will be sent. The body keeps its own line breaks,
// indentation and spacing, but every line is sanitized first because it is
// operator-supplied text: terminal escape sequences are stripped and control
// characters become a replacement rune. The header and the body are written
// through the trusted writer, because the safe writer strips the styling.
func writeMultiLineEcho(out io.Writer, header, text string, policy ColorPolicy) error {
	if err := writeStyled(out, ansiBoldCyan, header, policy); err != nil {
		return err
	}
	if _, err := io.WriteString(out, "\n"); err != nil {
		return err
	}
	for _, line := range strings.Split(text, "\n") {
		if err := writeStyled(out, ansiGreen, sanitizeTerminal([]byte(line)), policy); err != nil {
			return err
		}
		if _, err := io.WriteString(out, "\n"); err != nil {
			return err
		}
	}
	return nil
}

// WriteTaskEcho prints one accepted multi-line task verbatim with colour, so a
// caller outside this package can show exactly what will be sent.
func WriteTaskEcho(out io.Writer, text string, policy ColorPolicy) error {
	return writeMultiLineEcho(out, TaskEchoHeader, text, policy)
}
