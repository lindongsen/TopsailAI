package tui

import (
	"context"
	"io"
	"sort"
	"strconv"
	"strings"
	"time"

	"topsailai_agent_cluster/internal/protocol"
)

// Endpoint column keys name one logical field, so a layout change cannot
// silently shift colours or alignment.
const (
	columnEndpointID         = "endpoint_id"
	columnHostname           = "hostname"
	columnDisplayName        = "display_name"
	columnConnectionState    = "connection_state"
	columnObservedAt         = "observed_at"
	columnCapabilityRevision = "capability_revision"
)

// endpointColumns is the complete endpoint layout. Connection state is a
// different domain from session state, so it keeps its own column and colour
// mapping instead of reusing the session table.
var endpointColumns = []tableColumn{
	{key: columnEndpointID, header: "ENDPOINT_ID", cap: 36},
	{key: columnHostname, header: "HOSTNAME", cap: 40},
	{key: columnDisplayName, header: "DISPLAY_NAME", cap: 40},
	{key: columnConnectionState, header: "CONNECTION_STATE", cap: 14},
	{key: columnObservedAt, header: "OBSERVED_AT", cap: 10},
	{key: columnCapabilityRevision, header: "CAPABILITY_REVISION", cap: 24},
}

// connectionStateOrder fixes the summary precedence so output is deterministic.
var connectionStateOrder = []string{"online", "suspect", "offline", "unknown"}

// Endpoints lists every registered endpoint with its reported details.
func (r CommandRunner) Endpoints(ctx context.Context, out io.Writer, filter string, jsonMode bool, options TableOptions) error {
	endpoints, err := r.API.ListEndpoints(ctx)
	if err != nil {
		return err
	}
	return RenderEndpoints(out, endpoints, filter, jsonMode, options)
}

// RenderEndpoints renders the endpoint projection. JSON mode emits the complete
// reported endpoint objects, so no detail is lost to presentation columns.
func RenderEndpoints(out io.Writer, endpoints []protocol.Endpoint, filter string, jsonMode bool, options TableOptions) error {
	selected := selectEndpoints(endpoints, filter)
	if jsonMode {
		return RenderJSON(out, selected)
	}
	headers := columnHeaders(endpointColumns)
	cells := make([][]string, len(selected))
	states := make([][]string, len(selected))
	rowStyles := make([]string, len(selected))
	for i, endpoint := range selected {
		cells[i] = projectCells(endpointCells(endpoint, options.Location), endpointColumns)
		states[i] = endpointStates(endpoint, endpointColumns)
		rowStyles[i] = connectionStateStyle(endpoint.ConnectionState)
	}
	widths := measureColumns(cells, endpointColumns, options.Full)
	if err := writeTable(out, headers, cells, states, rowStyles, widths, endpointColumns, options); err != nil {
		return err
	}
	if len(selected) > 0 {
		return writeEndpointSummary(out, selected, options.Color)
	}
	_, err := io.WriteString(out, "no endpoints\n")
	return err
}

// selectEndpoints applies the optional endpoint ID filter and sorts by ID, so
// the output order never depends on the Server's map iteration.
func selectEndpoints(endpoints []protocol.Endpoint, filter string) []protocol.Endpoint {
	selected := make([]protocol.Endpoint, 0, len(endpoints))
	for _, endpoint := range endpoints {
		if filter != "" && endpoint.EndpointID != filter {
			continue
		}
		selected = append(selected, endpoint)
	}
	sort.Slice(selected, func(i, j int) bool { return selected[i].EndpointID < selected[j].EndpointID })
	return selected
}

