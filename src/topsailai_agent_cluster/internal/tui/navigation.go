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
// Entering session scope renders one bounded output snapshot immediately, so the
// operator sees the session's current output without typing logs.
func interactiveCD(parent context.Context, api InteractiveAPI, state *interactiveState, rest string, lineSource <-chan lineReadResult, out, trustedOut io.Writer, color ColorPolicy, options InteractiveOptions) error {
	previous := state.Scope
	target := strings.TrimSpace(rest)
	switch target {
	case "", "/":
		state.enterWorkspace()
		return rerenderNavigatedList(parent, api, state, trustedOut, color)
	case "..":
		if err := cdParent(state, out); err != nil {
			return err
		}
		return rerenderNavigatedList(parent, api, state, trustedOut, color)
	}
	parts := strings.Split(target, "/")
	if len(parts) > 3 {
		return fmt.Errorf("usage: cd [target]")
	}
	if len(parts) == 1 && isASCIIDecimal(parts[0]) {
		index, numeric := parseRowNumber(parts[0])
		if !numeric {
			return fmt.Errorf("row number exceeds the supported integer range")
		}
		if err := cdRowNumber(state, api, parent, index); err != nil {
			return err
		}
		return autoLogsOnSessionEntry(parent, api, state, previous, out, options)
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
	var resolveErr error
	switch len(parts) {
	case 1:
		// The disambiguation prompt is a human answer, so it must not inherit the
		// command deadline; only the inventory load above is bounded.
		resolveErr = cdSingle(parent, state, loaded, parts[0], lineSource, out)
	case 2:
		resolveErr = cdPair(state, loaded, parts[0], parts[1])
	default:
		resolveErr = cdTriple(state, loaded, parts[0], parts[1], parts[2])
	}
	if resolveErr != nil {
		return resolveErr
	}
	if err := rerenderNavigatedList(parent, api, state, trustedOut, color); err != nil {
		return err
	}
	return autoLogsOnSessionEntry(parent, api, state, previous, out, options)
}

// autoLogsOnSessionEntry renders one bounded output snapshot when a navigation
// command actually enters session scope. The generation validated by the
// transition is reused, so entering a session costs one output read and no
// repeated inventory discovery. A failed read is reported without rolling back
// the already validated selection.
func autoLogsOnSessionEntry(parent context.Context, api InteractiveAPI, state *interactiveState, previous ScopeState, out io.Writer, options InteractiveOptions) error {
	if state.Scope.Kind != ScopeSession || previous.Kind == ScopeSession {
		return nil
	}
	return renderAutomaticSnapshot(parent, api, state, out, options, "session selected")
}

// renderAutomaticSnapshot renders one bounded output snapshot for the selected
// session and reports a failed read as a diagnostic instead of an error. The
// caller has already validated the selection, so a follow-up read must never
// turn an accepted action into a failure. failurePrefix names the action that
// triggered the read, so the operator can tell which step failed.
func renderAutomaticSnapshot(parent context.Context, api InteractiveAPI, state *interactiveState, out io.Writer, options InteractiveOptions, failurePrefix string) error {
	maxBytes, maxLines := interactiveOutputBounds(options)
	ctx, cancel := commandContext(parent)
	defer cancel()
	runner := CommandRunner{API: api, Policy: InteractivePolicy}
	if err := runner.RenderSessionSnapshot(ctx, out, state.EndpointID, state.SessionID, state.Generation, maxBytes, maxLines); err != nil {
		return writeAutomaticDiagnostic(out, failurePrefix, "automatic logs failed: "+err.Error())
	}
	return nil
}

// refreshSelectedSession asks the selected session's Endpoint for one fresh
// collection and revalidates only that session against the committed document,
// so a later list reads a newer persisted inventory without rendering the table.
// The Endpoint is the smallest unit the Server can make fresh, because it stores
// one inventory document per Endpoint; the per-session part is the revalidation,
// not a separate query. A client without the forced-collection seam degrades to
// read-only behaviour, and every failure is reported as a diagnostic instead of
// turning the accepted action into a failure.
func refreshSelectedSession(parent context.Context, api InteractiveAPI, state *interactiveState, out io.Writer, failurePrefix string) error {
	refresher, forced := api.(InventoryRefresher)
	if !forced {
		return nil
	}
	ctx, cancel := context.WithTimeout(parent, refreshCommandTimeout)
	defer cancel()
	if _, err := refresher.RefreshInventory(ctx, state.EndpointID); err != nil {
		return writeAutomaticDiagnostic(out, failurePrefix, "automatic refresh failed: "+err.Error())
	}
	report, err := api.GetInventory(ctx, state.EndpointID)
	if err != nil {
		return writeAutomaticDiagnostic(out, failurePrefix, "automatic refresh failed: "+err.Error())
	}
	loaded := reportLoad{
		endpoints: []protocol.Endpoint{{EndpointID: state.EndpointID}},
		reports:   map[string]protocol.InventoryReport{state.EndpointID: report},
	}
	if _, _, _, err := findSelectedIn(loaded, state); err != nil {
		return writeAutomaticDiagnostic(out, failurePrefix, err.Error())
	}
	return nil
}

// writeAutomaticDiagnostic reports a failed automatic step without failing the
// command that triggered it, because that command's durable receipt is already
// the authority for what happened.
func writeAutomaticDiagnostic(out io.Writer, failurePrefix, detail string) error {
	_, err := fmt.Fprintf(out, "%s; %s\n", failurePrefix, detail)
	return err
}

// interactiveOutputBounds resolves the bounded output read limits used by an
// automatic snapshot, applying the same REPL defaults as RunInteractive so an
// unset option never requests an unbounded read.
func interactiveOutputBounds(options InteractiveOptions) (int, int) {
	maxLines := options.MaxLines
	if maxLines <= 0 {
		maxLines = 100
	}
	maxBytes := options.MaxBytes
	if maxBytes <= 0 {
		maxBytes = 64 << 10
	}
	return maxBytes, maxLines
}

// rerenderNavigatedList refreshes the visible list for workspace and endpoint scopes.
func rerenderNavigatedList(parent context.Context, api InteractiveAPI, state *interactiveState, out io.Writer, color ColorPolicy) error {
	if state.Scope.Kind == ScopeSession {
		return nil
	}
	return interactiveList(parent, api, state, "", false, out, io.Discard, color)
}

// isASCIIDecimal recognizes unsigned ASCII decimal syntax without accepting signs or whitespace.
func isASCIIDecimal(value string) bool {
	if value == "" {
		return false
	}
	for _, r := range value {
		if r < '0' || r > '9' {
			return false
		}
	}
	return true
}

// parseRowNumber converts an already classified ASCII decimal token.
func parseRowNumber(value string) (int, bool) {
	if !isASCIIDecimal(value) {
		return 0, false
	}
	number, err := strconv.Atoi(value)
	return number, err == nil
}

// cdRowNumber resolves against the most recently rendered table, preserving the user's visible numbering.
func cdRowNumber(state *interactiveState, api InteractiveAPI, parent context.Context, number int) error {
	if state.Scope.Kind == ScopeSession {
		return fmt.Errorf("row-number navigation is unavailable in session scope; use cd .. or cd <session>")
	}
	if len(state.Rows) == 0 {
		return fmt.Errorf("no list is available for row navigation; run list first")
	}
	row, ok := state.Rows[number]
	if !ok {
		return fmt.Errorf("row %d is out of range; valid rows are 1-%d", number, len(state.Rows))
	}
	if row.SessionID == "" {
		return fmt.Errorf("row %d does not identify a session; choose a session row", number)
	}
	if row.Generation == "" {
		return fmt.Errorf("row %d has no generation; run list again", number)
	}
	ctx, cancel := commandContext(parent)
	defer cancel()
	loaded, err := loadReports(ctx, api, row.EndpointID)
	if err != nil {
		return err
	}
	endpoint, report, ok := endpointReport(loaded, row.EndpointID)
	if !ok || !report.ReportComplete {
		return fmt.Errorf("endpoint %q inventory is unavailable; run list again", row.EndpointID)
	}
	var match *protocol.Session
	for i := range report.Sessions {
		if report.Sessions[i].SessionID != row.SessionID {
			continue
		}
		if match != nil {
			return fmt.Errorf("row %d identifies multiple sessions; run list again", number)
		}
		match = &report.Sessions[i]
	}
	if match == nil {
		return fmt.Errorf("row %d no longer identifies a session; run list again", number)
	}
	if match.Generation == "" || match.Generation != row.Generation {
		return fmt.Errorf("row %d generation changed; run list again", number)
	}
	outcome, enterErr := enterValidatedSession(state, endpoint, report, *match)
	if enterErr != nil {
		return enterErr
	}
	if outcome == outcomeResolved {
		return nil
	}
	return fmt.Errorf("row %d no longer identifies a session; run list again", number)
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
func cdSingle(ctx context.Context, state *interactiveState, loaded reportLoad, target string, lineSource <-chan lineReadResult, out io.Writer) error {
	var sessionErr error
	if state.Scope.Kind != ScopeWorkspace {
		outcome, err := resolveSessionInEndpoint(state, loaded, state.Scope.EndpointID, target)
		if outcome == outcomeResolved || err != nil {
			return err
		}
		sessionErr = fmt.Errorf("session %q was not found on endpoint %q", target, state.Scope.EndpointID)
	}
	outcome, err := resolveEndpoint(ctx, state, loaded, target, lineSource, out)
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
func resolveEndpoint(ctx context.Context, state *interactiveState, loaded reportLoad, target string, lineSource <-chan lineReadResult, out io.Writer) (resolveOutcome, error) {
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
		return chooseEndpoint(ctx, state, matches, target, lineSource, out)
	}
}

// chooseEndpoint asks the operator to disambiguate a hostname conflict.
func chooseEndpoint(ctx context.Context, state *interactiveState, matches []protocol.Endpoint, hostname string, lineSource <-chan lineReadResult, out io.Writer) (resolveOutcome, error) {
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
	answer, ok := nextPromptLine(ctx, lineSource)
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
	if err := validateEndpointOnline(endpoint); err != nil {
		return outcomeCancelled, err
	}
	if err := validateSessionFreshness(report, session); err != nil {
		return outcomeCancelled, err
	}
	if err := validateAdapterFreshness(report, session.AdapterID); err != nil {
		return outcomeCancelled, err
	}
	state.enterSessionDetails(endpoint, session.SessionID, session.ProviderSessionID, session.DisplayName, session.AdapterID, session.Generation)
	return outcomeResolved, nil
}

// validateEndpointOnline rejects retained inventory from a disconnected endpoint,
// because stale data must never authorize a session-scoped transition.
func validateEndpointOnline(endpoint protocol.Endpoint) error {
	if endpoint.ConnectionState != "" && endpoint.ConnectionState != "online" {
		return fmt.Errorf("endpoint %q is not online: connection_state=%s", endpoint.EndpointID, endpoint.ConnectionState)
	}
	return nil
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
	// The list displays the provider session identifier, so it must also be
	// accepted as input; the cluster resource ID keeps precedence above.
	for _, session := range report.Sessions {
		if session.ProviderSessionID != "" && session.ProviderSessionID == target {
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
