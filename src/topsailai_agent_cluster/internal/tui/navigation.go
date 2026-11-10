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
		// The history namespace wins when it is the most recent render, because
		// the operator is looking at the history table and a number must mean the
		// row they can see. Rendering a list clears the namespace, so the two can
		// never both claim the same number.
		if state.history != nil {
			if err := cdHistoryRowNumber(state, api, parent, index); err != nil {
				return err
			}
			return autoLogsOnSessionEntry(parent, api, state, previous, trustedOut, options)
		}
		if err := cdRowNumber(state, api, parent, index); err != nil {
			return err
		}
		return autoLogsOnSessionEntry(parent, api, state, previous, trustedOut, options)
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
		resolveErr = cdSingle(parent, state, loaded, parts[0], lineSource, out, trustedOut, color)
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
	return autoLogsOnSessionEntry(parent, api, state, previous, trustedOut, options)
}

// autoLogsOnSessionEntry follows the output of the session a navigation command
// actually entered. The generation validated by the transition is reused, so
// entering a session costs one output read and no repeated inventory discovery.
// It arms the same live tail as logs -f, because a one-shot snapshot stops at the
// moment it was read while the agent keeps writing. A client that cannot stream,
// or a reader that cannot observe a keypress, degrades to that bounded snapshot
// and says why. A failed read is reported without rolling back the already
// validated selection.
func autoLogsOnSessionEntry(parent context.Context, api InteractiveAPI, state *interactiveState, previous ScopeState, trustedOut io.Writer, options InteractiveOptions) error {
	if state.Scope.Kind != ScopeSession || previous.Kind == ScopeSession {
		return nil
	}
	return autoFollowAfterAction(parent, api, state, state.EndpointID, state.ClusterSessionID, state.ProviderGeneration, trustedOut, options, "session selected")
}

// renderAutomaticSnapshot renders one bounded output snapshot for the selected
// session and reports a failed read as a diagnostic instead of an error. The
// caller has already validated the selection, so a follow-up read must never
// turn an accepted action into a failure. failurePrefix names the action that
// triggered the read, so the operator can tell which step failed.
func renderAutomaticSnapshot(parent context.Context, api InteractiveAPI, state *interactiveState, trustedOut io.Writer, color ColorPolicy, options InteractiveOptions, failurePrefix string) error {
	return renderSnapshotForTarget(parent, api, state.EndpointID, state.ClusterSessionID, state.ProviderGeneration, trustedOut, color, options, failurePrefix)
}

// renderSnapshotForTarget renders one bounded output snapshot for an explicit
// target. The automatic snapshot and the follow recovery both call it, so the
// two routes cannot drift into two renderers, two budgets or two failure
// messages. The target is passed explicitly because a recovery addresses the
// session that was followed, which is not necessarily the current selection.
func renderSnapshotForTarget(parent context.Context, api InteractiveAPI, endpointID, sessionID, generation string, trustedOut io.Writer, color ColorPolicy, options InteractiveOptions, failurePrefix string) error {
	maxBytes, maxLines := interactiveOutputBounds(options)
	ctx, cancel := commandContext(parent)
	defer cancel()
	runner := CommandRunner{API: api, Policy: InteractivePolicy}
	if err := runner.RenderSessionSnapshot(ctx, trustedOut, endpointID, sessionID, generation, maxBytes, maxLines, color); err != nil {
		// The diagnostic interpolates a provider error, so it is sanitized
		// before it reaches the trusted writer.
		return writeAutomaticDiagnostic(trustedOut, failurePrefix, "automatic logs failed: "+sanitizeTerminal([]byte(err.Error())))
	}
	return nil
}

// followRecovery is the optional seam a follow session implements when it can
// report that the operator was left without output. A session that does not
// implement it keeps its current behaviour, so the auto-refresh loop and a
// stream that never started are unaffected.
type followRecovery interface {
	Recovery(operatorContinued bool) (followRequest, string, bool)
}

