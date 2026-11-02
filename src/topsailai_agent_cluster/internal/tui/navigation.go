package tui

import (
	"context"
	"fmt"
	"io"
	"sort"
	"strconv"
	"strings"

	"topsailai_agent_cluster/internal/protocol"
)

// resolveOutcome reports how a navigation target was handled.
type resolveOutcome int

const (
	outcomeResolved resolveOutcome = iota
	outcomeNotFound
	outcomeCancelled
)

// interactiveCD navigates between workspace, endpoint, and session scopes.
func interactiveCD(parent context.Context, api InteractiveAPI, state *interactiveState, rest string, lineSource <-chan lineReadResult, out io.Writer) error {
	target := strings.TrimSpace(rest)
	switch target {
	case "", "/":
		state.enterWorkspace()
		return nil
	case "..":
		return cdParent(state, out)
	}
	parts := strings.Split(target, "/")
	if len(parts) > 3 {
		return fmt.Errorf("usage: cd [target]")
	}
	for _, part := range parts {
		if strings.TrimSpace(part) == "" {
			return fmt.Errorf("usage: cd [target]")
		}
	}
	ctx, cancel := commandContext(parent)
	defer cancel()
	loaded, err := loadReports(ctx, api, "")
	if err != nil {
		return err
	}
	switch len(parts) {
	case 1:
		return cdSingle(state, loaded, parts[0], lineSource, out)
	case 2:
		return cdPair(state, loaded, parts[0], parts[1])
	default:
		return cdTriple(state, loaded, parts[0], parts[1], parts[2])
	}
}

// cdParent moves one level up the scope hierarchy.
func cdParent(state *interactiveState, out io.Writer) error {
	switch state.Scope.Kind {
	case ScopeSession:
		state.enterEndpoint(protocol.Endpoint{EndpointID: state.Scope.EndpointID, Hostname: state.Scope.Hostname})
		return nil
	case ScopeEndpoint:
		state.enterWorkspace()
		return nil
	default:
		_, err := fmt.Fprintln(out, "already at workspace scope")
		return err
	}
}

// cdSingle resolves a bare target, preferring the current endpoint for sessions.
func cdSingle(state *interactiveState, loaded reportLoad, target string, lineSource <-chan lineReadResult, out io.Writer) error {
	var sessionErr error
	if state.Scope.Kind != ScopeWorkspace {
		outcome, err := resolveSessionInEndpoint(state, loaded, state.Scope.EndpointID, target)
		if outcome == outcomeResolved || err != nil {
			return err
		}
		sessionErr = fmt.Errorf("session %q was not found on endpoint %q", target, state.Scope.EndpointID)
	}
	outcome, err := resolveEndpoint(state, loaded, target, lineSource, out)
	if outcome == outcomeResolved || err != nil {
		return err
	}
	if outcome == outcomeCancelled {
		return nil
	}
	if sessionErr != nil {
		return sessionErr
	}
	return fmt.Errorf("endpoint %q was not found", target)
}

// cdPair resolves hostname/endpoint-id or endpoint-id/session targets.
func cdPair(state *interactiveState, loaded reportLoad, first, second string) error {
	if endpoint, ok := endpointByHostnameAndID(loaded, first, second); ok {
		state.enterEndpoint(endpoint)
		return nil
	}
	if endpoint, ok := endpointByID(loaded, first); ok {
		outcome, err := resolveSessionInEndpoint(state, loaded, endpoint.EndpointID, second)
		if outcome == outcomeResolved || err != nil {
			return err
		}
		return fmt.Errorf("session %q was not found on endpoint %q", second, endpoint.EndpointID)
	}
	return fmt.Errorf("endpoint %q was not found", first+"/"+second)
}

// cdTriple resolves a complete hostname/endpoint-id/session path atomically.
func cdTriple(state *interactiveState, loaded reportLoad, hostname, endpointID, sessionID string) error {
	endpoint, ok := endpointByHostnameAndID(loaded, hostname, endpointID)
	if !ok {
		return fmt.Errorf("endpoint %q was not found", hostname+"/"+endpointID)
	}
	outcome, err := resolveSessionInEndpoint(state, loaded, endpoint.EndpointID, sessionID)
	if outcome == outcomeResolved || err != nil {
		return err
	}
	return fmt.Errorf("session %q was not found on endpoint %q", sessionID, endpoint.EndpointID)
}

