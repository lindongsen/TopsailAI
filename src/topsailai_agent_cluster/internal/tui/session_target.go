package tui

import (
	"context"
	"fmt"
	"strings"
)

// sessionTarget is the exact endpoint-scoped session identity a mutating command
// names. The endpoint is carried explicitly because workspace scope has no current
// endpoint, so the target cannot be derived from the navigation scope. The provider
// session identifier and the reported display name are carried so the confirmation
// question can name the row the operator selected instead of only the opaque cluster
// resource ID.
type sessionTarget struct {
	endpointID        string
	sessionID         string
	providerSessionID string
	// providerPID is the provider process identifier the inventory reported for
	// this exact row. It travels beside the provider session identifier because
	// one provider session can own several rows, and a provider that receives only
	// the session identifier must either choose a row or refuse an ambiguous
	// target. A zero value means the inventory reported no process, which is the
	// unverified case rather than a different target.
	providerPID    int64
	providerTarget string
	displayName    string
	generation     string
}

// confirmationTarget names this target for the confirmation question.
func (t sessionTarget) confirmationTarget() confirmationTarget {
	return confirmationTarget{ProviderDisplayName: t.displayName, ProviderSessionID: t.providerSessionID, ClusterSessionID: t.sessionID, ProviderTarget: t.providerTarget}
}

// resolveSessionTarget maps the operator argument to one exact session identity for
// the named command. Every rejection happens before the confirmation prompt, so the
// operator is never asked to confirm a target that the current inventory cannot prove.
//
// An empty token means the current scope already names the target, which only session
// scope does. A non-empty token is resolved from the most recently rendered list row
// first, then as a literal session identifier: endpoint scope stays inside the current
// endpoint, while workspace scope searches every endpoint and rejects an ambiguous
// match instead of silently retargeting it.
func resolveSessionTarget(ctx context.Context, api InteractiveAPI, state *interactiveState, command, token string) (sessionTarget, error) {
	if token == "" {
		if state.Scope.Kind != ScopeSession {
			return sessionTarget{}, fmt.Errorf("%s requires a session in %s scope; use %s <number> for a session row", command, state.Scope.Kind, command)
		}
		_, _, session, err := findSelected(ctx, api, state)
		if err != nil {
			return sessionTarget{}, err
		}
		return sessionTarget{endpointID: state.EndpointID, sessionID: session.ClusterSessionID, providerSessionID: session.ProviderSessionID, providerPID: session.ProviderPID, providerTarget: session.ProviderTarget, displayName: session.ProviderDisplayName, generation: session.ProviderGeneration}, nil
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
		return sessionTarget{}, err
	}
	if resolved {
		return validateSessionTarget(ctx, api, row.EndpointID, row.ClusterSessionID, row.ProviderGeneration)
	}
	if state.Scope.Kind == ScopeEndpoint {
		return resolveSessionTargetInEndpoint(ctx, api, state.Scope.EndpointID, token)
	}
	return resolveSessionTargetAcrossEndpoints(ctx, api, command, token)
}

// resolveSessionTargetInEndpoint resolves a literal session identifier inside one endpoint.
func resolveSessionTargetInEndpoint(ctx context.Context, api InteractiveAPI, endpointID, token string) (sessionTarget, error) {
	loaded, err := loadReports(ctx, api, endpointID)
	if err != nil {
		return sessionTarget{}, err
	}
	_, _, session, err := findSessionInEndpoint(loaded, endpointID, token)
	if err != nil {
		return sessionTarget{}, numericTokenHint(token, err)
	}
	return sessionTargetFromLoaded(loaded, endpointID, session.ClusterSessionID, session.ProviderGeneration)
}

// resolveSessionTargetAcrossEndpoints resolves a literal session identifier in
// workspace scope. A token that matches sessions on several endpoints is rejected
// instead of being silently retargeted, because the operator named no endpoint.
func resolveSessionTargetAcrossEndpoints(ctx context.Context, api InteractiveAPI, command, token string) (sessionTarget, error) {
	loaded, err := loadReports(ctx, api, "")
	if err != nil {
		return sessionTarget{}, err
	}
	matches := make([]sessionTarget, 0, 1)
	unavailable := make([]string, 0, 1)
	degraded := make([]string, 0, 1)
	for _, endpoint := range loaded.endpoints {
		// A degraded endpoint has a known state and a known deletion date, so it is
		// reported as degraded rather than as an inventory that failed to answer.
		// Its inventory is gone by design, which would otherwise be indistinguishable
		// from a transient read failure.
		if endpointDegraded(endpoint) {
			degraded = append(degraded, endpoint.EndpointID)
			continue
		}
		report, ok := loaded.reports[endpoint.EndpointID]
		if !ok || !report.ReportComplete {
			// An incomplete enumeration cannot prove absence, so remember it and fail
			// closed instead of reporting the token as missing on every endpoint.
			unavailable = append(unavailable, endpoint.EndpointID)
			continue
		}
		if _, _, session, findErr := findSessionInEndpoint(loaded, endpoint.EndpointID, token); findErr == nil {
			matches = append(matches, sessionTarget{endpointID: endpoint.EndpointID, sessionID: session.ClusterSessionID, providerSessionID: session.ProviderSessionID, providerPID: session.ProviderPID, providerTarget: session.ProviderTarget, displayName: session.ProviderDisplayName, generation: session.ProviderGeneration})
		}
	}
	switch len(matches) {
	case 1:
		return validateSessionTarget(ctx, api, matches[0].endpointID, matches[0].sessionID, matches[0].generation)
	case 0:
		if len(degraded) > 0 {
			return sessionTarget{}, numericTokenHint(token, degradedEndpointError(degraded))
		}
		if len(unavailable) > 0 {
			return sessionTarget{}, numericTokenHint(token, unavailableInventoryError(unavailable))
		}
		return sessionTarget{}, numericTokenHint(token, fmt.Errorf("session %q was not found on any endpoint", token))
	default:
		return sessionTarget{}, fmt.Errorf("multiple sessions match %q; use %s <number> with a row from list", token, command)
	}
}

