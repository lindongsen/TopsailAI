package tui

import (
	"context"
	"encoding/json"
	"fmt"
	"io"
	"strconv"
	"strings"
	"unicode/utf8"

	"topsailai_agent_cluster/internal/protocol"
)

// LaunchQuerier retrieves live adapter-owned launch choices without inventory authority.
type LaunchQuerier interface {
	GetLaunchOptions(context.Context, string, string) (protocol.LaunchOptions, error)
}

// launchAnswer reads literal, history-free input with explicit cancellation.
func launchAnswer(ctx context.Context, lines <-chan lineReadResult, out io.Writer, field string) (string, error) {
	prompt := "start." + field + "> "
	if _, err := io.WriteString(out, prompt); err != nil {
		return "", &startPromptTermination{kind: startPromptFatal, cause: err}
	}
	line, err := readStartAnswer(ctx, lines, prompt)
	if err != nil {
		return "", err
	}
	if strings.TrimSpace(line) == "" || line == "cancel" {
		_, err := fmt.Fprintln(out, "start cancelled")
		return "", err
	}
	return line, nil
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
	if endpointID == "" {
		endpointID, err = launchAnswer(ctx, lines, out, "endpoint")
		if err != nil || endpointID == "" {
			return err
		}
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
		answer, err := launchAnswer(ctx, lines, out, "adapter")
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
	folder, err := launchAnswer(ctx, lines, out, "folder")
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
	task, err := launchAnswer(ctx, lines, out, "task")
	if err != nil || task == "" {
		return err
	}
	if !utf8.ValidString(task) || strings.ContainsRune(task, 0) {
		return fmt.Errorf("task must be UTF-8 without NUL")
	}
	if len(task) > protocol.MaxInitialTaskBytes {
		return fmt.Errorf("task exceeds maximum bytes")
	}
	payload, err := json.Marshal(map[string]string{"task": task})
	if err != nil {
		return err
	}
	if err := ctx.Err(); err != nil {
		return err
	}
	return interactiveStart(ctx, api, state, interactiveStartRequest{EndpointID: endpointID, Profile: selected.AdapterID, ProfileRevision: selected.Revision, Folder: folder, Payload: payload}, out, options)
}
