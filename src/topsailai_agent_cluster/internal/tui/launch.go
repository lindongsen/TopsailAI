package tui

import (
	"context"
	"errors"
	"fmt"
	"io"
	"strconv"
	"strings"

	"topsailai_agent_cluster/internal/protocol"
)

// LaunchQuerier retrieves live adapter-owned launch choices without inventory authority.
type LaunchQuerier interface {
	GetLaunchOptions(context.Context, string, string) (protocol.LaunchOptions, error)
}

// launchAnswerOutcome classifies one project-launch prompt answer.
type launchAnswerOutcome int

const (
	launchAnswerValue launchAnswerOutcome = iota
	launchAnswerCancel
	launchAnswerQuit
	launchAnswerRefresh
)

// errLaunchQuit signals that the operator asked to leave the REPL from a launch prompt.
var errLaunchQuit = errors.New("launch quit")

// errLaunchRefresh signals that the operator asked to refresh from a launch prompt.
var errLaunchRefresh = errors.New("launch refresh")

// classifyLaunchAnswer maps one answer to an outcome and its literal value.
// A quoted control word stays a literal value, matching the legacy start wizard.
func classifyLaunchAnswer(line string) (launchAnswerOutcome, string) {
	trimmed := strings.TrimSpace(line)
	if trimmed == "" || trimmed == "cancel" {
		return launchAnswerCancel, ""
	}
	if isQuotedLaunchAnswer(trimmed) {
		return launchAnswerValue, strings.TrimSuffix(strings.TrimPrefix(trimmed, trimmed[:1]), trimmed[:1])
	}
	switch trimmed {
	case "q", "quit", "exit":
		return launchAnswerQuit, ""
	case "r", "refresh":
		return launchAnswerRefresh, ""
	}
	return launchAnswerValue, line
}

// isQuotedLaunchAnswer reports whether the answer is wrapped in matching quotes.
func isQuotedLaunchAnswer(trimmed string) bool {
	single := strings.HasPrefix(trimmed, "'") && strings.HasSuffix(trimmed, "'")
	double := strings.HasPrefix(trimmed, `"`) && strings.HasSuffix(trimmed, `"`)
	return single || double
}

// launchAnswer reads literal, history-free input with explicit cancellation and control words.
// Help and unavailable-command answers are reported and the same field is asked again.
// The field prompt carries application styling, so it is written through the trusted
// writer; the sanitizing writer would strip the colour and leave this wizard prompt as
// the only unstyled prompt in the session.
func launchAnswer(ctx context.Context, lines <-chan lineReadResult, out, trustedOut io.Writer, state *interactiveState, field string, color ColorPolicy) (string, launchAnswerOutcome, error) {
	prompt := RenderNamedPrompt("start."+field+">", color)
	for {
		if _, err := io.WriteString(trustedOut, prompt); err != nil {
			return "", launchAnswerCancel, &startPromptTermination{kind: startPromptFatal, cause: err}
		}
		line, err := readStartAnswer(ctx, lines, prompt)
		if errors.Is(err, errStartPromptOverflow) {
			if writeErr := writeInteractiveError(out, "start", fmt.Errorf("input line exceeds the maximum length")); writeErr != nil {
				return "", launchAnswerCancel, &startPromptTermination{kind: startPromptFatal, cause: writeErr}
			}
			continue
		}
		if err != nil {
			return "", launchAnswerCancel, err
		}
		outcome, value := classifyLaunchAnswer(line)
		if outcome == launchAnswerCancel {
			if _, writeErr := fmt.Fprintln(out, "start cancelled"); writeErr != nil {
				return "", launchAnswerCancel, &startPromptTermination{kind: startPromptFatal, cause: writeErr}
			}
			return "", launchAnswerCancel, nil
		}
		if outcome != launchAnswerValue {
			return "", outcome, nil
		}
		if handled, handleErr := handleLaunchAnswerControl(out, state, line); handleErr != nil {
			return "", launchAnswerCancel, handleErr
		} else if handled {
			continue
		}
		return value, launchAnswerValue, nil
	}
}

