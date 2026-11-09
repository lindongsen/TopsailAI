package tui

import (
	"context"
	"errors"
	"fmt"
	"io"
	"strings"
)

// startPromptTerminationKind distinguishes normal end-of-input from fatal I/O.
type startPromptTerminationKind int

const (
	startPromptEOF startPromptTerminationKind = iota + 1
	startPromptFatal
)

// startPromptTermination carries the original reader or writer failure.
type startPromptTermination struct {
	kind  startPromptTerminationKind
	cause error
}

func (e *startPromptTermination) Error() string { return e.cause.Error() }
func (e *startPromptTermination) Unwrap() error { return e.cause }

// startPromptOutcome is the private result of one start wizard invocation.
type startPromptOutcome int

const (
	startPromptReady startPromptOutcome = iota
	startPromptCancel
	startPromptQuit
	startPromptRefresh
)

type startDraftField int

const (
	startFieldEndpoint startDraftField = iota
	startFieldResource
	startFieldProfile
	startFieldRevision
)

type startDraft struct {
	request interactiveStartRequest
	missing [4]bool
}

// recordingWriter preserves the first output failure without changing Write behavior.
type startOutputRecorder struct {
	err error
}

func (r *startOutputRecorder) record(err error) {
	if err != nil && r.err == nil {
		r.err = err
	}
}

type recordingWriter struct {
	writer   io.Writer
	recorder *startOutputRecorder
	err      error
}

func (w *recordingWriter) Write(p []byte) (int, error) {
	n, err := w.writer.Write(p)
	if err == nil && n < len(p) {
		err = io.ErrShortWrite
	}
	if err != nil {
		if w.err == nil {
			w.err = err
		}
		if w.recorder != nil {
			w.recorder.record(err)
		}
	}
	return n, err
}

func (w *recordingWriter) Error() error { return w.err }

func newRecordingWriter(writer io.Writer, recorder *startOutputRecorder) *recordingWriter {
	return &recordingWriter{writer: writer, recorder: recorder}
}

func parseInteractiveStartDraft(rest string) (startDraft, error) {
	args, err := splitInteractiveArguments(rest)
	if err != nil {
		return startDraft{}, err
	}
	positionals := 0
	for _, arg := range args {
		if strings.HasPrefix(arg, "--") {
			break
		}
		if arg == "" || strings.HasPrefix(arg, "-") {
			return startDraft{}, fmt.Errorf("start requires endpoint and resource")
		}
		positionals++
		if positionals == 2 {
			break
		}
	}
	request, missing, err := parseInteractiveStartTokens(args, true)
	if err != nil {
		return startDraft{}, err
	}
	draft := startDraft{request: request}
	for field := range draft.missing {
		draft.missing[field] = missing&(1<<field) != 0
	}
	return draft, nil
}

func firstMissingField(draft startDraft) (startDraftField, bool) {
	for field, missing := range draft.missing {
		if missing {
			return startDraftField(field), true
		}
	}
	return 0, false
}

func startFieldName(field startDraftField) string {
	switch field {
	case startFieldEndpoint:
		return "endpoint"
	case startFieldResource:
		return "resource"
	case startFieldProfile:
		return "profile"
	default:
		return "profile-revision"
	}
}

func startFieldDescription(field startDraftField) string {
	descriptions := map[startDraftField]string{
		startFieldEndpoint: "endpoint ID",
		startFieldResource: "compatibility resource identifier",
		startFieldProfile:  "launch profile ID",
		startFieldRevision: "launch profile revision",
	}
	return "start: " + descriptions[field] + " required (" + descriptions[field] + "). cancel/empty: cancel; q: quit; r: refresh; help: guidance; starts immediately when complete."
}

func parseStartAnswer(line string) (string, error) {
	args, err := splitInteractiveArguments(line)
	if err != nil {
		return "", err
	}
	if len(args) != 1 || args[0] == "" {
		return "", fmt.Errorf("start input requires one non-empty value")
	}
	return args[0], nil
}

