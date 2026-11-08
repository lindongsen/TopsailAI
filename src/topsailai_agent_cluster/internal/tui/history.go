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

// HistoryQuerier reads bounded provider session history for one Endpoint.
//
// History is a live provider read, so this seam never returns a persisted
// projection and never caches a result.
type HistoryQuerier interface {
	GetHistory(context.Context, string) (protocol.HistoryResult, error)
}

// HistoryViewRow is one rendered history row: provider evidence plus the cluster
// join against the persisted inventory.
//
// The join fields are the only way a history row can become routable. A row that
// could not be joined carries Joined=false and no resource ID or generation, so a
// caller can never mistake it for a routable resource.
type HistoryViewRow struct {
	No                  int    `json:"no"`
	EndpointID          string `json:"endpoint_id"`
	ProviderSessionID   string `json:"provider_session_id"`
	DisplayName         string `json:"display_name,omitempty"`
	ProjectWorkspace    string `json:"project_workspace,omitempty"`
	Task                string `json:"task,omitempty"`
	ProviderStatus      string `json:"provider_status,omitempty"`
	ProviderNo          int    `json:"provider_no,omitempty"`
	CreatedAtMS         int64  `json:"created_at_ms,omitempty"`
	ModifiedAtMS        int64  `json:"modified_at_ms,omitempty"`
	Resumable           bool   `json:"resumable"`
	ResumeBlockedReason string `json:"resume_blocked_reason,omitempty"`
	// Joined reports whether the inventory join could be evaluated at all. A
	// false value means the row is unknown, never that it is stopped.
	Joined bool `json:"joined"`
	// Ambiguous reports that the join was evaluated but found several live
	// sessions sharing one provider session ID. It is a different unknown from an
	// unavailable inventory: the inventory answered, and its answer was
	// contradictory. The two are kept apart so a caller never tells the operator
	// to refresh data that a refresh cannot disambiguate.
	Ambiguous bool `json:"ambiguous,omitempty"`
	// Live reports whether the same provider session is present in the current
	// inventory for this endpoint. Only a live row can be entered.
	Live bool `json:"live"`
	// ResourceID and Generation are supplied only by the join. They are empty for
	// every non-live row, because a past session has no generation to validate.
	ResourceID string `json:"resource_id,omitempty"`
	Generation string `json:"generation,omitempty"`
	// ResumeResourceID is the opaque cluster handle the Endpoint minted for this
	// provider session. It exists so a resume request can address a stopped row
	// without naming a provider key or an adapter. It is never a routing
	// identity: routing requires resource_id + generation, and a stopped row has
	// no generation, so resume authorizes on the provider's proven absence.
	ResumeResourceID string `json:"resume_resource_id,omitempty"`
	State            string `json:"state,omitempty"`
}

// HistoryView is one rendered history table.
//
// Truncated reports that the provider returned its own capped window. It is
// surfaced so a bounded window is never presented as a complete history.
type HistoryView struct {
	EndpointID   string           `json:"endpoint_id"`
	Rows         []HistoryViewRow `json:"rows"`
	ObservedAtMS int64            `json:"observed_at_ms,omitempty"`
	Truncated    bool             `json:"truncated,omitempty"`
	// Joined reports whether the inventory was available for correlation. When it
	// was not, every row is unjoined rather than assumed stopped.
	Joined bool `json:"joined"`
}