// handleLaunchAnswerControl prints help or rejects a known command without consuming the answer.
func handleLaunchAnswerControl(out io.Writer, state *interactiveState, line string) (bool, error) {
	trimmed := strings.TrimSpace(line)
	if isQuotedLaunchAnswer(trimmed) {
		return false, nil
	}
	switch trimmed {
	case "help", "?", "help start":
		if err := PrintScopedCommandHelp(out, "start", state.Scope.Kind); err != nil {
			return false, &startPromptTermination{kind: startPromptFatal, cause: err}
		}
		return true, nil
	}
	command, _ := splitCommand(trimmed)
	if _, known := commandHelpCatalog[canonicalCommandName(command)]; known {
		if err := writeInteractiveError(out, "start", fmt.Errorf("command unavailable during start input; cancel before running another command")); err != nil {
			return false, &startPromptTermination{kind: startPromptFatal, cause: err}
		}
		return true, nil
	}
	return false, nil
}

// launchAnswerValueOrControl returns the literal value or the REPL control signal.
// A cancelled answer returns an empty value and no error, because it already reported itself.
func launchAnswerValueOrControl(ctx context.Context, lines <-chan lineReadResult, out, trustedOut io.Writer, state *interactiveState, field string, color ColorPolicy) (string, error) {
	value, outcome, err := launchAnswer(ctx, lines, out, trustedOut, state, field, color)
	if err != nil {
		return "", err
	}
	switch outcome {
	case launchAnswerCancel:
		return "", nil
	case launchAnswerQuit:
		return "", errLaunchQuit
	case launchAnswerRefresh:
		return "", errLaunchRefresh
	default:
		return value, nil
	}
}

// launchTaskAnswer reads the initial task of a project launch. An empty answer
// enters multi-line task mode, so a task never has to be squeezed into one line;
// the accepted multi-line body is echoed verbatim with colour so the operator can
// verify exactly what will be sent. The word "cancel" still cancels, because an
// empty answer now means "compose a multi-line task" rather than "abort".
func launchTaskAnswer(ctx context.Context, lines <-chan lineReadResult, out, trustedOut io.Writer, state *interactiveState, options InteractiveOptions) (string, error) {
	prompt := RenderNamedPrompt("start.task>", options.Color)
	for {
		if _, err := io.WriteString(trustedOut, prompt); err != nil {
			return "", &startPromptTermination{kind: startPromptFatal, cause: err}
		}
		line, err := readStartAnswer(ctx, lines, prompt)
		if errors.Is(err, errStartPromptOverflow) {
			if writeErr := writeInteractiveError(out, "start", fmt.Errorf("input line exceeds the maximum length")); writeErr != nil {
				return "", &startPromptTermination{kind: startPromptFatal, cause: writeErr}
			}
			continue
		}
		if err != nil {
			return "", err
		}
		trimmed := strings.TrimSpace(line)
		if trimmed == "cancel" {
			if _, writeErr := fmt.Fprintln(out, "start cancelled"); writeErr != nil {
				return "", &startPromptTermination{kind: startPromptFatal, cause: writeErr}
			}
			return "", nil
		}
		if trimmed == "" {
			return launchMultiLineTask(ctx, lines, out, trustedOut, options)
		}
		outcome, value := classifyLaunchAnswer(line)
		if outcome != launchAnswerValue {
			return "", launchOutcomeSignal(outcome)
		}
		if handled, handleErr := handleLaunchAnswerControl(out, state, line); handleErr != nil {
			return "", handleErr
		} else if handled {
			continue
		}
		return value, nil
	}
}

// launchOutcomeSignal converts a non-value launch outcome into the REPL signal.
func launchOutcomeSignal(outcome launchAnswerOutcome) error {
	switch outcome {
	case launchAnswerQuit:
		return errLaunchQuit
	case launchAnswerRefresh:
		return errLaunchRefresh
	default:
		return nil
	}
}

// launchMultiLineTask reads one multi-line task block and echoes the accepted
// body verbatim. The echo is written through the trusted writer, because the
// safe writer strips the styling the operator asked for.
func launchMultiLineTask(ctx context.Context, lines <-chan lineReadResult, out, trustedOut io.Writer, options InteractiveOptions) (string, error) {
	block, err := readInteractiveTaskMultiLine(ctx, lines, out, options)
	if errors.Is(err, errMultiLineEmpty) {
		return "", fmt.Errorf("task must not be empty; enter a task or cancel")
	}
	if err != nil {
		return "", err
	}
	if err := writeMultiLineEcho(trustedOut, TaskEchoHeader, block.Text, options.Color); err != nil {
		return "", &startPromptTermination{kind: startPromptFatal, cause: err}
	}
	return block.Text, nil
}