// endpointCells returns every column value keyed by column key.
func endpointCells(endpoint protocol.Endpoint, location *time.Location) map[string]string {
	return map[string]string{
		columnEndpointID:         escapeCell(endpoint.EndpointID),
		columnHostname:           escapeCell(orDash(endpoint.Hostname)),
		columnDisplayName:        escapeCell(orDash(endpoint.DisplayName)),
		columnConnectionState:    escapeCell(orDash(endpoint.ConnectionState)),
		columnObservedAt:         escapeCell(formatObservedAt(endpoint.ObservedAtMS, location)),
		columnCapabilityRevision: escapeCell(orDash(endpoint.CapabilityRevision)),
	}
}

// endpointStates colours every cell of a row with the endpoint connection state,
// because the row is rendered as one unit.
func endpointStates(endpoint protocol.Endpoint, columns []tableColumn) []string {
	state := endpoint.ConnectionState
	if state == "" {
		state = "unknown"
	}
	states := make([]string, len(columns))
	for i := range columns {
		states[i] = state
	}
	return states
}

// orDash renders an unreported value as "-" instead of an empty cell.
func orDash(value string) string {
	if value == "" {
		return "-"
	}
	return value
}

// formatObservedAt renders the last observation time, or "-" when the endpoint
// has never reported one.
func formatObservedAt(value int64, location *time.Location) string {
	if value <= 0 {
		return "-"
	}
	if location == nil {
		location = time.Local
	}
	return time.UnixMilli(value).In(location).Format("15:04:05")
}

// connectionStateStyle is the single connection-state-to-colour mapping shared by
// the endpoint table and its summary line.
func connectionStateStyle(state string) string {
	switch state {
	case "online":
		return ansiGreen
	case "offline":
		return ansiRed
	default:
		return ansiYellow
	}
}

// connectionStateCounts tallies endpoints by connection state in a deterministic
// order, reusing the statusCount pair so both summaries stay uniform.
func connectionStateCounts(endpoints []protocol.Endpoint) []statusCount {
	tally := make(map[string]int, len(endpoints))
	for _, endpoint := range endpoints {
		state := endpoint.ConnectionState
		if state == "" {
			state = "unknown"
		}
		tally[state]++
	}
	counts := make([]statusCount, 0, len(tally))
	seen := make(map[string]bool, len(tally))
	for _, state := range connectionStateOrder {
		if count, ok := tally[state]; ok {
			counts = append(counts, statusCount{State: state, Count: count})
			seen[state] = true
		}
	}
	// Unrecognized states stay visible, sorted so the summary never reorders.
	rest := make([]string, 0, len(tally))
	for state := range tally {
		if !seen[state] {
			rest = append(rest, state)
		}
	}
	sort.Strings(rest)
	for _, state := range rest {
		counts = append(counts, statusCount{State: state, Count: tally[state]})
	}
	return counts
}

// writeEndpointSummary renders "online(2) | offline(1)" below the table,
// colouring each state with the same mapping the table rows use.
func writeEndpointSummary(out io.Writer, endpoints []protocol.Endpoint, policy ColorPolicy) error {
	for i, count := range connectionStateCounts(endpoints) {
		if i > 0 {
			if err := writeStyled(out, ansiDim, " | ", policy); err != nil {
				return err
			}
		}
		label := count.State + "(" + strconv.Itoa(count.Count) + ")"
		if err := writeStyled(out, connectionStateStyle(count.State), label, policy); err != nil {
			return err
		}
	}
	_, err := io.WriteString(out, "\n")
	return err
}

// interactiveEndpoints lists endpoints in workspace scope. It is read-only, so it
// never forces provider discovery and never changes the session row bindings.
func interactiveEndpoints(parent context.Context, api InteractiveAPI, rest string, out io.Writer, color ColorPolicy) error {
	if err := rejectInteractiveOption("endpoints", rest); err != nil {
		return err
	}
	ctx, cancel := commandContext(parent)
	defer cancel()
	return (CommandRunner{API: api, Policy: InteractivePolicy}).Endpoints(ctx, out, strings.TrimSpace(rest), false, tableOptionsFor(out, color, listArguments{}, nil))
}
