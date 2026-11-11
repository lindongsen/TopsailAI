package tui

import (
	"context"
	"io"
	"time"
)

// InteractiveLineReader reads only after a prompt is written; answers are not history.
// Implementations must honor cancellation and reject partial text on errors.
// A prompt beginning with "\n" is a question row: the implementation must end the
// current row before drawing it, because the caller has already written the row
// above and relies on that break instead of writing a second one.
type InteractiveLineReader func(context.Context, string, bool, int) (string, bool, error)

// EchoReader is the optional reader seam that appends the echo of an accepted
// answer to the answer row itself. It is a separate interface because
// InteractiveLineReader is a function value and cannot be type asserted, and
// because a reader without it must still report the echo instead of dropping it.
//
// Only a terminal editor can append in-row: it owns the row the answer was typed
// on. A reader that cannot do that keeps the plain read, and the echo is written
// on its own line instead.
type EchoReader interface {
	ReadLineWithEcho(context.Context, string, bool, int, func(string) string) (string, bool, error)
}

type promptReaderKey struct{}
type promptReaderConfig struct {
	read  InteractiveLineReader
	echo  EchoReader
	limit int
	color ColorPolicy
	// echoOut receives the echo when the reader cannot append it in-row, so a
	// piped or TERM=dumb session still reports what a bare number selected.
	echoOut io.Writer
	failure *error
	// recoverable is set by a caller whose prompt read failure only cancels the
	// current operation instead of ending the session.
	recoverable *bool
}

// promptReader obtains the explicitly injected reader without global state.
func promptReader(ctx context.Context) InteractiveLineReader {
	config, _ := ctx.Value(promptReaderKey{}).(promptReaderConfig)
	return config.read
}

// markRecoverablePromptFailure declares that a failure of the next prompt read cancels
// only the current operation. Wizard prompts keep the default fatal classification.
func markRecoverablePromptFailure(ctx context.Context) {
	config, ok := ctx.Value(promptReaderKey{}).(promptReaderConfig)
	if ok && config.recoverable != nil {
		*config.recoverable = true
	}
}

// readPromptLine requests a history-free child answer after its question is written.
// The default answer prompt is styled with the same policy as the REPL prompt, so the
// child question is never the only unstyled prompt in the session. A caller-supplied
// named prompt is styled the same way, because every prompt that waits for operator
// input must carry colour; a question row and an already styled prompt keep their own
// renderer's styling instead of being wrapped twice.
func readPromptLine(ctx context.Context, prompts ...string) (string, bool, error) {
	config := ctx.Value(promptReaderKey{}).(promptReaderConfig)
	prompt := RenderAnswerPrompt(config.color)
	if len(prompts) > 0 {
		prompt = styleNamedPrompt(prompts[0], config.color)
	}
	line, overflow, err := config.read(ctx, prompt, false, config.limit)
	if err != nil && config.failure != nil {
		*config.failure = err
	}
	return line, overflow, err
}

// readPromptLineWithEcho reads one guided answer and reports the label of the
// accepted choice on the answer row itself.
//
// The echo is produced by the caller, because only the caller knows which row a
// bare number selected, and it is written by the reader, because only the reader
// still owns the answer row when the answer is accepted. A reader that cannot
// append in-row keeps the plain read and the echo is written on its own line, so
// a piped or TERM=dumb session still reports what the answer selected instead of
// silently dropping the confirmation.
//
// A cancelled, empty or failed answer echoes nothing, because no choice was
// accepted and an echo would claim one was.
func readPromptLineWithEcho(ctx context.Context, echo func(string) string, prompts ...string) (string, bool, error) {
	config := ctx.Value(promptReaderKey{}).(promptReaderConfig)
	prompt := RenderAnswerPrompt(config.color)
	if len(prompts) > 0 {
		prompt = styleNamedPrompt(prompts[0], config.color)
	}
	var line string
	var overflow bool
	var err error
	if config.echo != nil {
		line, overflow, err = config.echo.ReadLineWithEcho(ctx, prompt, false, config.limit, echo)
	} else {
		line, overflow, err = config.read(ctx, prompt, false, config.limit)
		if err == nil && !overflow && line != "" && echo != nil {
			if writeErr := writeAnswerEchoFallback(config.echoOut, echo(line)); writeErr != nil {
				err = writeErr
			}
		}
	}
	if err != nil && config.failure != nil {
		*config.failure = err
	}
	return line, overflow, err
}

// writeAnswerEchoFallback writes an echo on its own line for a reader that cannot
// append it to the answer row. A nil writer keeps the read silent, so a caller
// that supplied no output boundary loses nothing.
func writeAnswerEchoFallback(out io.Writer, suffix string) error {
	if out == nil || suffix == "" {
		return nil
	}
	_, err := io.WriteString(out, suffix+"\n")
	return err
}

// nextPromptLineWithEcho preserves the stream fallback and reports the accepted
// choice beside the answer, so a guided selection outside the start wizard gets
// the same echo as one inside it. A reader seam appends the echo to the answer
// row; the stream fallback has no row to append to, so the echo is written on its
// own line through echoOut instead of being dropped. A nil echo keeps the plain
// read, so every existing caller is unchanged.
func nextPromptLineWithEcho(ctx context.Context, source <-chan lineReadResult, echoOut io.Writer, echo func(string) string, prompts ...string) (lineReadResult, bool) {
	if promptReader(ctx) != nil {
		line, overflow, err := readPromptLineWithEcho(ctx, echo, prompts...)
		return lineReadResult{line: line, overflow: overflow, err: err}, true
	}
	select {
	case <-ctx.Done():
		return lineReadResult{err: ctx.Err()}, true
	case result, ok := <-source:
		if ok && result.err == nil && !result.overflow && result.line != "" && echo != nil {
			if writeErr := writeAnswerEchoFallback(echoOut, echo(result.line)); writeErr != nil {
				return lineReadResult{err: writeErr}, true
			}
		}
		return result, ok
	}
}

// nextPromptLine preserves the stream fallback and makes confirmation cancellation observable.
// An optional prompt replaces the default answer prompt, so a caller whose question
// row is itself the input row passes that row instead of printing a second prompt.
func nextPromptLine(ctx context.Context, source <-chan lineReadResult, prompts ...string) (lineReadResult, bool) {
	if promptReader(ctx) != nil {
		line, overflow, err := readPromptLine(ctx, prompts...)
		return lineReadResult{line: line, overflow: overflow, err: err}, true
	}
	select {
	case <-ctx.Done():
		return lineReadResult{err: ctx.Err()}, true
	case result, ok := <-source:
		return result, ok
	}
}

// promptSignalContext lets AfterFunc observe the existing prompt cancellation channel.
type promptSignalContext struct{ done <-chan struct{} }

// Deadline leaves deadline authority with the parent read context.
func (c promptSignalContext) Deadline() (time.Time, bool) { return time.Time{}, false }

// Done exposes the controller-owned signal without creating another watcher.
func (c promptSignalContext) Done() <-chan struct{} { return c.done }

// Err reports cancellation only after the controller signal closes.
func (c promptSignalContext) Err() error {
	select {
	case <-c.done:
		return context.Canceled
	default:
		return nil
	}
}

// Value carries no configuration or authority.
func (c promptSignalContext) Value(any) any { return nil }

// promptContext adapts the existing signal to the standard cancellation API.
func promptContext(done <-chan struct{}) context.Context { return promptSignalContext{done} }