// degradedEndpointError names the endpoints that are degraded, so a known state is
// never reported as an inventory that failed to answer.
func degradedEndpointError(endpointIDs []string) error {
	if len(endpointIDs) == 1 {
		return fmt.Errorf("endpoint %q is degraded, so its sessions cannot be listed; re-register the endpoint to use it again", endpointIDs[0])
	}
	return fmt.Errorf("endpoints are degraded, so their sessions cannot be listed: %s; re-register them to use them again", strings.Join(endpointIDs, ", "))
}

// unavailableInventoryError names the endpoints whose inventory could not prove
// absence, so a partial enumeration is never presented as a proven miss.
func unavailableInventoryError(endpointIDs []string) error {
	if len(endpointIDs) == 1 {
		return fmt.Errorf("endpoint %q inventory is unavailable", endpointIDs[0])
	}
	return fmt.Errorf("endpoint inventories are unavailable: %s", strings.Join(endpointIDs, ", "))
}

// validateSessionTarget proves from a fresh inventory that the named session is still
// the exact generation the operator selected, so a replacement is never targeted.
func validateSessionTarget(ctx context.Context, api InteractiveAPI, endpointID, sessionID, generation string) (sessionTarget, error) {
	loaded, err := loadReports(ctx, api, endpointID)
	if err != nil {
		return sessionTarget{}, err
	}
	return sessionTargetFromLoaded(loaded, endpointID, sessionID, generation)
}

// sessionTargetFromLoaded applies the shared authority checks to an already loaded
// inventory. An empty expected generation skips the comparison, because the caller
// has just read that generation from this same inventory.
func sessionTargetFromLoaded(loaded reportLoad, endpointID, sessionID, expectedGeneration string) (sessionTarget, error) {
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
		if session.ProviderGeneration == "" {
			// A session reported without a generation is present but its liveness
			// was not verified, so it cannot be addressed. Resume is the only
			// operation that does not need a generation, so name it as the
			// recovery step instead of asking for a refresh that cannot help.
			return sessionTarget{}, fmt.Errorf("session %s is unverified on endpoint %q: the session record exists but no process holds it, so it cannot be addressed; use resume to resume it", sessionIdentityLabel(session.ProviderDisplayName, session.ProviderSessionID, sessionID), endpointID)
		}
		if expectedGeneration != "" && session.ProviderGeneration != expectedGeneration {
			return sessionTarget{}, fmt.Errorf("session %s generation changed; run list again", sessionIdentityLabel(session.ProviderDisplayName, session.ProviderSessionID, sessionID))
		}
		return sessionTarget{endpointID: endpointID, sessionID: sessionID, providerSessionID: session.ProviderSessionID, providerPID: session.ProviderPID, providerTarget: session.ProviderTarget, displayName: session.ProviderDisplayName, generation: session.ProviderGeneration}, nil
	}
	return sessionTarget{}, fmt.Errorf("session %q was not found on endpoint %q; run list again", sessionID, endpointID)
}

