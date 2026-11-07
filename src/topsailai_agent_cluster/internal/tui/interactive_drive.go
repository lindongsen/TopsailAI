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

// interactiveDrive dispatches the drive action for the selected session.
// status is a read projection of the persisted inventory and never admits a
// command; start and stop are mutating and require explicit confirmation.
func interactiveDrive(parent context.Context, api InteractiveAPI, state *interactiveState, rest string, lines <-chan lineReadResult, out, trustedOut io.Writer, options InteractiveOptions) error {
	if err := rejectInteractiveOption("drive", rest); err != nil {
		return err
	}
	action := strings.ToLower(strings.TrimSpace(rest))
	if action == "" {
		action = "status"
	}
	operation, known := driveActions[action]
	if !known {
		return fmt.Errorf("usage: drive [start|stop|status]")
	}
	if operation == "" {
		return interactiveDriveStatus(parent, api, state, out)
	}
	ctx, cancel := commandContext(parent)
	if err := state.requireUsable(); err != nil {
		cancel()
		return err
	}
	_, _, session, err := findSelected(ctx, api, state)
	cancel()
	if err != nil {
		return err
	}
	// The confirmation text names the controller explicitly, because stopping a
	// driver is not stopping the agent and the operator must not confuse them.
	label := "drive " + action
	return interactiveConfirmedAction(parent, api, state, operation, label, session.SessionID, session.Generation, json.RawMessage(`{}`), lines, out, trustedOut, options, nil, nil)
}

// interactiveDriveStatus reports the standard drive state of the selected
// session from the persisted inventory, so the operator sees the same freshness
// the Server holds instead of an implied live probe.
func interactiveDriveStatus(parent context.Context, api InteractiveAPI, state *interactiveState, out io.Writer) error {
	ctx, cancel := commandContext(parent)
	defer cancel()
	if err := state.requireUsable(); err != nil {
		return err
	}
	_, _, session, err := findSelected(ctx, api, state)
	if err != nil {
		return err
	}
	return (CommandRunner{API: api, Policy: InteractivePolicy}).DriveStatus(ctx, out, state.EndpointID, session.SessionID, false)
}
