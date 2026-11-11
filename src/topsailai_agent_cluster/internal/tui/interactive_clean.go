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
		return fmt.Errorf("usage: clean <session>")
	}
	ctx, cancel := commandContext(parent)
	target, err := resolveCleanTarget(ctx, api, state, token)
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
		_, err := validateCleanTarget(revalidateCtx, api, target.endpointID, target.sessionID, target.generation)
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

// resolveCleanTarget resolves an operator token without requiring a live process
// generation. Cleanup addresses the provider's exact session/PID artifact owner,
// so an expired row whose process is gone remains a valid target.
func resolveCleanTarget(ctx context.Context, api InteractiveAPI, state *interactiveState, token string) (sessionTarget, error) {
	var row SessionRow
	var resolved bool
	var err error
	if state.Scope.Kind == ScopeEndpoint {
		row, resolved, err = resolveReadSessionTokenInEndpoint(state, token, state.Scope.EndpointID)
	} else {
		row, resolved, err = resolveReadSessionToken(state, token)
	}
	if err != nil {
		return sessionTarget{}, err
	}
	if resolved {
		if row.ClusterSessionID == "" {
			return sessionTarget{}, fmt.Errorf("row %d does not identify a session; choose a session row", row.No)
		}
		return validateCleanTarget(ctx, api, row.EndpointID, row.ClusterSessionID, row.ProviderGeneration)
	}
	if state.Scope.Kind == ScopeEndpoint {
		return resolveCleanTargetInEndpoint(ctx, api, state.Scope.EndpointID, token)
	}
	return resolveCleanTargetAcrossEndpoints(ctx, api, token)
}

// resolveCleanTargetInEndpoint resolves one literal session identifier inside the
// selected endpoint while preserving generationless expired rows.
func resolveCleanTargetInEndpoint(ctx context.Context, api InteractiveAPI, endpointID, token string) (sessionTarget, error) {
	loaded, err := loadReports(ctx, api, endpointID)
	if err != nil {
		return sessionTarget{}, err
	}
	_, _, session, err := findSessionInEndpoint(loaded, endpointID, token)
	if err != nil {
		return sessionTarget{}, numericTokenHint(token, err)
	}
	return cleanTargetFromLoaded(loaded, endpointID, session.ClusterSessionID, session.ProviderGeneration)
}

// resolveCleanTargetAcrossEndpoints resolves one literal session identifier in
// workspace scope and refuses a match that is ambiguous across endpoints.
func resolveCleanTargetAcrossEndpoints(ctx context.Context, api InteractiveAPI, token string) (sessionTarget, error) {
	loaded, err := loadReports(ctx, api, "")
	if err != nil {
		return sessionTarget{}, err
	}
	matches := make([]sessionTarget, 0, 1)
	unavailable := make([]string, 0, 1)
	ambiguous := make([]error, 0, 1)
	for _, endpoint := range loaded.endpoints {
		report, ok := loaded.reports[endpoint.EndpointID]
		if !ok || !report.ReportComplete {
			unavailable = append(unavailable, endpoint.EndpointID)
			continue
		}
		_, _, session, findErr := findSessionInEndpoint(loaded, endpoint.EndpointID, token)
		if findErr == nil {
			matches = append(matches, sessionTarget{endpointID: endpoint.EndpointID, sessionID: session.ClusterSessionID, providerSessionID: session.ProviderSessionID, displayName: session.ProviderDisplayName, generation: session.ProviderGeneration})
			continue
		}
		if strings.Contains(findErr.Error(), "multiple sessions match") {
			ambiguous = append(ambiguous, findErr)
		}
	}
	if len(ambiguous) > 0 {
		return sessionTarget{}, ambiguous[0]
	}
	switch len(matches) {
	case 1:
		return cleanTargetFromLoaded(loaded, matches[0].endpointID, matches[0].sessionID, matches[0].generation)
	case 0:
		if len(unavailable) > 0 {
			return sessionTarget{}, numericTokenHint(token, unavailableInventoryError(unavailable))
		}
		return sessionTarget{}, numericTokenHint(token, fmt.Errorf("session %q was not found on any endpoint", token))
	default:
		return sessionTarget{}, fmt.Errorf("multiple sessions match %q; use clean <number> with a row from list", token)
	}
}

// validateCleanTarget reloads current inventory and proves the selected endpoint,
// session row, freshness, and generation still match before confirmation dispatch.
func validateCleanTarget(ctx context.Context, api InteractiveAPI, endpointID, sessionID, generation string) (sessionTarget, error) {
	loaded, err := loadReports(ctx, api, endpointID)
	if err != nil {
		return sessionTarget{}, err
	}
	return cleanTargetFromLoaded(loaded, endpointID, sessionID, generation)
}

// cleanTargetFromLoaded applies the normal endpoint and freshness checks while
// allowing an empty generation. A non-empty generation must still match, so a
// replacement process can never inherit an older row's cleanup confirmation.
func cleanTargetFromLoaded(loaded reportLoad, endpointID, sessionID, expectedGeneration string) (sessionTarget, error) {
	endpoint, found := endpointByID(loaded, endpointID)
	if !found {
		return sessionTarget{}, fmt.Errorf("endpoint %q was not found; run list again", endpointID)
	}
	if err := validateEndpointOnline(endpoint); err != nil {
		return sessionTarget{}, err
	}
	report, ok := loaded.reports[endpointID]
	if !ok || !report.ReportComplete {
		return sessionTarget{}, fmt.Errorf("endpoint %q inventory is unavailable", endpointID)
	}
	for _, session := range report.Sessions {
		if session.ClusterSessionID != sessionID {
			continue
		}
		if err := validateSessionFreshness(report, session); err != nil {
			return sessionTarget{}, err
		}
		if err := validateAdapterFreshness(report, session.AdapterID); err != nil {
			return sessionTarget{}, err
		}
		if expectedGeneration != "" && session.ProviderGeneration != expectedGeneration {
			return sessionTarget{}, fmt.Errorf("session %s generation changed; run list again", sessionIdentityLabel(session.ProviderDisplayName, session.ProviderSessionID, sessionID))
		}
		return sessionTarget{endpointID: endpointID, sessionID: sessionID, providerSessionID: session.ProviderSessionID, displayName: session.ProviderDisplayName, generation: session.ProviderGeneration}, nil
	}
	return sessionTarget{}, fmt.Errorf("session %q was not found on endpoint %q; run list again", sessionID, endpointID)
}