func setStartField(request *interactiveStartRequest, field startDraftField, value string) {
	switch field {
	case startFieldEndpoint:
		request.EndpointID = value
	case startFieldResource:
		request.ResourceID = value
	case startFieldProfile:
		request.Profile = value
	case startFieldRevision:
		request.ProfileRevision = value
	}
}

func startPromptControl(line string) (startPromptOutcome, bool) {
	switch strings.TrimSpace(line) {
	case "q", "quit", "exit":
		return startPromptQuit, true
	case "r", "refresh":
		return startPromptRefresh, true
	case "help", "?", "help start":
		return startPromptCancel, false
	default:
		return startPromptReady, false
	}
}

// writeStartHelp prints the field description and then the field prompt. The
// description is plain text, so it goes to the sanitizing writer; the prompt
// carries application styling, so it goes to the trusted writer. Writing the
// styled prompt to the sanitizing writer would strip the colour and leave the
// wizard prompt as the only unstyled prompt in the session.
func writeStartHelp(out, trustedOut io.Writer, field startDraftField, state interactiveState, color ColorPolicy) error {
	if _, err := fmt.Fprintln(out, startFieldDescription(field)); err != nil {
		return err
	}
	_, err := io.WriteString(trustedOut, RenderNamedPrompt("start."+startFieldName(field)+">", color))
	return err
}

var errStartPromptOverflow = errors.New("start prompt input overflow")

func readStartAnswer(ctx context.Context, lines <-chan lineReadResult, prompts ...string) (string, error) {
	if lines == nil && promptReader(ctx) == nil {
		return "", &startPromptTermination{kind: startPromptFatal, cause: errors.New("start input is unavailable")}
	}
	if read := promptReader(ctx); read != nil {
		line, overflow, err := readPromptLine(ctx, prompts...)
		if err == io.EOF {
			return "", &startPromptTermination{kind: startPromptEOF, cause: err}
		}
		if err != nil {
			return "", &startPromptTermination{kind: startPromptFatal, cause: err}
		}
		if overflow {
			return "", errStartPromptOverflow
		}
		return line, nil
	}
	select {
	case <-ctx.Done():
		return "", ctx.Err()
	case result, ok := <-lines:
		if !ok || result.err == io.EOF {
			return "", &startPromptTermination{kind: startPromptEOF, cause: io.EOF}
		}
		if result.err != nil {
			return "", &startPromptTermination{kind: startPromptFatal, cause: result.err}
		}
		if result.overflow {
			return "", errStartPromptOverflow
		}
		return strings.TrimSuffix(result.line, "\r"), nil
	}
}

