package tui

import (
	"context"
	"encoding/json"
	"fmt"
	"io"
	"strings"

	"topsailai_agent_cluster/internal/protocol"
)

// interactiveStop stops one session selected by the current scope.
// Session scope keeps the pinned selection and accepts no argument. Workspace and
// endpoint scope accept a row number from the most recently rendered list, or a
// session identifier, so a session can be stopped without entering it first.
func interactiveStop(parent context.Context, api InteractiveAPI, state *interactiveState, rest string, lines <-chan lineReadResult, out, trustedOut io.Writer, options InteractiveOptions) error {
	if err := rejectInteractiveOption("stop", rest); err != nil {
		return err
	}
	token := strings.TrimSpace(rest)
	if token != "" && state.Scope.Kind == ScopeSession {
		// Session scope already names its target; an argument would be ambiguous.
		return fmt.Errorf("usage: stop")
	}
	ctx, cancel := commandContext(parent)
	target, err := resolveSessionTarget(ctx, api, state, "stop", token)
	cancel()
	if err != nil {
		return err
	}
	payload := json.RawMessage(`{}`)
	if state.Scope.Kind == ScopeSession {
		postSubmit := func(postCtx context.Context, result map[string]any) error {
			return reconcileStoppedSelection(postCtx, api, state, target.sessionID, out)
		}
		return interactiveConfirmedAction(parent, api, state, protocol.OperationAgentStop, "stop", target.sessionID, target.generation, payload, lines, out, trustedOut, options, nil, postSubmit)
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
		return invalidateStopRowBindings(state, out)
	}
	return interactiveConfirmedAction(parent, api, &pinned, protocol.OperationAgentStop, "stop", target.sessionID, target.generation, payload, lines, out, trustedOut, options, revalidate, postSubmit)
}

// invalidateStopRowBindings drops the row numbers rendered before the stop, because
// the stopped session may no longer be reported and a stale number would name a
// different session after the next list.
func invalidateStopRowBindings(state *interactiveState, out io.Writer) error {
	state.Rows = nil
	_, err := fmt.Fprintln(out, "row numbers are stale after stop; run list to refresh")
	return err
}
