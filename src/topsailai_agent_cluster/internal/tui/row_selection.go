package tui

import "fmt"

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
	if row.SessionID == "" {
		return SessionRow{}, fmt.Errorf("row %d does not identify a session; choose a session row", number)
	}
	if row.Generation == "" {
		return SessionRow{}, fmt.Errorf("row %d has no generation; run list again", number)
	}
	return row, nil
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
