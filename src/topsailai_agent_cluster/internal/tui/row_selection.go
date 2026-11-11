package tui

import (
	"fmt"

	"topsailai_agent_cluster/internal/protocol"
)

// resolveRowSelection maps a bare ASCII row number to the session row it names.
// Row numbers are the operator-facing shorthand for long provider identifiers, so
// every rejection happens locally: an unusable token must never reach the API.
func resolveRowSelection(state *interactiveState, token string) (SessionRow, error) {
	number, numeric := parseRowNumber(token)
	if !numeric {
		return SessionRow{}, fmt.Errorf("row number exceeds the supported integer range")
	}
	if len(state.Rows) == 0 {
		return SessionRow{}, fmt.Errorf("no list is available for row selection; run list first")
	}
	row, ok := state.Rows[number]
	if !ok {
		return SessionRow{}, fmt.Errorf("row %d is out of range; valid rows are 1-%d", number, len(state.Rows))
	}
	if row.ClusterSessionID == "" {
		return SessionRow{}, fmt.Errorf("row %d does not identify a session; choose a session row", number)
	}
	if row.ProviderGeneration == "" {
		// A row reported without a generation is present but its liveness was not
		// verified, so it cannot be addressed. Naming the real reason keeps the
		// operator from retrying a refresh that cannot change the outcome.
		if row.State == protocol.SessionStateUnknown {
			return SessionRow{}, fmt.Errorf("row %d is unverified: the session record exists but no process holds it, so it cannot be addressed; use resume to resume it", number)
		}
		return SessionRow{}, fmt.Errorf("row %d has no generation; run list again", number)
	}
	return row, nil
}

// resolveReadRowSelection maps a bare ASCII row number to the row it names for a
// read-only command.
//
// This deliberately does not reuse resolveRowSelection, because that helper refuses
// a row whose generation is empty or whose session identity is absent. Those
// refusals exist because cd, send, stop, inject and interrupt address a live
// process, and an empty generation cannot prove which process an operation would
// reach. A read-only command addresses persisted report data instead: a session the
// provider listed but could not prove live is still readable, and an endpoint
// placeholder row still names an endpoint whose detail can be shown. Refusing either
// would hide exactly the rows an operator most wants to inspect, and would leave a
// visible list row with no way to read it.
//
// The row is returned as rendered, so the caller decides what the row can address.
// A row with no session identity is an endpoint row, and a row with no generation is
// an unverified session; both are legitimate read targets.
func resolveReadRowSelection(state *interactiveState, token string) (SessionRow, error) {
	number, numeric := parseRowNumber(token)
	if !numeric {
		return SessionRow{}, fmt.Errorf("row number exceeds the supported integer range")
	}
	if len(state.Rows) == 0 {
		return SessionRow{}, fmt.Errorf("no list is available for row selection; run list first")
	}
	row, ok := state.Rows[number]
	if !ok {
		return SessionRow{}, fmt.Errorf("row %d is out of range; valid rows are 1-%d", number, len(state.Rows))
	}
	return row, nil
}

// resolveReadSessionToken maps an operator token to a row for a read-only command.
//
// A bare row number wins because it is the documented shorthand. A numeric token
// that is not a row number is retried as a provider session identifier, because the
// list displays provider identifiers and they are numeric strings. When no list has
// been rendered the token is left to the identifier path, which resolves it against
// the live inventory. Unlike resolveSessionToken this never rejects a row for being
// unverified or for naming an endpoint, because a read addresses persisted data.
func resolveReadSessionToken(state *interactiveState, token string) (SessionRow, bool, error) {
	if !isASCIIDecimal(token) {
		return SessionRow{}, false, nil
	}
	if len(state.Rows) == 0 {
		return SessionRow{}, false, nil
	}
	row, err := resolveReadRowSelection(state, token)
	if err == nil {
		return row, true, nil
	}
	if match, ok := rowByProviderSessionID(state, token); ok {
		return match, true, nil
	}
	return SessionRow{}, false, err
}

