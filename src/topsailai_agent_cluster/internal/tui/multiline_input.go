package tui

import (
	"bufio"
	"context"
	"errors"
	"fmt"
	"io"
	"strings"
)

const (
	// MultiLineTerminator ends a multi-line block when it is the entire line.
	// The provider rejects a standalone EOF line inside a message body, so the
	// terminator can never be legitimate content and is never part of the text.
	MultiLineTerminator = "EOF"
	// MultiLineLimit bounds one accumulated block body in bytes. The provider
	// documents a 1 MiB UTF-8 message bound, so a block cannot exceed it.
	MultiLineLimit = 1 << 20
	// MultiLineHint tells the operator how to finish a multi-line block.
	MultiLineHint = "Enter message; finish with a standalone EOF line or Ctrl+D"
	// multiLinePrompt is the continuation prompt of an interactive block.
	multiLinePrompt = "send> "
	// defaultLineLimit is the per-line bound used when a caller supplies none.
	defaultLineLimit = 8192
)

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

// ReadMultiLineBlock reads one block from reader until a standalone terminator
// line or the end of input. It is the non-interactive entry point; the
// interactive REPL supplies its own line source instead.
func ReadMultiLineBlock(reader io.Reader, limit int) (MultiLineBlock, error) {
	if reader == nil {
		return MultiLineBlock{}, errors.New("multi-line input requires a readable stream")
	}
	buffered := bufio.NewReaderSize(reader, 4096)
	next := func() (lineReadResult, bool) {
		line, overflow, err := readLine(buffered, lineLimitOrDefault(limit))
		return lineReadResult{line: line, overflow: overflow, err: err}, true
	}
	return readMultiLineBlock(next, MultiLineLimit)
}

// readMultiLineBlock consumes lines from next until a standalone terminator line
// or the end of input. The terminator is never part of the returned text.
func readMultiLineBlock(next func() (lineReadResult, bool), limit int) (MultiLineBlock, error) {
	if limit <= 0 {
		limit = MultiLineLimit
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
				return MultiLineBlock{}, fmt.Errorf("message exceeds the maximum length of %d bytes", limit)
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

// readInteractiveMultiLine reads one block from the REPL line source. Ctrl+D
// ends the block instead of ending the session, so this read never records a
// prompt failure; the block reports its own errors.
func readInteractiveMultiLine(ctx context.Context, source <-chan lineReadResult, out io.Writer, options InteractiveOptions) (MultiLineBlock, error) {
	read := promptReader(ctx)
	if read == nil && source == nil {
		return MultiLineBlock{}, errors.New("multi-line input is unavailable")
	}
	if _, err := fmt.Fprintln(out, MultiLineHint); err != nil {
		return MultiLineBlock{}, err
	}
	limit := lineLimitOrDefault(options.LineLimit)
	next := func() (lineReadResult, bool) {
		if read != nil {
			line, overflow, err := read(ctx, multiLinePrompt, false, limit)
			return lineReadResult{line: line, overflow: overflow, err: err}, true
		}
		select {
		case <-ctx.Done():
			return lineReadResult{err: ctx.Err()}, true
		case result, ok := <-source:
			return result, ok
		}
	}
	return readMultiLineBlock(next, MultiLineLimit)
}
