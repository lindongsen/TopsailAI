package tui

import (
	"context"
	"encoding/json"
	"fmt"
	"io"
	"sort"
	"strconv"
	"strings"

	"topsailai_agent_cluster/internal/protocol"
)

// historyNamespace is the row-number namespace produced by one history render.
//
// Rendering history replaces the live list namespace for that render, because a
// number must never silently mean a different row after the visible table
// changed. The namespace is endpoint-scoped: a history query always concerns one
// endpoint, so a number can never address a row from another machine.
type historyNamespace struct {
	EndpointID string
	Rows       map[int]HistoryViewRow
}

// interactiveHistory renders bounded provider history and replaces the row-number
// namespace with the rendered history table.
//
// Endpoint scope queries the current endpoint and rejects a different explicit
// endpoint, because the operator is already inside one machine. Workspace scope
// requires the endpoint argument, because a history query is endpoint-scoped and
// fanning out would multiply provider calls and mix rows whose provider session
// identifiers may collide.
func interactiveHistory(parent context.Context, api InteractiveAPI, state *interactiveState, rest string, out, diagnostics io.Writer, color ColorPolicy) error {
	if err := rejectInteractiveOption("history", rest); err != nil {
		return err
	}
	querier, ok := api.(HistoryQuerier)
	if !ok {
		return fmt.Errorf("history is unavailable: this client cannot query provider history")
	}
	ctx, cancel := commandContext(parent)
	defer cancel()
	endpointID, err := historyEndpointID(ctx, api, state, strings.TrimSpace(rest))
	if err != nil {
		return err
	}
	// The interactive surface always reads the whole provider window, because a
	// REPL operator selects a row from what is rendered and cannot pass a limit.
	result, err := querier.GetHistory(ctx, endpointID, 0)
	if err != nil {
		return err
	}
	if result.ErrorCode != "" {
		return fmt.Errorf("history for endpoint %q failed: %s", endpointID, result.ErrorCode)
	}
	report, inventoryErr := api.GetInventory(ctx, endpointID)
	view := JoinHistory(endpointID, result.Rows, report, inventoryErr == nil)
	view.ObservedAtMS = result.ObservedAtMS
	view.Truncated = result.Truncated
	// The live namespace is dropped before the history table is rendered, so a
	// number from the previous list can never be applied to a history row.
	state.Rows = nil
	state.history = nil
	if inventoryErr != nil {
		if _, err := fmt.Fprintf(diagnostics, "history rows are unjoined: inventory for endpoint %q is unavailable: %v\n", endpointID, inventoryErr); err != nil {
			return err
		}
	}
	if view.Truncated {
		if _, err := fmt.Fprintln(diagnostics, "history is a bounded provider window; older sessions are not listed"); err != nil {
			return err
		}
	}
	// The interactive history table hides SESSION_ID for the same reason the
	// session list does: the operator selects a row by number, and the provider
	// session ID is a long opaque value that only widens the table. The ID stays
	// on the row, so it is still accepted as a selector and still named in the
	// resume and cd diagnostics. The standalone history command keeps the column,
	// because its output is parsed by scripts and tests.
	options := TableOptionsFor(out)
	options.Color = color
	options.HideSessionID = true
	if err := RenderHistory(out, view, options); err != nil {
		return err
	}
	state.history = &historyNamespace{EndpointID: endpointID, Rows: make(map[int]HistoryViewRow, len(view.Rows))}
	for _, row := range view.Rows {
		state.history.Rows[row.No] = row
	}
	return nil
}

// historyEndpointID resolves the endpoint a history query must address.
//
// Endpoint scope already names one machine, so an explicit argument may only
// repeat it. Workspace scope has no current endpoint, so the argument is
// mandatory. Both scopes resolve through the same resolver the standalone command
// uses, so connectivity is validated on both paths: an endpoint that was online
// when it was entered can disconnect before the query is dispatched.
func historyEndpointID(ctx context.Context, api InteractiveAPI, state *interactiveState, target string) (string, error) {
	if state.Scope.Kind == ScopeEndpoint {
		if target != "" && target != state.Scope.EndpointID {
			return "", fmt.Errorf("history %q does not match the current endpoint %q; run cd .. to query another endpoint", target, state.Scope.EndpointID)
		}
		target = state.Scope.EndpointID
	}
	endpoint, err := resolveHistoryEndpoint(ctx, api, target)
	if err != nil {
		return "", err
	}
	return endpoint.EndpointID, nil
}

