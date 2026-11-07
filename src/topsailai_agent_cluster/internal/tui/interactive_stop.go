package tui

import (
	"context"
	"encoding/json"
	"fmt"
	"io"
	"strings"

	"topsailai_agent_cluster/internal/protocol"
)

// stopTarget is the exact endpoint-scoped session identity a stop request names.
// The endpoint is carried explicitly because workspace scope has no current
// endpoint, so the target cannot be derived from the navigation scope. The
// provider session identifier is carried so the confirmation question can name
// the row the operator selected instead of only the opaque cluster resource ID.
type stopTarget struct {
	endpointID        string
	sessionID         string
	providerSessionID string
	generation        string
}

// confirmationTarget names this stop target for the confirmation question.
func (t stopTarget) confirmationTarget() confirmationTarget {
	return confirmationTarget{ProviderSessionID: t.providerSessionID, SessionID: t.sessionID}
}

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
	target, err := resolveStopTarget(ctx, api, state, token)
	cancel()
	if err != nil {
		return err
	}
	payload := json.RawMessage(`{}`)
	if state.Scope.Kind == ScopeSession {
		postSubmit := func(postCtx context.Context, result map[string]any) error {
			return reconcileStoppedSelection(postCtx, api, state, target.sessionID, out)
		}
		return interactiveConfirmedAction(parent, api, state, protocol.OperationAgentStop, "stop", target.confirmationTarget(), target.generation, payload, lines, out, trustedOut, options, nil, postSubmit)
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
		_, err := validateStopTarget(revalidateCtx, api, target.endpointID, target.sessionID, target.generation)
		return err
	}
	postSubmit := func(postCtx context.Context, result map[string]any) error {
		// The shared confirmation path records the command ID on the detached copy,
		// so copy it back before the caller can query status on the real state.
		state.commandID = pinned.commandID
		return invalidateStopRowBindings(state, out)
	}
	return interactiveConfirmedAction(parent, api, &pinned, protocol.OperationAgentStop, "stop", target.confirmationTarget(), target.generation, payload, lines, out, trustedOut, options, revalidate, postSubmit)
}

// resolveStopTarget maps the operator argument to one exact session identity.
// Every rejection happens before the confirmation prompt, so the operator is never
// asked to confirm a target that the current inventory cannot prove.
func resolveStopTarget(ctx context.Context, api InteractiveAPI, state *interactiveState, token string) (stopTarget, error) {
	if token == "" {
		if state.Scope.Kind != ScopeSession {
			return stopTarget{}, fmt.Errorf("stop requires a session in %s scope; use stop <number> for a session row", state.Scope.Kind)
		}
		_, _, session, err := findSelected(ctx, api, state)
		if err != nil {
			return stopTarget{}, err
		}
		return stopTarget{endpointID: state.EndpointID, sessionID: session.SessionID, providerSessionID: session.ProviderSessionID, generation: session.Generation}, nil
	}
	var row SessionRow
	var resolved bool
	var err error
	if state.Scope.Kind == ScopeEndpoint {
		row, resolved, err = resolveSessionTokenInEndpoint(state, token, state.Scope.EndpointID)
	} else {
		row, resolved, err = resolveSessionToken(state, token)
	}
	if err != nil {
		return stopTarget{}, err
	}
	if resolved {
		return validateStopTarget(ctx, api, row.EndpointID, row.SessionID, row.Generation)
	}
	if state.Scope.Kind == ScopeEndpoint {
		return resolveStopTargetInEndpoint(ctx, api, state.Scope.EndpointID, token)
	}
	return resolveStopTargetAcrossEndpoints(ctx, api, token)
}

// resolveStopTargetInEndpoint resolves a literal session identifier inside one endpoint.
func resolveStopTargetInEndpoint(ctx context.Context, api InteractiveAPI, endpointID, token string) (stopTarget, error) {
	loaded, err := loadReports(ctx, api, endpointID)
	if err != nil {
		return stopTarget{}, err
	}
	_, _, session, err := findSessionInEndpoint(loaded, endpointID, token)
	if err != nil {
		return stopTarget{}, numericTokenHint(token, err)
	}
	return stopTargetFromLoaded(loaded, endpointID, session.SessionID, session.Generation)
}

