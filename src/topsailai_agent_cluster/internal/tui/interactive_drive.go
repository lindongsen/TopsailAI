package tui

import (
	"context"
	"encoding/json"
	"fmt"
	"io"
	"strings"

	"topsailai_agent_cluster/internal/protocol"
)

// driveActions maps the accepted interactive spellings onto the standard
// operation. An empty action is a read, so a bare drive never mutates anything.
var driveActions = map[string]string{
	"start":  protocol.OperationAgentDriveStart,
	"stop":   protocol.OperationAgentDriveStop,
	"status": "",
}

// interactiveDrive dispatches the drive action for one session.
//
// The grammar is "drive [start|stop|status] [session]". The first token is an action
// only when it names one, so "drive 3" and "drive res_abc" are the documented
// "drive [number-or-session-id]" form and report the controller state. Session scope
// keeps its pinned selection and rejects a target, because the scope already names it.
// status is a read projection of the persisted inventory and never admits a command;
// start and stop are mutating and require explicit confirmation.
func interactiveDrive(parent context.Context, api InteractiveAPI, state *interactiveState, rest string, lines <-chan lineReadResult, out, trustedOut io.Writer, options InteractiveOptions) error {
	if err := rejectInteractiveOption("drive", rest); err != nil {
		return err
	}
	action, token, err := parseDriveArguments(rest)
	if err != nil {
		return err
	}
	if token != "" && state.Scope.Kind == ScopeSession {
		// Session scope already names its target; an argument would be ambiguous.
		return fmt.Errorf("usage: drive [start|stop|status]")
	}
	operation := driveActions[action]
	if operation == "" {
		return interactiveDriveStatus(parent, api, state, token, out)
	}
	ctx, cancel := commandContext(parent)
	target, err := resolveSessionTarget(ctx, api, state, "drive", token)
	cancel()
	if err != nil {
		return err
	}
	// The confirmation text names the controller explicitly, because stopping a
	// driver is not stopping the agent and the operator must not confuse them.
	label := "drive " + action
	if state.Scope.Kind == ScopeSession {
		return interactiveConfirmedAction(parent, api, state, operation, label, target.confirmationTarget(), target.generation, json.RawMessage(`{}`), lines, out, trustedOut, options, nil, nil)
	}
	// Outside session scope the pinned selection is not the target, so the shared
	// confirmation path receives a detached copy that pins exactly this target.
	pinned := *state
	pinned.EndpointID = target.endpointID
	pinned.SessionID = target.sessionID
	pinned.Generation = target.generation
	pinned.Invalidated = false
	pinned.InvalidReason = ""
	revalidate := func(revalidateCtx context.Context) error {
		_, err := validateSessionTarget(revalidateCtx, api, target.endpointID, target.sessionID, target.generation)
		return err
	}
	postSubmit := func(postCtx context.Context, result map[string]any) error {
		// The shared confirmation path records the command ID on the detached copy,
		// so copy it back before the caller can query status on the real state.
		state.commandID = pinned.commandID
		return nil
	}
	return interactiveConfirmedAction(parent, api, &pinned, operation, label, target.confirmationTarget(), target.generation, json.RawMessage(`{}`), lines, out, trustedOut, options, revalidate, postSubmit)
}

// parseDriveArguments splits the optional action from the optional session target.
// A first token that is not an action is the target, so the documented
// "drive [number-or-session-id]" form needs no action word. An omitted action is a
// read, which keeps a bare drive non-mutating.
func parseDriveArguments(rest string) (string, string, error) {
	fields := strings.Fields(rest)
	action := "status"
	token := ""
	if len(fields) > 0 {
		if _, known := driveActions[strings.ToLower(fields[0])]; known {
			action = strings.ToLower(fields[0])
			fields = fields[1:]
		}
	}
	switch len(fields) {
	case 0:
	case 1:
		token = fields[0]
	default:
		return "", "", fmt.Errorf("usage: drive [start|stop|status] [session]")
	}
	return action, token, nil
}

// interactiveDriveStatus reports the standard drive state of one session from the
// persisted inventory, so the operator sees the same freshness the Server holds
// instead of an implied live probe. An empty token means the current scope already
// names the session, which only session scope does.
func interactiveDriveStatus(parent context.Context, api InteractiveAPI, state *interactiveState, token string, out io.Writer) error {
	ctx, cancel := commandContext(parent)
	defer cancel()
	target, err := resolveSessionTarget(ctx, api, state, "drive", token)
	if err != nil {
		return err
	}
	return (CommandRunner{API: api, Policy: InteractivePolicy}).DriveStatus(ctx, out, target.endpointID, target.sessionID, false)
}
