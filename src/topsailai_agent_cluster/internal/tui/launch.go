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
func launchAnswer(ctx context.Context, lines <-chan lineReadResult, out io.Writer, state *interactiveState, field string) (string, launchAnswerOutcome, error) {
	prompt := "start." + field + "> "
	for {
		if _, err := io.WriteString(out, prompt); err != nil {
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
func launchAnswerValueOrControl(ctx context.Context, lines <-chan lineReadResult, out io.Writer, state *interactiveState, field string) (string, error) {
	value, outcome, err := launchAnswer(ctx, lines, out, state, field)
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

// projectLaunch collects a complete draft before submitting exactly one durable start.
func projectLaunch(ctx context.Context, api InteractiveAPI, query LaunchQuerier, state *interactiveState, rest string, lines <-chan lineReadResult, out io.Writer, options InteractiveOptions) error {
	endpointID := state.Scope.EndpointID
	args, err := splitInteractiveArguments(rest)
	if err != nil || len(args) > 1 {
		return fmt.Errorf("usage: start [endpoint]")
	}
	if len(args) == 1 {
		endpointID = args[0]
	}
	endpointID, err = resolveLaunchEndpoint(ctx, api, state, endpointID, lines, out)
	if err != nil || endpointID == "" {
		return err
	}
	queryCtx, cancel := commandContext(ctx)
	catalog, err := query.GetLaunchOptions(queryCtx, endpointID, "")
	cancel()
	if err != nil {
		return err
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
		answer, err := launchAnswerValueOrControl(ctx, lines, out, state, "adapter")
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
	folder, err := launchAnswerValueOrControl(ctx, lines, out, state, "folder")
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
	task, err := launchAnswerValueOrControl(ctx, lines, out, state, "task")
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
	return interactiveStart(ctx, api, state, interactiveStartRequest{EndpointID: endpointID, Profile: selected.AdapterID, ProfileRevision: selected.Revision, Folder: folder, Payload: payload}, out, options)
}
