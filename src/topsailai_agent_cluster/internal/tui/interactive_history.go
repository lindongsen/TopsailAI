package tui

import (
	"context"
	"encoding/json"
	"fmt"
	"io"
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
	result, err := querier.GetHistory(ctx, endpointID)
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
// mandatory and is resolved through the same resolver the standalone command uses.
func historyEndpointID(ctx context.Context, api InteractiveAPI, state *interactiveState, target string) (string, error) {
	if state.Scope.Kind == ScopeEndpoint {
		if target != "" && target != state.Scope.EndpointID {
			return "", fmt.Errorf("history %q does not match the current endpoint %q; run cd .. to query another endpoint", target, state.Scope.EndpointID)
		}
		return state.Scope.EndpointID, nil
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
func cdHistoryRowNumber(state *interactiveState, api InteractiveAPI, parent context.Context, number int) error {
	namespace := state.history
	if namespace == nil {
		return fmt.Errorf("no history table is available for row navigation; run history first")
	}
	row, ok := namespace.Rows[number]
	if !ok {
		return fmt.Errorf("row %d is out of range; valid history rows are 1-%d", number, len(namespace.Rows))
	}
	if !row.Joined {
		return fmt.Errorf("history row %d is unjoined: the inventory for endpoint %q is unavailable, so the row cannot be entered; run refresh and history again", number, namespace.EndpointID)
	}
	if !row.Live {
		return fmt.Errorf("history row %d is not live on endpoint %q, so it cannot be entered; use resume %d to resume it", number, namespace.EndpointID, number)
	}
	// The join supplies the only routable pair. An empty pair means the join
	// could not prove a live session, so the transition must fail closed.
	if row.ResourceID == "" || row.Generation == "" {
		return fmt.Errorf("history row %d has no routable identity; run history again", number)
	}
	sessionRow := SessionRow{No: row.No, EndpointID: row.EndpointID, SessionID: row.ResourceID, ProviderSessionID: row.ProviderSessionID, Generation: row.Generation, State: row.State}
	return cdSessionRow(state, api, parent, number, sessionRow)
}

// interactiveResume resumes one stopped history row by its row number.
//
// Resume authorizes on the absence of the target, so it addresses the opaque
// resource handle the Endpoint minted for the provider session and carries no
// generation. A live row is rejected because it is already running, and a row the
// adapter did not mark resumable is rejected with the adapter's own reason.
func interactiveResume(parent context.Context, api InteractiveAPI, state *interactiveState, rest string, lines <-chan lineReadResult, out, trustedOut io.Writer, options InteractiveOptions) error {
	if err := rejectInteractiveOption("resume", rest); err != nil {
		return err
	}
	token := strings.TrimSpace(rest)
	if token == "" {
		return fmt.Errorf("usage: resume <row-number>")
	}
	namespace := state.history
	if namespace == nil {
		return fmt.Errorf("resume requires a history row; run history first")
	}
	number, numeric := parseRowNumber(token)
	if !numeric {
		return fmt.Errorf("resume accepts a history row number only; run history to see the rows")
	}
	row, ok := namespace.Rows[number]
	if !ok {
		return fmt.Errorf("row %d is out of range; valid history rows are 1-%d", number, len(namespace.Rows))
	}
	if row.Live {
		return fmt.Errorf("history row %d is live on endpoint %q, so it cannot be resumed; use cd %d to enter it", number, namespace.EndpointID, number)
	}
	if !row.Resumable {
		reason := row.ResumeBlockedReason
		if reason == "" {
			reason = protocol.ResumeBlockedRecordIncomplete
		}
		return fmt.Errorf("history row %d is not resumable: %s", number, reason)
	}
	if row.ResumeResourceID == "" {
		return fmt.Errorf("history row %d has no resource handle, so it cannot be resumed; run history again", number)
	}
	// The pinned selection is detached because resume outside session scope is not
	// the current selection. The shared confirmation path records the command ID on
	// that copy, so it is copied back before the caller can query status.
	pinned := *state
	pinned.EndpointID = namespace.EndpointID
	pinned.SessionID = row.ResumeResourceID
	pinned.Generation = ""
	pinned.Invalidated = false
	pinned.InvalidReason = ""
	revalidate := func(revalidateCtx context.Context) error {
		return validateResumeAbsence(revalidateCtx, api, namespace.EndpointID, row.ProviderSessionID)
	}
	postSubmit := func(postCtx context.Context, result map[string]any) error {
		state.commandID = pinned.commandID
		return invalidateHistoryRowBindings(state, out)
	}
	target := confirmationTarget{ProviderSessionID: row.ProviderSessionID, SessionID: row.ResumeResourceID}
	return interactiveConfirmedAction(parent, api, &pinned, protocol.OperationAgentResume, "resume", target, "", json.RawMessage(`{}`), lines, out, trustedOut, options, revalidate, postSubmit)
}

// validateResumeAbsence proves from the current inventory that the provider
// session is still absent, so a stale history row can never resume a session that
// has since started. The Endpoint repeats this check against the provider's own
// answer before it invokes the provider, so this is a client-side guard, not the
// authority.
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
		return fmt.Errorf("endpoint %q inventory is unavailable, so the absence of session %q cannot be proven", endpointID, providerSessionID)
	}
	for _, session := range report.Sessions {
		if session.ProviderSessionID != "" && session.ProviderSessionID == providerSessionID {
			return fmt.Errorf("session %q is live on endpoint %q, so it cannot be resumed; use cd to enter it", providerSessionID, endpointID)
		}
	}
	return nil
}

// invalidateHistoryRowBindings drops the history row numbers rendered before the
// resume, because the resumed session may become live and a stale number would
// then name a different row after the next history render.
func invalidateHistoryRowBindings(state *interactiveState, out io.Writer) error {
	state.history = nil
	_, err := fmt.Fprintln(out, "history row numbers are stale after resume; run history to refresh")
	return err
}
