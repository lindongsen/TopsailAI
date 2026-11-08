package tui

import (
	"context"
	"time"
)

// InteractiveLineReader reads only after a prompt is written; answers are not history.
// Implementations must honor cancellation and reject partial text on errors.
// A prompt beginning with "\n" is a question row: the implementation must end the
// current row before drawing it, because the caller has already written the row
// above and relies on that break instead of writing a second one.
type InteractiveLineReader func(context.Context, string, bool, int) (string, bool, error)

type promptReaderKey struct{}
type promptReaderConfig struct {
	read    InteractiveLineReader
	limit   int
	color   ColorPolicy
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
// child question is never the only unstyled prompt in the session.
func readPromptLine(ctx context.Context, prompts ...string) (string, bool, error) {
	config := ctx.Value(promptReaderKey{}).(promptReaderConfig)
	prompt := RenderAnswerPrompt(config.color)
	if len(prompts) > 0 {
		prompt = prompts[0]
	}
	line, overflow, err := config.read(ctx, prompt, false, config.limit)
	if err != nil && config.failure != nil {
		*config.failure = err
	}
	return line, overflow, err
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