// resolveEndpoint enters an endpoint by exact ID or by unique hostname.
func resolveEndpoint(state *interactiveState, loaded reportLoad, target string, lineSource <-chan lineReadResult, out io.Writer) (resolveOutcome, error) {
	if endpoint, ok := endpointByID(loaded, target); ok {
		state.enterEndpoint(endpoint)
		return outcomeResolved, nil
	}
	matches := make([]protocol.Endpoint, 0, 2)
	for _, endpoint := range loaded.endpoints {
		if endpoint.Hostname != "" && endpoint.Hostname == target {
			matches = append(matches, endpoint)
		}
	}
	switch len(matches) {
	case 0:
		return outcomeNotFound, nil
	case 1:
		state.enterEndpoint(matches[0])
		return outcomeResolved, nil
	default:
		sort.Slice(matches, func(i, j int) bool { return matches[i].EndpointID < matches[j].EndpointID })
		return chooseEndpoint(state, matches, target, lineSource, out)
	}
}

// chooseEndpoint asks the operator to disambiguate a hostname conflict.
func chooseEndpoint(state *interactiveState, matches []protocol.Endpoint, hostname string, lineSource <-chan lineReadResult, out io.Writer) (resolveOutcome, error) {
	if _, err := fmt.Fprintf(out, "multiple endpoints match hostname %q:\n", hostname); err != nil {
		return outcomeCancelled, err
	}
	for index, endpoint := range matches {
		label := endpoint.DisplayName
		if label == "" {
			label = endpoint.EndpointID
		}
		if _, err := fmt.Fprintf(out, "  %d. %s / %s / %s\n", index+1, endpoint.Hostname, endpoint.EndpointID, label); err != nil {
			return outcomeCancelled, err
		}
	}
	if _, err := fmt.Fprintf(out, "select endpoint [1-%d] or 'cancel': ", len(matches)); err != nil {
		return outcomeCancelled, err
	}
	answer, ok := nextLine(lineSource)
	if !ok || answer.overflow || answer.err != nil {
		return cancelTransition(out)
	}
	choice := strings.TrimSpace(answer.line)
	if choice == "" || strings.EqualFold(choice, "cancel") {
		return cancelTransition(out)
	}
	if index, err := strconv.Atoi(choice); err == nil {
		if index < 1 || index > len(matches) {
			return rejectSelection(out)
		}
		state.enterEndpoint(matches[index-1])
		return outcomeResolved, nil
	}
	if endpoint, ok := matchEndpointPath(matches, choice); ok {
		state.enterEndpoint(endpoint)
		return outcomeResolved, nil
	}
	return rejectSelection(out)
}

// cancelTransition reports an abandoned conflict selection without changing scope.
func cancelTransition(out io.Writer) (resolveOutcome, error) {
	_, err := fmt.Fprintln(out, "scope transition cancelled")
	return outcomeCancelled, err
}

// rejectSelection reports an unusable conflict answer without changing scope.
func rejectSelection(out io.Writer) (resolveOutcome, error) {
	_, err := fmt.Fprintln(out, "invalid selection; scope transition cancelled")
	return outcomeCancelled, err
}

// matchEndpointPath accepts a hostname/endpoint-id answer for a conflict prompt.
func matchEndpointPath(matches []protocol.Endpoint, answer string) (protocol.Endpoint, bool) {
	parts := strings.Split(answer, "/")
	if len(parts) != 2 {
		return protocol.Endpoint{}, false
	}
	for _, endpoint := range matches {
		if endpoint.Hostname == parts[0] && endpoint.EndpointID == parts[1] {
			return endpoint, true
		}
	}
	return protocol.Endpoint{}, false
}