// resolveReadTarget maps an operator token to one exact session identity for a
// command that addresses persisted data rather than a live process.
//
// It is the read counterpart of resolveSessionTarget. The difference is one
// decision: an empty provider generation is accepted, because a generation proves
// which process a mutation would reach, while a read only needs to know which
// record to read. That identity is already proven by the durable resource mapping
// and re-proven by the provider, so requiring a generation here would refuse to
// read exactly the rows an operator most needs to inspect: the ones the provider
// listed but could not prove live.
//
// A non-empty generation must still match, so a replacement process can never
// inherit an older row's identity. Every other check is unchanged: the endpoint
// must be online, the report complete, and the session and its adapter fresh.
func resolveReadTarget(ctx context.Context, api InteractiveAPI, state *interactiveState, command, token string) (sessionTarget, error) {
	if token == "" {
		// An empty token means the current scope already names the target, which only
		// session scope does. The selected session is revalidated through the same
		// selection check every scoped command uses, so a read cannot address a
		// session the scope no longer proves.
		if state.Scope.Kind != ScopeSession {
			return sessionTarget{}, fmt.Errorf("%s requires a session in %s scope; use %s <number> for a session row", command, state.Scope.Kind, command)
		}
		_, _, session, err := findSelected(ctx, api, state)
		if err != nil {
			return sessionTarget{}, err
		}
		return sessionTarget{endpointID: state.EndpointID, sessionID: session.ClusterSessionID, providerSessionID: session.ProviderSessionID, providerPID: session.ProviderPID, providerTarget: session.ProviderTarget, displayName: session.ProviderDisplayName, generation: session.ProviderGeneration}, nil
	}
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
		return validateReadTarget(ctx, api, row.EndpointID, row.ClusterSessionID, row.ProviderGeneration)
	}
	if state.Scope.Kind == ScopeEndpoint {
		return resolveReadTargetInEndpoint(ctx, api, state.Scope.EndpointID, token)
	}
	return resolveReadTargetAcrossEndpoints(ctx, api, command, token)
}

// resolveReadTargetInEndpoint resolves one literal session identifier inside the
// selected endpoint while preserving generationless rows.
func resolveReadTargetInEndpoint(ctx context.Context, api InteractiveAPI, endpointID, token string) (sessionTarget, error) {
	loaded, err := loadReports(ctx, api, endpointID)
	if err != nil {
		return sessionTarget{}, err
	}
	_, _, session, err := findSessionInEndpoint(loaded, endpointID, token)
	if err != nil {
		return sessionTarget{}, numericTokenHint(token, err)
	}
	return readTargetFromLoaded(loaded, endpointID, session.ClusterSessionID, session.ProviderGeneration)
}

// resolveReadTargetAcrossEndpoints resolves one literal session identifier in
// workspace scope and refuses a match that is ambiguous across endpoints.
func resolveReadTargetAcrossEndpoints(ctx context.Context, api InteractiveAPI, command, token string) (sessionTarget, error) {
	loaded, err := loadReports(ctx, api, "")
	if err != nil {
		return sessionTarget{}, err
	}
	matches := make([]sessionTarget, 0, 1)
	unavailable := make([]string, 0, 1)
	degraded := make([]string, 0, 1)
	ambiguous := make([]error, 0, 1)
	for _, endpoint := range loaded.endpoints {
		// A degraded endpoint is reported by its known state, not as an inventory
		// that failed to answer, because its inventory is removed by design.
		if endpointDegraded(endpoint) {
			degraded = append(degraded, endpoint.EndpointID)
			continue
		}
		report, ok := loaded.reports[endpoint.EndpointID]
		if !ok || !report.ReportComplete {
			unavailable = append(unavailable, endpoint.EndpointID)
			continue
		}
		_, _, session, findErr := findSessionInEndpoint(loaded, endpoint.EndpointID, token)
		if findErr == nil {
			matches = append(matches, sessionTarget{endpointID: endpoint.EndpointID, sessionID: session.ClusterSessionID, providerSessionID: session.ProviderSessionID, providerPID: session.ProviderPID, providerTarget: session.ProviderTarget, displayName: session.ProviderDisplayName, generation: session.ProviderGeneration})
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
		return readTargetFromLoaded(loaded, matches[0].endpointID, matches[0].sessionID, matches[0].generation)
	case 0:
		if len(degraded) > 0 {
			return sessionTarget{}, numericTokenHint(token, degradedEndpointError(degraded))
		}
		if len(unavailable) > 0 {
			return sessionTarget{}, numericTokenHint(token, unavailableInventoryError(unavailable))
		}
		return sessionTarget{}, numericTokenHint(token, fmt.Errorf("session %q was not found on any endpoint", token))
	default:
		return sessionTarget{}, fmt.Errorf("multiple sessions match %q; use %s <row> with a row from list", token, command)
	}
}

// validateReadTarget reloads current inventory and proves the selected endpoint,
// session row, freshness and generation still match before a read is dispatched.
func validateReadTarget(ctx context.Context, api InteractiveAPI, endpointID, sessionID, generation string) (sessionTarget, error) {
	loaded, err := loadReports(ctx, api, endpointID)
	if err != nil {
		return sessionTarget{}, err
	}
	return readTargetFromLoaded(loaded, endpointID, sessionID, generation)
}

// readTargetFromLoaded applies the normal endpoint and freshness checks while
// allowing an empty generation. A non-empty generation must still match, so a
// replacement process can never inherit an older row's identity.
func readTargetFromLoaded(loaded reportLoad, endpointID, sessionID, expectedGeneration string) (sessionTarget, error) {
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
		return sessionTarget{endpointID: endpointID, sessionID: sessionID, providerSessionID: session.ProviderSessionID, providerPID: session.ProviderPID, providerTarget: session.ProviderTarget, displayName: session.ProviderDisplayName, generation: session.ProviderGeneration}, nil
	}
	return sessionTarget{}, fmt.Errorf("session %q was not found on endpoint %q; run list again", sessionID, endpointID)
}