// projectLaunch collects a complete draft before submitting exactly one durable start.
// The trusted writer carries the verbatim multi-line task echo, because the safe
// writer strips the styling the operator asked for.
func projectLaunch(ctx context.Context, api InteractiveAPI, query LaunchQuerier, state *interactiveState, rest string, lines <-chan lineReadResult, out, trustedOut io.Writer, options InteractiveOptions) error {
	endpointID := state.Scope.EndpointID
	args, err := splitInteractiveArguments(rest)
	if err != nil || len(args) > 1 {
		return fmt.Errorf("usage: start [endpoint]")
	}
	if len(args) == 1 {
		// An explicit argument is resolved against the inventory, so a hostname or
		// a printed row number works here exactly as it does in the wizard.
		endpointID, err = resolveLaunchEndpointTarget(ctx, api, args[0])
		if err != nil {
			return err
		}
	}
	endpointID, err = resolveLaunchEndpoint(ctx, api, state, endpointID, lines, out, trustedOut, options.Color)
	if err != nil || endpointID == "" {
		return err
	}
	queryCtx, cancel := commandContext(ctx)
	catalog, err := query.GetLaunchOptions(queryCtx, endpointID, "")
	cancel()
	if err != nil {
		return nonSyntaxError{message: fmt.Sprintf("endpoint %q is not reachable: %v", endpointID, err), next: "Run endpoints to check endpoint connectivity, then retry."}
	}
	if catalog.ErrorCode != "" {
		return fmt.Errorf("launch query: %s", catalog.ErrorCode)
	}
	if len(catalog.Handlers) == 0 {
		return fmt.Errorf("endpoint has no project launch handlers")
	}
	selected := catalog.Handlers[0]
	if len(catalog.Handlers) > 1 {
		for index, handler := range catalog.Handlers {
			if _, err := fmt.Fprintf(out, "%d. %s (%s)\n", index+1, handler.DisplayName, handler.AdapterID); err != nil {
				return err
			}
		}
		answer, err := launchAnswerValueOrControl(ctx, lines, out, trustedOut, state, "adapter", options.Color)
		if err != nil || answer == "" {
			return err
		}
		index, err := strconv.Atoi(answer)
		if err != nil || index < 1 || index > len(catalog.Handlers) {
			return fmt.Errorf("invalid adapter selection")
		}
		selected = catalog.Handlers[index-1]
	}
	queryCtx, cancel = commandContext(ctx)
	projects, queryErr := query.GetLaunchOptions(queryCtx, endpointID, selected.AdapterID)
	cancel()
	if queryErr != nil || projects.ErrorCode != "" {
		if _, err := fmt.Fprintln(out, "Project list unavailable; enter a folder manually."); err != nil {
			return err
		}
	} else {
		if len(projects.Handlers) != 1 || projects.Handlers[0].AdapterID != selected.AdapterID || projects.Handlers[0].Revision != selected.Revision {
			return fmt.Errorf("launch handler changed; start again")
		}
		for index, project := range projects.Projects {
			if _, err := fmt.Fprintf(out, "%d. %s (%s)\n", index+1, project.Name, project.Path); err != nil {
				return err
			}
		}
	}
	if _, err := fmt.Fprintln(out, "Choose a project number or enter a folder; empty/cancel cancels."); err != nil {
		return err
	}
	folder, err := launchAnswerValueOrControl(ctx, lines, out, trustedOut, state, "folder", options.Color)
	if err != nil || folder == "" {
		return err
	}
	if index, parseErr := strconv.Atoi(folder); parseErr == nil {
		if queryErr != nil || projects.ErrorCode != "" || index < 1 || index > len(projects.Projects) {
			return fmt.Errorf("invalid project selection; use an explicit folder path")
		}
		folder = projects.Projects[index-1].Path
	}
	if err := protocol.ValidateFolder(folder); err != nil {
		return err
	}
	task, err := launchTaskAnswer(ctx, lines, out, trustedOut, state, options)
	if err != nil || task == "" {
		return err
	}
	payload, err := TaskPayload(task)
	if err != nil {
		return err
	}
	if err := ctx.Err(); err != nil {
		return err
	}
	return interactiveStart(ctx, api, state, interactiveStartRequest{EndpointID: endpointID, Profile: selected.AdapterID, ProfileRevision: selected.Revision, Folder: folder, Payload: payload}, out, trustedOut, options)
}