// resolveReadSessionTokenInEndpoint applies resolveReadSessionToken and then enforces
// that the resolved row belongs to the current endpoint. A row rendered for another
// endpoint is rejected instead of being silently retargeted, because the operator
// selected a number from a different table.
func resolveReadSessionTokenInEndpoint(state *interactiveState, token, endpointID string) (SessionRow, bool, error) {
	row, resolved, err := resolveReadSessionToken(state, token)
	if err != nil || !resolved {
		return SessionRow{}, resolved, err
	}
	if row.EndpointID != endpointID {
		return SessionRow{}, false, fmt.Errorf("row %d belongs to endpoint %q, not the current endpoint %q; run list in that endpoint first", row.No, row.EndpointID, endpointID)
	}
	return row, true, nil
}

// resolveRowSelectionInEndpoint resolves a row number that must belong to one endpoint.
// A row rendered for another endpoint is rejected instead of being silently retargeted,
// because the operator selected a number from a different table.
func resolveRowSelectionInEndpoint(state *interactiveState, token, endpointID string) (SessionRow, error) {
	row, err := resolveRowSelection(state, token)
	if err != nil {
		return SessionRow{}, err
	}
	if row.EndpointID != endpointID {
		return SessionRow{}, fmt.Errorf("row %d belongs to endpoint %q, not the current endpoint %q; run list in that endpoint first", row.No, row.EndpointID, endpointID)
	}
	return row, nil
}

// rowByProviderSessionID finds the row whose displayed provider session ID matches
// the token. Provider identifiers are numeric strings, so a token that is not a
// valid row number may still name a session the operator copied from the list.
func rowByProviderSessionID(state *interactiveState, token string) (SessionRow, bool) {
	for _, row := range state.Rows {
		if row.ProviderSessionID != "" && row.ProviderSessionID == token {
			return row, true
		}
	}
	return SessionRow{}, false
}

// resolveSessionToken maps an operator token to a session row. A bare row number
// wins because it is the documented shorthand. A numeric token that is not a row
// number is retried as a provider session identifier, because the list displays
// provider identifiers and they are numeric strings. When no list has been
// rendered the token is left to the identifier path, which resolves it against
// the live inventory.
func resolveSessionToken(state *interactiveState, token string) (SessionRow, bool, error) {
	if !isASCIIDecimal(token) {
		return SessionRow{}, false, nil
	}
	if len(state.Rows) == 0 {
		return SessionRow{}, false, nil
	}
	row, err := resolveRowSelection(state, token)
	if err == nil {
		return row, true, nil
	}
	if match, ok := rowByProviderSessionID(state, token); ok {
		return match, true, nil
	}
	return SessionRow{}, false, err
}

// resolveSessionTokenInEndpoint applies resolveSessionToken and then enforces that
// the resolved row belongs to the current endpoint.
func resolveSessionTokenInEndpoint(state *interactiveState, token, endpointID string) (SessionRow, bool, error) {
	row, resolved, err := resolveSessionToken(state, token)
	if err != nil || !resolved {
		return SessionRow{}, resolved, err
	}
	if row.EndpointID != endpointID {
		return SessionRow{}, false, fmt.Errorf("row %d belongs to endpoint %q, not the current endpoint %q; run list in that endpoint first", row.No, row.EndpointID, endpointID)
	}
	return row, true, nil
}

// numericTokenHint appends the row-selection remedy when a numeric token failed to
// resolve as an identifier. A numeric token may be a provider session identifier
// or a row number from a list that has not been rendered yet, so the failure must
// name both remedies instead of only reporting a missing session.
func numericTokenHint(token string, err error) error {
	if err == nil || !isASCIIDecimal(token) {
		return err
	}
	return fmt.Errorf("%w; run list to select a session by row number", err)
}
