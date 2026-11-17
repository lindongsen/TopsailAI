package tui

import (
	"context"
	"encoding/json"
	"fmt"
	"io"
	"strings"

	"topsailai_agent_cluster/internal/protocol"
)

// interactiveClean removes provider-owned expired artifacts for one exact
// session selected in workspace or endpoint scope.
func interactiveClean(parent context.Context, api InteractiveAPI, state *interactiveState, rest string, lines <-chan lineReadResult, out, trustedOut io.Writer, options InteractiveOptions) error {
	if err := rejectInteractiveOption("clean", rest); err != nil {
		return err
	}
	token := strings.TrimSpace(rest)
	if token == "" {
		return fmt.Errorf("usage: clean <row|session>")
	}
	ctx, cancel := commandContext(parent)
	target, err := resolveReadTarget(ctx, api, state, "clean", token)
	cancel()
	if err != nil {
		return err
	}
	pinned := *state
	pinned.EndpointID = target.endpointID
	pinned.ClusterSessionID = target.sessionID
	pinned.ProviderGeneration = target.generation
	pinned.Invalidated = false
	pinned.InvalidReason = ""
	revalidate := func(revalidateCtx context.Context) error {
		_, err := validateReadTarget(revalidateCtx, api, target.endpointID, target.sessionID, target.generation)
		return err
	}
	postSubmit := func(context.Context, map[string]any) error {
		state.commandID = pinned.commandID
		state.Rows = nil
		_, err := fmt.Fprintln(out, "row numbers are stale after clean; run list to refresh")
		return err
	}
	return interactiveConfirmedAction(parent, api, &pinned, protocol.OperationWorkspaceClean, "clean", target.confirmationTarget(), target.generation, json.RawMessage(`{}`), lines, out, trustedOut, options, revalidate, postSubmit)
}