// recoverFollowOutput renders one bounded snapshot when a follow stream ended
// without showing the operator any output, or ended abnormally after showing
// only part of it. The decision belongs to the session, because only the session
// knows whether the bytes it received ever reached the terminal.
//
// operatorContinued reports that the operator typed a real command after the
// stream stopped. A keypress that became a command is a deliberate move on, so
// the keypress trigger declines; an abnormal end still recovers, because the
// stream failed rather than being dismissed.
//
// The status line comes first and names the reason, so a snapshot is never
// mistaken for a stream that is still running. A failed snapshot is a
// diagnostic, never a command failure: the stream already ended, and the
// operator's command was accepted before it started.
func recoverFollowOutput(parent context.Context, api InteractiveAPI, watch WatchSession, trustedOut io.Writer, options InteractiveOptions, operatorContinued bool) error {
	recovery, ok := watch.(followRecovery)
	if !ok {
		return nil
	}
	request, code, needed := recovery.Recovery(operatorContinued)
	if !needed {
		return nil
	}
	message := "follow ended: " + sanitizeInlineText(code) + "; showing one snapshot instead"
	if code == "no_output" {
		message = "follow stopped before any output; showing one snapshot instead"
	}
	// The policy comes from the writer this line goes to, exactly as the follow
	// announcement does, so --no-color and a redirected stream stay plain.
	if _, err := fmt.Fprintln(trustedOut, renderFollowStatus(message, ansiDim, OutputColorPolicy(trustedOut), false)); err != nil {
		return err
	}
	return renderSnapshotForTarget(parent, api, request.EndpointID, request.ResourceID, request.ProviderGeneration, trustedOut, OutputColorPolicy(trustedOut), options, "follow recovery")
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
// automatic snapshot, applying the same REPL budget as RunInteractive so an
// unset option never requests an unbounded read.
func interactiveOutputBounds(options InteractiveOptions) (int, int) {
	// The automatic snapshot reuses the REPL budget resolver, so the entry
	// snapshot and a bare logs read can never disagree about how many trailing
	// lines they show.
	maxLines := NormalizeInteractiveMaxLines(options.MaxLines)
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
	return interactiveList(parent, api, state, "", false, false, out, io.Discard, color)
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
	if row.ClusterSessionID == "" {
		return fmt.Errorf("row %d does not identify a session; choose a session row", number)
	}
	if row.ProviderGeneration == "" {
		return fmt.Errorf("row %d has no generation; run list again", number)
	}
	return cdSessionRow(state, api, parent, number, row)
}

// cdSessionRow enters one already resolved session row after revalidating its
// generation against the current inventory. It is shared by the live list
// namespace and the history namespace, so both surfaces apply exactly the same
// authority checks instead of drifting apart.
func cdSessionRow(state *interactiveState, api InteractiveAPI, parent context.Context, number int, row SessionRow) error {
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
		if report.Sessions[i].ClusterSessionID != row.ClusterSessionID {
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
	if match.ProviderGeneration == "" || match.ProviderGeneration != row.ProviderGeneration {
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
// The disambiguation question is a prompt that waits for operator input, so it is
// written through the trusted writer with the same styling as every other prompt.
func cdSingle(ctx context.Context, state *interactiveState, loaded reportLoad, target string, lineSource <-chan lineReadResult, out, trustedOut io.Writer, color ColorPolicy) error {
	var sessionErr error
	if state.Scope.Kind != ScopeWorkspace {
		outcome, err := resolveSessionInEndpoint(state, loaded, state.Scope.EndpointID, target)
		if outcome == outcomeResolved || err != nil {
			return err
		}
		sessionErr = fmt.Errorf("session %q was not found on endpoint %q", target, state.Scope.EndpointID)
	}
	outcome, err := resolveEndpoint(ctx, state, loaded, target, lineSource, out, trustedOut, color)
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
func resolveEndpoint(ctx context.Context, state *interactiveState, loaded reportLoad, target string, lineSource <-chan lineReadResult, out, trustedOut io.Writer, color ColorPolicy) (resolveOutcome, error) {
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
		return chooseEndpoint(ctx, state, matches, target, lineSource, out, trustedOut, color)
	}
}

// chooseEndpoint asks the operator to disambiguate a hostname conflict. The
// question is a prompt that waits for operator input, so it is written through the
// trusted writer with the confirmation styling; the sanitizing writer would strip
// the colour. The question is written here and not passed to the read, because the
// terminal editor draws its own styled answer prompt on the next row and passing
// this question as well would print it twice.
func chooseEndpoint(ctx context.Context, state *interactiveState, matches []protocol.Endpoint, hostname string, lineSource <-chan lineReadResult, out, trustedOut io.Writer, color ColorPolicy) (resolveOutcome, error) {
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
	question := fmt.Sprintf("select endpoint [1-%d] or 'cancel': ", len(matches))
	if err := writeConfirmationQuestion(trustedOut, question, color); err != nil {
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
		if session.ClusterSessionID == target {
			return enterValidatedSession(state, endpoint, report, session)
		}
	}
	byName := make([]protocol.Session, 0, 1)
	for _, session := range report.Sessions {
		if session.ProviderDisplayName != "" && session.ProviderDisplayName == target {
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
	if session.ProviderGeneration == "" {
		// A session reported without a generation is present but its liveness was
		// not verified, so it cannot be entered. Returning not-found here would
		// tell the operator the session does not exist, which is false and hides
		// the only recovery step.
		return outcomeCancelled, fmt.Errorf("session %s is unverified on endpoint %q: the session record exists but no process holds it, so it cannot be entered; use resume to resume it", sessionIdentityLabel(session.ProviderDisplayName, session.ProviderSessionID, session.ClusterSessionID), endpoint.EndpointID)
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
	state.enterSessionDetails(endpoint, session.ClusterSessionID, session.ProviderSessionID, session.ProviderDisplayName, session.AdapterID, session.ProviderGeneration)
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
		if session.ClusterSessionID == target {
			return endpoint, report, session, nil
		}
	}
	// The provider session identifier is hidden from the interactive table but is
	// still a valid selector, so it must also be accepted as input; the cluster
	// resource ID keeps precedence above.
	for _, session := range report.Sessions {
		if session.ProviderSessionID != "" && session.ProviderSessionID == target {
			return endpoint, report, session, nil
		}
	}
	byName := make([]protocol.Session, 0, 1)
	for _, session := range report.Sessions {
		if session.ProviderDisplayName != "" && session.ProviderDisplayName == target {
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