// JoinHistory correlates provider history rows with one endpoint's persisted
// inventory.
//
// The join key is (endpoint_id, provider_session_id). It is never the bare
// provider session ID, because that value may be duplicated across endpoints, and
// it is never a cluster resource ID, because a history row has none. The join is a
// pure function of the two inputs: it performs no network call and no provider
// call.
//
// A provider session ID that matches more than one live session inside the same
// endpoint is ambiguous, so the row is left unjoined instead of picking one and is
// marked Ambiguous. A missing inventory leaves every row unjoined, because an
// unavailable observation is unknown, not an empty inventory. The two outcomes are
// reported separately because they need different remedies: an unavailable
// inventory can be refreshed, while contradictory inventory data cannot.
func JoinHistory(endpointID string, rows []protocol.HistoryRow, report protocol.InventoryReport, inventoryAvailable bool) HistoryView {
	view := HistoryView{EndpointID: endpointID, Rows: make([]HistoryViewRow, 0, len(rows)), Joined: inventoryAvailable}
	live := make(map[string][]protocol.Session, len(report.Sessions))
	if inventoryAvailable {
		for _, session := range report.Sessions {
			if session.ProviderSessionID == "" {
				continue
			}
			live[session.ProviderSessionID] = append(live[session.ProviderSessionID], session)
		}
	}
	for _, row := range rows {
		viewRow := HistoryViewRow{
			EndpointID:          endpointID,
			ProviderSessionID:   row.ProviderSessionID,
			DisplayName:         row.DisplayName,
			ProjectWorkspace:    row.ProjectWorkspace,
			Task:                row.Task,
			ProviderStatus:      row.ProviderStatus,
			ProviderNo:          row.ProviderNo,
			CreatedAtMS:         row.CreatedAtMS,
			ModifiedAtMS:        row.ModifiedAtMS,
			Resumable:           row.Resumable,
			ResumeBlockedReason: row.ResumeBlockedReason,
			// The Endpoint minted this handle for the provider session, so it
			// addresses the row even when the session is not running. It is
			// copied verbatim and never derived from the inventory join.
			ResumeResourceID: row.ResourceID,
		}
		if inventoryAvailable && row.ProviderSessionID != "" {
			// Exactly one live match is a usable join. Several matches are
			// ambiguous, so the row stays unjoined rather than being guessed, and
			// the ambiguity is recorded so the caller can report the real cause.
			if matches := live[row.ProviderSessionID]; len(matches) == 1 {
				viewRow.Joined = true
				viewRow.Live = true
				viewRow.ResourceID = matches[0].SessionID
				viewRow.Generation = matches[0].Generation
				viewRow.State = matches[0].State
			} else if len(matches) == 0 {
				viewRow.Joined = true
			} else {
				viewRow.Ambiguous = true
			}
		}
		view.Rows = append(view.Rows, viewRow)
	}
	assignHistoryRowNumbers(view.Rows)
	return view
}

// assignHistoryRowNumbers binds row numbers to one rendered history view.
func assignHistoryRowNumbers(rows []HistoryViewRow) {
	for index := range rows {
		rows[index].No = index + 1
	}
}

// historyColumns is the history table layout. It is deliberately separate from
// the session table, because a history row has no generation and no data-status
// stamp, and reusing the session columns would imply fields it does not have.
var historyColumns = []tableColumn{
	{key: columnNo, header: "NO", cap: 4},
	{key: "provider_status", header: "PROVIDER_STATUS", cap: 16},
	{key: columnName, header: "SESSION_NAME", cap: 64, wide: true},
	{key: columnID, header: "SESSION_ID", cap: 36},
	{key: columnWorkspace, header: "PROJECT_WORKSPACE", cap: 48, leftClip: true},
	{key: "live", header: "LIVE", cap: 8},
	{key: "resumable", header: "RESUMABLE", cap: 24, warn: true},
}

// historyCells renders one history row into the keyed layout.
func historyCells(row HistoryViewRow) map[string]string {
	return map[string]string{
		columnNo:          strconv.Itoa(row.No),
		"provider_status": escapeCell(row.ProviderStatus),
		columnName:        escapeCell(row.DisplayName),
		columnID:          escapeCell(row.ProviderSessionID),
		columnWorkspace:   escapeCell(row.ProjectWorkspace),
		"live":            historyLiveCell(row),
		"resumable":       escapeCell(historyResumableCell(row)),
	}
}

// historyLiveCell states the join outcome without implying a stopped session.
//
// An ambiguous row is labelled separately from an unjoined row, because the two
// tell the operator different things: "unjoined" means the inventory could not be
// read, while "ambiguous" means it was read and contradicted itself.
func historyLiveCell(row HistoryViewRow) string {
	if row.Ambiguous {
		return "ambiguous"
	}
	if !row.Joined {
		return "unjoined"
	}
	if row.Live {
		return "yes"
	}
	return "no"
}

// historyResumableCell states the adapter verdict and its standard reason.
func historyResumableCell(row HistoryViewRow) string {
	if row.Resumable {
		return "yes"
	}
	if row.ResumeBlockedReason == "" {
		return "no"
	}
	return "no (" + row.ResumeBlockedReason + ")"
}