// resolveStopTargetAcrossEndpoints resolves a literal session identifier in workspace
// scope. A token that matches sessions on several endpoints is rejected instead of
// being silently retargeted, because the operator named no endpoint.
func resolveStopTargetAcrossEndpoints(ctx context.Context, api InteractiveAPI, token string) (stopTarget, error) {
	loaded, err := loadReports(ctx, api, "")
	if err != nil {
		return stopTarget{}, err
	}
	matches := make([]stopTarget, 0, 1)
	unavailable := make([]string, 0, 1)
	for _, endpoint := range loaded.endpoints {
		report, ok := loaded.reports[endpoint.EndpointID]
		if !ok || !report.ReportComplete {
			// An incomplete enumeration cannot prove absence, so remember it and fail
			// closed instead of reporting the token as missing on every endpoint.
			unavailable = append(unavailable, endpoint.EndpointID)
			continue
		}
		if _, _, session, findErr := findSessionInEndpoint(loaded, endpoint.EndpointID, token); findErr == nil {
			matches = append(matches, stopTarget{endpointID: endpoint.EndpointID, sessionID: session.SessionID, generation: session.Generation})
		}
	}
	switch len(matches) {
	case 1:
		return validateStopTarget(ctx, api, matches[0].endpointID, matches[0].sessionID, matches[0].generation)
	case 0:
		if len(unavailable) > 0 {
			return stopTarget{}, numericTokenHint(token, unavailableInventoryError(unavailable))
		}
		return stopTarget{}, numericTokenHint(token, fmt.Errorf("session %q was not found on any endpoint", token))
	default:
		return stopTarget{}, fmt.Errorf("multiple sessions match %q; use stop <number> with a row from list", token)
	}
}

// unavailableInventoryError names the endpoints whose inventory could not prove
// absence, so a partial enumeration is never presented as a proven miss.
func unavailableInventoryError(endpointIDs []string) error {
	if len(endpointIDs) == 1 {
		return fmt.Errorf("endpoint %q inventory is unavailable", endpointIDs[0])
	}
	return fmt.Errorf("endpoint inventories are unavailable: %s", strings.Join(endpointIDs, ", "))
}

// validateStopTarget proves from a fresh inventory that the named session is still
// the exact generation the operator selected, so a replacement is never stopped.
func validateStopTarget(ctx context.Context, api InteractiveAPI, endpointID, sessionID, generation string) (stopTarget, error) {
	loaded, err := loadReports(ctx, api, endpointID)
	if err != nil {
		return stopTarget{}, err
	}
	return stopTargetFromLoaded(loaded, endpointID, sessionID, generation)
}

// stopTargetFromLoaded applies the stop authority checks to an already loaded
// inventory. An empty expected generation skips the comparison, because the caller
// has just read that generation from this same inventory.
func stopTargetFromLoaded(loaded reportLoad, endpointID, sessionID, expectedGeneration string) (stopTarget, error) {
	endpoint, found := endpointByID(loaded, endpointID)
	if !found {
		return stopTarget{}, fmt.Errorf("endpoint %q was not found; run list again", endpointID)
	}
	if err := validateEndpointOnline(endpoint); err != nil {
		return stopTarget{}, err
	}
	report, ok := loaded.reports[endpointID]
	if !ok || !report.ReportComplete {
		return stopTarget{}, fmt.Errorf("endpoint %q inventory is unavailable", endpointID)
	}
	for _, session := range report.Sessions {
		if session.SessionID != sessionID {
			continue
		}
		if err := validateSessionFreshness(report, session); err != nil {
			return stopTarget{}, err
		}
		if err := validateAdapterFreshness(report, session.AdapterID); err != nil {
			return stopTarget{}, err
		}
		if session.Generation == "" {
			return stopTarget{}, fmt.Errorf("session %q has no generation; run list again", sessionID)
		}
		if expectedGeneration != "" && session.Generation != expectedGeneration {
			return stopTarget{}, fmt.Errorf("session %q generation changed; run list again", sessionID)
		}
		return stopTarget{endpointID: endpointID, sessionID: sessionID, providerSessionID: session.ProviderSessionID, generation: session.Generation}, nil
	}
	return stopTarget{}, fmt.Errorf("session %q was not found on endpoint %q; run list again", sessionID, endpointID)
}

// invalidateStopRowBindings drops the row numbers rendered before the stop, because
// the stopped session may no longer be reported and a stale number would name a
// different session after the next list.
func invalidateStopRowBindings(state *interactiveState, out io.Writer) error {
	state.Rows = nil
	_, err := fmt.Fprintln(out, "row numbers are stale after stop; run list to refresh")
	return err
}
