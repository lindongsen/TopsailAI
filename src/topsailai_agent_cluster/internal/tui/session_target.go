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
	displayName       string
	generation        string
}

// confirmationTarget names this target for the confirmation question.
func (t sessionTarget) confirmationTarget() confirmationTarget {
	return confirmationTarget{DisplayName: t.displayName, ProviderSessionID: t.providerSessionID, SessionID: t.sessionID}
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
		return sessionTarget{endpointID: state.EndpointID, sessionID: session.SessionID, providerSessionID: session.ProviderSessionID, displayName: session.DisplayName, generation: session.Generation}, nil
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
		return validateSessionTarget(ctx, api, row.EndpointID, row.SessionID, row.Generation)
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
	return sessionTargetFromLoaded(loaded, endpointID, session.SessionID, session.Generation)
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
	for _, endpoint := range loaded.endpoints {
		report, ok := loaded.reports[endpoint.EndpointID]
		if !ok || !report.ReportComplete {
			// An incomplete enumeration cannot prove absence, so remember it and fail
			// closed instead of reporting the token as missing on every endpoint.
			unavailable = append(unavailable, endpoint.EndpointID)
			continue
		}
		if _, _, session, findErr := findSessionInEndpoint(loaded, endpoint.EndpointID, token); findErr == nil {
			matches = append(matches, sessionTarget{endpointID: endpoint.EndpointID, sessionID: session.SessionID, providerSessionID: session.ProviderSessionID, displayName: session.DisplayName, generation: session.Generation})
		}
	}
	switch len(matches) {
	case 1:
		return validateSessionTarget(ctx, api, matches[0].endpointID, matches[0].sessionID, matches[0].generation)
	case 0:
		if len(unavailable) > 0 {
			return sessionTarget{}, numericTokenHint(token, unavailableInventoryError(unavailable))
		}
		return sessionTarget{}, numericTokenHint(token, fmt.Errorf("session %q was not found on any endpoint", token))
	default:
		return sessionTarget{}, fmt.Errorf("multiple sessions match %q; use %s <number> with a row from list", token, command)
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
		if session.SessionID != sessionID {
			continue
		}
		if err := validateSessionFreshness(report, session); err != nil {
			return sessionTarget{}, err
		}
		if err := validateAdapterFreshness(report, session.AdapterID); err != nil {
			return sessionTarget{}, err
		}
		if session.Generation == "" {
			// A session reported without a generation is present but its liveness
			// was not verified, so it cannot be addressed. Resume is the only
			// operation that does not need a generation, so name it as the
			// recovery step instead of asking for a refresh that cannot help.
			return sessionTarget{}, fmt.Errorf("session %s is unverified on endpoint %q: the session record exists but no process holds it, so it cannot be addressed; use resume to resume it", sessionIdentityLabel(session.DisplayName, session.ProviderSessionID, sessionID), endpointID)
		}
		if expectedGeneration != "" && session.Generation != expectedGeneration {
			return sessionTarget{}, fmt.Errorf("session %s generation changed; run list again", sessionIdentityLabel(session.DisplayName, session.ProviderSessionID, sessionID))
		}
		return sessionTarget{endpointID: endpointID, sessionID: sessionID, providerSessionID: session.ProviderSessionID, displayName: session.DisplayName, generation: session.Generation}, nil
	}
	return sessionTarget{}, fmt.Errorf("session %q was not found on endpoint %q; run list again", sessionID, endpointID)
}