// cdHistoryRowNumber enters one live history row and rejects a non-live row with
// the reason the adapter reported.
//
// A history row is never a routing identity, so the transition reuses the joined
// resource ID and generation and revalidates them against the current inventory.
// A row that is not live has no generation at all, so it can never be entered.
//
// Session scope rejects row-number navigation for the same reason the live list
// does: the operator is already inside one session, so a bare number has no table
// to address. Without this guard a number typed in session scope resolved against
// the history table left behind by the previous render and reported a history-row
// error instead of the scope error.
func cdHistoryRowNumber(state *interactiveState, api InteractiveAPI, parent context.Context, number int) error {
	if state.Scope.Kind == ScopeSession {
		return fmt.Errorf("row-number navigation is unavailable in session scope; use cd .. or cd <session>")
	}
	namespace := state.history
	if namespace == nil {
		return fmt.Errorf("no history table is available for row navigation; run history first")
	}
	row, ok := namespace.Rows[number]
	if !ok {
		return fmt.Errorf("row %d is out of range; valid history rows are 1-%d", number, len(namespace.Rows))
	}
	// An ambiguous row and an unjoined row are both unusable, but they are not the
	// same unknown. Ambiguity means the inventory answered with several live
	// sessions for one provider session ID, so the operator must inspect the
	// endpoint inventory; no client-side retry can resolve contradictory data.
	if row.Ambiguous {
		return fmt.Errorf("history row %d is ambiguous: endpoint %q reports several live sessions for session %s, so the row cannot be entered; inspect the endpoint inventory", number, namespace.EndpointID, sessionIdentityLabel(row.DisplayName, row.ProviderSessionID, ""))
	}
	if !row.Joined {
		return fmt.Errorf("history row %d is unjoined: the inventory for endpoint %q is unavailable, so the row cannot be entered; run refresh and history again", number, namespace.EndpointID)
	}
	if !row.Live {
		// An unverified row is present but cannot be addressed, so the operator
		// must be told the real reason instead of a generic "not live". Resume is
		// the only operation that does not need a generation, so it is the only
		// recovery step worth naming.
		if row.Unverified {
			return fmt.Errorf("history row %d is unverified on endpoint %q: the session record exists but no process holds it, so it cannot be entered; use resume %d to resume it", number, namespace.EndpointID, number)
		}
		return fmt.Errorf("history row %d is not live on endpoint %q, so it cannot be entered; use resume %d to resume it", number, namespace.EndpointID, number)
	}
	// The join supplies the only routable pair. An empty pair means the join
	// could not prove a live session, so the transition must fail closed.
	if row.ResourceID == "" || row.Generation == "" {
		return fmt.Errorf("history row %d has no routable identity; run history again", number)
	}
	sessionRow := SessionRow{No: row.No, EndpointID: row.EndpointID, SessionID: row.ResourceID, ProviderSessionID: row.ProviderSessionID, Generation: row.Generation, State: row.State}
	if err := cdSessionRow(state, api, parent, number, sessionRow); err != nil {
		return err
	}
	// The history table is no longer on screen once a session is entered, so its
	// row numbers must not survive the transition. Keeping them would let a later
	// number resolve against a table the operator can no longer see.
	state.history = nil
	return nil
}

// Resume row numbers come from one of two tables. The names are used in the
// stale-number notice, so the operator is told which command refreshes them.
const (
	resumeSourceHistory = "history"
	resumeSourceList    = "list"
)

// resumeSelection is one resolved resume target.
//
// It is deliberately independent of the table that supplied the row number,
// because resume addresses the provider session by handle and the two tables
// describe the same provider session from different evidence: history reports a
// past provider record, while the live list reports a record whose liveness the
// provider could not verify.
type resumeSelection struct {
	EndpointID        string
	ProviderSessionID string
	ResourceID        string
	DisplayName       string
	// Source names the table the row number came from, so the stale-number
	// notice names the command that refreshes those numbers.
	Source string
}

// interactiveResume resumes one stopped session selected by a row number.
//
// Resume authorizes on the absence of the target, so it addresses the opaque
// resource handle the Endpoint minted for the provider session and carries no
// generation. A live row is rejected because it is already running.
//
// Two tables can supply the row number, and they are mutually exclusive because
// each render clears the other namespace. The history table reports a past
// provider record together with the adapter's own resumability verdict. The live
// list reports a session whose liveness the provider could not verify, which is
// the only case where a session is visible but cannot be entered; such a row
// carries no adapter verdict, so resume accepts it only when the reported state is
// unknown and no generation was reported.
//
// A bare resume is accepted only when exactly one listed session is unknown,
// because a second unknown row would make the choice ambiguous and resuming the
// wrong session would start a runtime the operator did not ask for.
func interactiveResume(parent context.Context, api InteractiveAPI, state *interactiveState, rest string, lines <-chan lineReadResult, out, trustedOut io.Writer, options InteractiveOptions) error {
	if err := rejectInteractiveOption("resume", rest); err != nil {
		return err
	}
	selection, err := resolveResumeSelection(state, strings.TrimSpace(rest))
	if err != nil {
		return err
	}
	// The pinned selection is detached because resume outside session scope is not
	// the current selection. The shared confirmation path records the command ID on
	// that copy, so it is copied back before the caller can query status.
	pinned := *state
	pinned.EndpointID = selection.EndpointID
	pinned.SessionID = selection.ResourceID
	pinned.Generation = ""
	pinned.Invalidated = false
	pinned.InvalidReason = ""
	revalidate := func(revalidateCtx context.Context) error {
		return validateResumeAbsence(revalidateCtx, api, selection.EndpointID, selection.ProviderSessionID)
	}
	postSubmit := func(postCtx context.Context, result map[string]any) error {
		state.commandID = pinned.commandID
		return invalidateResumeRowBindings(state, selection.Source, out)
	}
	target := confirmationTarget{DisplayName: selection.DisplayName, ProviderSessionID: selection.ProviderSessionID, SessionID: selection.ResourceID}
	return interactiveConfirmedAction(parent, api, &pinned, protocol.OperationAgentResume, "resume", target, "", json.RawMessage(`{}`), lines, out, trustedOut, options, revalidate, postSubmit)
}