// resolveSessionInEndpoint enters a fresh session identified by ID or unique display name.
func resolveSessionInEndpoint(state *interactiveState, loaded reportLoad, endpointID, target string) (resolveOutcome, error) {
	endpoint, report, ok := endpointReport(loaded, endpointID)
	if !ok || !report.ReportComplete {
		return outcomeNotFound, nil
	}
	for _, session := range report.Sessions {
		if session.SessionID == target {
			return enterValidatedSession(state, endpoint, report, session)
		}
	}
	byName := make([]protocol.Session, 0, 1)
	for _, session := range report.Sessions {
		if session.DisplayName != "" && session.DisplayName == target {
			byName = append(byName, session)
		}
	}
	switch len(byName) {
	case 0:
		return outcomeNotFound, nil
	case 1:
		return enterValidatedSession(state, endpoint, report, byName[0])
	default:
		return outcomeCancelled, fmt.Errorf("multiple sessions match %q on endpoint %q; use the session ID", target, endpointID)
	}
}

// enterValidatedSession changes scope only after freshness validation succeeds.
func enterValidatedSession(state *interactiveState, endpoint protocol.Endpoint, report protocol.InventoryReport, session protocol.Session) (resolveOutcome, error) {
	if session.Generation == "" {
		return outcomeNotFound, nil
	}
	if err := validateSessionFreshness(report, session); err != nil {
		return outcomeCancelled, err
	}
	if err := validateAdapterFreshness(report, session.AdapterID); err != nil {
		return outcomeCancelled, err
	}
	state.enterSession(endpoint, session.SessionID, session.Generation)
	return outcomeResolved, nil
}

// endpointByID returns the endpoint with the exact identifier.
func endpointByID(loaded reportLoad, endpointID string) (protocol.Endpoint, bool) {
	for _, endpoint := range loaded.endpoints {
		if endpoint.EndpointID == endpointID {
			return endpoint, true
		}
	}
	return protocol.Endpoint{}, false
}

// endpointByHostnameAndID returns the endpoint matching both path components.
func endpointByHostnameAndID(loaded reportLoad, hostname, endpointID string) (protocol.Endpoint, bool) {
	for _, endpoint := range loaded.endpoints {
		if endpoint.EndpointID == endpointID && endpoint.Hostname == hostname {
			return endpoint, true
		}
	}
	return protocol.Endpoint{}, false
}

// endpointReport returns the endpoint and its complete inventory when available.
func endpointReport(loaded reportLoad, endpointID string) (protocol.Endpoint, protocol.InventoryReport, bool) {
	endpoint, ok := endpointByID(loaded, endpointID)
	if !ok {
		return protocol.Endpoint{}, protocol.InventoryReport{}, false
	}
	report, ok := loaded.reports[endpointID]
	if !ok {
		return protocol.Endpoint{}, protocol.InventoryReport{}, false
	}
	return endpoint, report, true
}

// findSessionInEndpoint resolves a session inside one endpoint without changing scope.
func findSessionInEndpoint(loaded reportLoad, endpointID, target string) (protocol.Endpoint, protocol.InventoryReport, protocol.Session, error) {
	endpoint, report, ok := endpointReport(loaded, endpointID)
	if !ok || !report.ReportComplete {
		return protocol.Endpoint{}, protocol.InventoryReport{}, protocol.Session{}, fmt.Errorf("endpoint %q inventory is unavailable", endpointID)
	}
	for _, session := range report.Sessions {
		if session.SessionID == target {
			return endpoint, report, session, nil
		}
	}
	byName := make([]protocol.Session, 0, 1)
	for _, session := range report.Sessions {
		if session.DisplayName != "" && session.DisplayName == target {
			byName = append(byName, session)
		}
	}
	switch len(byName) {
	case 1:
		return endpoint, report, byName[0], nil
	case 0:
		return protocol.Endpoint{}, protocol.InventoryReport{}, protocol.Session{}, fmt.Errorf("session %q was not found on endpoint %q", target, endpointID)
	default:
		return protocol.Endpoint{}, protocol.InventoryReport{}, protocol.Session{}, fmt.Errorf("multiple sessions match %q on endpoint %q; use the session ID", target, endpointID)
	}
}