// RenderHistory writes one bounded history table.
func RenderHistory(out io.Writer, view HistoryView, options TableOptions) error {
	columns := historyColumns
	headers := columnHeaders(columns)
	cells := make([][]string, len(view.Rows))
	states := make([][]string, len(view.Rows))
	rowStyles := make([]string, len(view.Rows))
	for i, row := range view.Rows {
		values := historyCells(row)
		cells[i] = projectCells(values, columns)
		states[i] = make([]string, len(columns))
		for j, column := range columns {
			if column.key == "resumable" {
				states[i][j] = historyResumableState(row)
				continue
			}
			states[i][j] = "ok"
		}
		rowStyles[i] = stateStyle(historyResumableState(row))
	}
	widths := measureColumns(cells, columns, options.Full)
	return writeTable(out, headers, cells, states, rowStyles, widths, columns, options)
}

// historyResumableState maps the adapter verdict to a colour state.
func historyResumableState(row HistoryViewRow) string {
	if row.Resumable {
		return "ok"
	}
	return "failed"
}

// History renders bounded provider session history for one endpoint.
//
// The endpoint argument is mandatory on the standalone surface, because a history
// query is endpoint-scoped: fanning out across endpoints would multiply provider
// calls and would mix rows whose provider session IDs may collide.
func (r CommandRunner) History(ctx context.Context, out, errors io.Writer, target string, jsonMode bool, options TableOptions) error {
	querier, ok := r.API.(HistoryQuerier)
	if !ok {
		return fmt.Errorf("history is unavailable: this client cannot query provider history")
	}
	endpoint, err := resolveHistoryEndpoint(ctx, r.API, target)
	if err != nil {
		return err
	}
	result, err := querier.GetHistory(ctx, endpoint.EndpointID)
	if err != nil {
		return err
	}
	if result.ErrorCode != "" {
		return fmt.Errorf("history for endpoint %q failed: %s", endpoint.EndpointID, result.ErrorCode)
	}
	report, inventoryErr := r.API.GetInventory(ctx, endpoint.EndpointID)
	view := JoinHistory(endpoint.EndpointID, result.Rows, report, inventoryErr == nil)
	view.ObservedAtMS = result.ObservedAtMS
	view.Truncated = result.Truncated
	if jsonMode {
		return RenderJSON(out, view)
	}
	if inventoryErr != nil {
		if _, err := fmt.Fprintf(errors, "history rows are unjoined: inventory for endpoint %q is unavailable: %v\n", endpoint.EndpointID, inventoryErr); err != nil {
			return err
		}
	}
	if view.Truncated {
		if _, err := fmt.Fprintln(errors, "history is a bounded provider window; older sessions are not listed"); err != nil {
			return err
		}
	}
	return RenderHistory(out, view, options)
}

// resolveHistoryEndpoint resolves an endpoint ID or a unique hostname.
//
// A hostname shared by several endpoints is rejected with the candidate list
// instead of picking one, because the operator asked for a specific machine and a
// silent choice would query the wrong provider.
func resolveHistoryEndpoint(ctx context.Context, api CommandAPI, target string) (protocol.Endpoint, error) {
	if strings.TrimSpace(target) == "" {
		return protocol.Endpoint{}, fmt.Errorf("usage: history <endpoint-id-or-hostname>")
	}
	endpoints, err := api.ListEndpoints(ctx)
	if err != nil {
		return protocol.Endpoint{}, err
	}
	for _, endpoint := range endpoints {
		if endpoint.EndpointID == target {
			return endpoint, nil
		}
	}
	matches := make([]protocol.Endpoint, 0, 2)
	for _, endpoint := range endpoints {
		if endpoint.Hostname != "" && endpoint.Hostname == target {
			matches = append(matches, endpoint)
		}
	}
	switch len(matches) {
	case 0:
		return protocol.Endpoint{}, fmt.Errorf("endpoint %q was not found", target)
	case 1:
		return matches[0], nil
	}
	sort.Slice(matches, func(i, j int) bool { return matches[i].EndpointID < matches[j].EndpointID })
	ids := make([]string, len(matches))
	for i, endpoint := range matches {
		ids[i] = endpoint.EndpointID
	}
	return protocol.Endpoint{}, fmt.Errorf("hostname %q matches several endpoints (%s); pass the endpoint ID instead", target, strings.Join(ids, ", "))
}