// resolveResumeSelection maps the resume argument to one resume target.
//
// An empty argument selects the only unknown session in the current list, so the
// operator can recover it without first rendering a table. A row number is
// resolved against whichever table is currently rendered, because each render
// clears the other namespace and a number must never silently mean a row from a
// table the operator can no longer see.
func resolveResumeSelection(state *interactiveState, token string) (resumeSelection, error) {
	if token == "" {
		return uniqueUnknownResumeSelection(state)
	}
	number, numeric := parseRowNumber(token)
	if !numeric {
		return resumeSelection{}, fmt.Errorf("resume accepts a row number only; run list or history to see the rows")
	}
	if state.history != nil {
		return historyResumeSelection(state.history, number)
	}
	if len(state.Rows) > 0 {
		return listResumeSelection(state, number)
	}
	return resumeSelection{}, fmt.Errorf("resume requires a rendered table; run list or history first")
}

// historyResumeSelection applies the history-table rules to one row number.
//
// The adapter owns the resumability verdict, so this function never re-derives
// it; it only refuses the rows that cannot be addressed at all.
func historyResumeSelection(namespace *historyNamespace, number int) (resumeSelection, error) {
	row, ok := namespace.Rows[number]
	if !ok {
		return resumeSelection{}, fmt.Errorf("row %d is out of range; valid history rows are 1-%d", number, len(namespace.Rows))
	}
	// An ambiguous row is not live, but the inventory did report live sessions for
	// this provider session ID. Resuming would therefore start a second runtime for
	// a session that is already running, so the row is refused before the adapter
	// verdict is consulted.
	if row.Ambiguous {
		return resumeSelection{}, fmt.Errorf("history row %d is ambiguous: endpoint %q reports several live sessions for session %s, so it cannot be resumed; inspect the endpoint inventory instead", number, namespace.EndpointID, sessionIdentityLabel(row.DisplayName, row.ProviderSessionID, ""))
	}
	if row.Live {
		return resumeSelection{}, fmt.Errorf("history row %d is live on endpoint %q, so it cannot be resumed; use cd %d to enter it", number, namespace.EndpointID, number)
	}
	if !row.Resumable {
		reason := row.ResumeBlockedReason
		if reason == "" {
			reason = protocol.ResumeBlockedRecordIncomplete
		}
		return resumeSelection{}, fmt.Errorf("history row %d is not resumable: %s", number, reason)
	}
	if row.ResumeResourceID == "" {
		return resumeSelection{}, fmt.Errorf("history row %d has no resource handle, so it cannot be resumed; run history again", number)
	}
	return resumeSelection{EndpointID: namespace.EndpointID, ProviderSessionID: row.ProviderSessionID, ResourceID: row.ResumeResourceID, DisplayName: row.DisplayName, Source: resumeSourceHistory}, nil
}

// listResumeSelection accepts one live-list row only when the provider reported
// the session as unknown and reported no generation.
//
// That combination is the only case where a session is visible but cannot be
// entered: the record exists, so resume can address it, while no process was
// proven to hold it, so no generation exists to validate. A row with a generation
// is already running and must be entered instead, and a row in any other state is
// not a resume candidate at all.
func listResumeSelection(state *interactiveState, number int) (resumeSelection, error) {
	row, ok := state.Rows[number]
	if !ok {
		return resumeSelection{}, fmt.Errorf("row %d is out of range; valid rows are 1-%d", number, len(state.Rows))
	}
	if row.SessionID == "" {
		return resumeSelection{}, fmt.Errorf("row %d does not identify a session; choose a session row", number)
	}
	if row.Generation != "" {
		return resumeSelection{}, fmt.Errorf("row %d is live on endpoint %q, so it cannot be resumed; use cd %d to enter it", number, row.EndpointID, number)
	}
	if row.State != protocol.SessionStateUnknown {
		return resumeSelection{}, fmt.Errorf("row %d is %q on endpoint %q, so it cannot be resumed; only an unknown session can be resumed from the list", number, row.State, row.EndpointID)
	}
	return resumeSelection{EndpointID: row.EndpointID, ProviderSessionID: row.ProviderSessionID, ResourceID: row.SessionID, DisplayName: row.DisplayName, Source: resumeSourceList}, nil
}