// runStartPrompt asks for each missing field of a start draft. The field prompt
// carries application styling, so it is written through the trusted writer; the
// description and diagnostics stay on the sanitizing writer.
func runStartPrompt(ctx context.Context, state interactiveState, draft startDraft, lines <-chan lineReadResult, out, trustedOut, errOut io.Writer, color ColorPolicy) (startPromptOutcome, interactiveStartRequest, error) {
	if lines == nil && promptReader(ctx) == nil {
		return startPromptCancel, interactiveStartRequest{}, &startPromptTermination{kind: startPromptFatal, cause: errors.New("start input is unavailable")}
	}
	for {
		if err := ctx.Err(); err != nil {
			return startPromptCancel, interactiveStartRequest{}, err
		}
		field, ok := firstMissingField(draft)
		if !ok {
			if err := ctx.Err(); err != nil {
				return startPromptCancel, interactiveStartRequest{}, err
			}
			return startPromptReady, draft.request, nil
		}
		if err := writeStartHelp(out, trustedOut, field, state, color); err != nil {
			return startPromptCancel, interactiveStartRequest{}, &startPromptTermination{kind: startPromptFatal, cause: err}
		}
		line, err := readStartAnswer(ctx, lines, "start."+startFieldName(field)+"> ")
		var termination *startPromptTermination
		if errors.As(err, &termination) && termination.kind == startPromptFatal {
			return startPromptCancel, interactiveStartRequest{}, err
		}
		if parentErr := ctx.Err(); parentErr != nil {
			return startPromptCancel, interactiveStartRequest{}, parentErr
		}
		if errors.Is(err, errStartPromptOverflow) {
			if writeErr := writeInteractiveError(errOut, "start", fmt.Errorf("input line exceeds the maximum length")); writeErr != nil {
				return startPromptCancel, interactiveStartRequest{}, &startPromptTermination{kind: startPromptFatal, cause: writeErr}
			}
			continue
		}
		if err != nil {
			return startPromptCancel, interactiveStartRequest{}, err
		}
		trimmed := strings.TrimSpace(line)
		if trimmed == "" || trimmed == "cancel" {
			if _, writeErr := fmt.Fprintln(out, "start cancelled"); writeErr != nil {
				return startPromptCancel, interactiveStartRequest{}, &startPromptTermination{kind: startPromptFatal, cause: writeErr}
			}
			return startPromptCancel, interactiveStartRequest{}, nil
		}
		controlErr := error(nil)
		quotedControl := (strings.HasPrefix(trimmed, "'") && strings.HasSuffix(trimmed, "'")) || (strings.HasPrefix(trimmed, `"`) && strings.HasSuffix(trimmed, `"`))
		if controlErr == nil && !quotedControl {
			if outcome, control := startPromptControl(trimmed); control {
				if outcome == startPromptQuit || outcome == startPromptRefresh {
					return outcome, interactiveStartRequest{}, nil
				}
			}
		}
		if trimmed == "help" || trimmed == "?" || trimmed == "help start" {
			if err := PrintScopedCommandHelp(out, "start", state.Scope.Kind); err != nil {
				return startPromptCancel, interactiveStartRequest{}, &startPromptTermination{kind: startPromptFatal, cause: err}
			}
			continue
		}
		if !quotedControl {
			command, _ := splitCommand(trimmed)
			if _, known := commandHelpCatalog[canonicalCommandName(command)]; known {
				if writeErr := writeInteractiveError(errOut, "start", fmt.Errorf("command unavailable during start input; cancel before running another command")); writeErr != nil {
					return startPromptCancel, interactiveStartRequest{}, &startPromptTermination{kind: startPromptFatal, cause: writeErr}
				}
				continue
			}
		}
		value, parseErr := parseStartAnswer(line)
		if parseErr != nil || ((field == startFieldEndpoint || field == startFieldResource) && strings.HasPrefix(value, "-")) {
			if parseErr == nil {
				parseErr = fmt.Errorf("start input requires one non-empty value for %s", startFieldName(field))
			}
			if writeErr := writeInteractiveError(errOut, "start", parseErr); writeErr != nil {
				return startPromptCancel, interactiveStartRequest{}, &startPromptTermination{kind: startPromptFatal, cause: writeErr}
			}
			continue
		}
		setStartField(&draft.request, field, value)
		draft.missing[field] = false
	}
}

func startOutputError(commandErr error, recorder *startOutputRecorder, writers ...*recordingWriter) error {
	if recorder != nil && recorder.err != nil {
		return &startPromptTermination{kind: startPromptFatal, cause: recorder.err}
	}
	for _, writer := range writers {
		if writer.Error() != nil {
			return &startPromptTermination{kind: startPromptFatal, cause: writer.Error()}
		}
	}
	return commandErr
}

func unwrapStartTermination(err error) error {
	var termination *startPromptTermination
	if errors.As(err, &termination) && termination.kind == startPromptFatal {
		return termination.cause
	}
	return nil
}

func isStartPromptEOF(err error) bool {
	var termination *startPromptTermination
	return errors.As(err, &termination) && termination.kind == startPromptEOF
}