// uniqueUnknownResumeSelection resolves a bare resume to the only unknown session
// in the current list.
//
// The uniqueness requirement is the whole point of the guard: an unknown session
// cannot be entered, so a bare resume is the operator's recovery step, and with
// several unknown rows there is no way to tell which one was meant. Resuming the
// wrong session would start a runtime nobody asked for, so the ambiguity is
// reported with the candidate row numbers instead of being resolved by position.
func uniqueUnknownResumeSelection(state *interactiveState) (resumeSelection, error) {
	if len(state.Rows) == 0 {
		return resumeSelection{}, fmt.Errorf("resume requires a rendered table; run list first")
	}
	candidates := make([]SessionRow, 0, 2)
	for _, row := range state.Rows {
		if row.SessionID == "" || row.Generation != "" || row.State != protocol.SessionStateUnknown {
			continue
		}
		candidates = append(candidates, row)
	}
	switch len(candidates) {
	case 0:
		return resumeSelection{}, fmt.Errorf("no unknown session is listed, so a bare resume has no target; run list and resume <row>")
	case 1:
		row := candidates[0]
		return resumeSelection{EndpointID: row.EndpointID, ProviderSessionID: row.ProviderSessionID, ResourceID: row.SessionID, DisplayName: row.DisplayName, Source: resumeSourceList}, nil
	}
	sort.Slice(candidates, func(i, j int) bool { return candidates[i].No < candidates[j].No })
	numbers := make([]string, len(candidates))
	for i, row := range candidates {
		numbers[i] = strconv.Itoa(row.No)
	}
	return resumeSelection{}, fmt.Errorf("%d unknown sessions are listed (%s), so a bare resume is ambiguous; run resume <row> to choose one", len(candidates), strings.Join(numbers, ", "))
}

// validateResumeAbsence proves from the current inventory that the provider
// session is not already running, so a stale history row can never resume a
// session that has since started. The Endpoint repeats this check against the
// provider's own answer before it invokes the provider, so this is a client-side
// guard, not the authority.
//
// Presence in the inventory is not the same as being live. A session whose
// liveness was not verified is reported without a generation, and resume is the
// only operation that can recover it, so such a row must not be refused here.
// Only a session with a verified generation is already running.
func validateResumeAbsence(ctx context.Context, api InteractiveAPI, endpointID, providerSessionID string) error {
	loaded, err := loadReports(ctx, api, endpointID)
	if err != nil {
		return err
	}
	endpoint, found := endpointByID(loaded, endpointID)
	if !found {
		return fmt.Errorf("endpoint %q was not found; run history again", endpointID)
	}
	if err := validateEndpointOnline(endpoint); err != nil {
		return err
	}
	report, ok := loaded.reports[endpointID]
	if !ok || !report.ReportComplete {
		return fmt.Errorf("endpoint %q inventory is unavailable, so the absence of session %s cannot be proven", endpointID, sessionIdentityLabel("", providerSessionID, ""))
	}
	for _, session := range report.Sessions {
		if session.ProviderSessionID == "" || session.ProviderSessionID != providerSessionID {
			continue
		}
		if session.Generation == "" {
			continue
		}
		return fmt.Errorf("session %s is live on endpoint %q, so it cannot be resumed; use cd to enter it", sessionIdentityLabel(session.DisplayName, session.ProviderSessionID, session.SessionID), endpointID)
	}
	return nil
}

// invalidateResumeRowBindings drops the row numbers rendered before the resume,
// because the resumed session may become live and a stale number would then name
// a different row after the next render.
//
// Both tables are cleared, not only the one that supplied the number. A resume
// changes the inventory, so a number from either table can be stale afterwards,
// and clearing only the source table would leave the other one silently wrong.
// The notice names the command that refreshes the numbers the operator was
// actually looking at, so the recovery step matches the table they used.
func invalidateResumeRowBindings(state *interactiveState, source string, out io.Writer) error {
	state.history = nil
	state.Rows = nil
	command := resumeSourceList
	if source == resumeSourceHistory {
		command = resumeSourceHistory
	}
	_, err := fmt.Fprintf(out, "%s row numbers are stale after resume; run %s to refresh\n", command, command)
	return err
}
