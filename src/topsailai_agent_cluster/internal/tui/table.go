package tui

import (
	"fmt"
	"io"
	"sort"
	"strconv"
	"strings"
	"time"
	"unicode/utf8"
)

// EndpointFailure identifies an endpoint whose inventory could not be observed.
type EndpointFailure struct {
	EndpointID string
	Err        error
}

// TableOptions controls table presentation without changing query semantics.
type TableOptions struct {
	// Width bounds terminal columns; zero preserves the full table.
	Width  int
	Color  ColorPolicy
	Clean  bool
	OnRows func([]SessionRow)
	// Location formats the DATA_STATUS success stamp; nil means the local timezone.
	Location *time.Location
}

// Column keys name one logical field so a layout change cannot silently shift
// colours, alignment, or the DATA_STATUS warning.
const (
	columnNo         = "no"
	columnState      = "state"
	columnName       = "name"
	columnID         = "id"
	columnEndpoint   = "endpoint"
	columnDataStatus = "data_status"
)

// tableColumn describes one column: its header, its width cap, whether it is
// never truncated, and whether it keeps its own warning colour.
type tableColumn struct {
	key    string
	header string
	cap    int
	wide   bool
	warn   bool
}

// allColumns is the complete column set. SESSION_STATUS is dropped when the row
// colour already carries the state, because the column would only repeat it.
var allColumns = []tableColumn{
	{key: columnNo, header: "NO", cap: 4},
	{key: columnState, header: "SESSION_STATUS", cap: 14},
	{key: columnName, header: "SESSION_NAME", cap: 64, wide: true},
	{key: columnID, header: "SESSION_ID", cap: 36},
	{key: columnEndpoint, header: "ENDPOINT", cap: 20},
	{key: columnDataStatus, header: "DATA_STATUS", cap: 35, warn: true},
}

// columnsFor returns the columns to render for one output capability. Colour
// already shows the state on every cell of the row, so SESSION_STATUS is omitted
// there; without colour it stays, because it is then the only per-row state
// signal.
func columnsFor(policy ColorPolicy) []tableColumn {
	if !policy.Enabled {
		return allColumns
	}
	columns := make([]tableColumn, 0, len(allColumns)-1)
	for _, column := range allColumns {
		if column.key == columnState {
			continue
		}
		columns = append(columns, column)
	}
	return columns
}

// columnHeaders returns the header text of one layout.
func columnHeaders(columns []tableColumn) []string {
	headers := make([]string, len(columns))
	for i, column := range columns {
		headers[i] = column.header
	}
	return headers
}

// columnWidths starts every column at its header width, so a short value never
// widens the table beyond its content.
func columnWidths(columns []tableColumn) []int {
	widths := make([]int, len(columns))
	for i, column := range columns {
		widths[i] = displayWidth(column.header)
	}
	return widths
}

// tableHeaders lists the plain layout headers, used by callers that render
// without colour such as help and redirected output.
var tableHeaders = columnHeaders(allColumns)

// minimumTableWidth reports the smallest width able to hold one column per field.
func minimumTableWidth(columns int) int {
	return 3*(columns-1) + columns
}

// RenderTable writes a bounded table and sorted endpoint diagnostics.
func RenderTable(out, errors io.Writer, rows []SessionRow, failures []EndpointFailure, options TableOptions) error {
	assignRowNumbers(rows)
	columns := columnsFor(options.Color)
	headers := columnHeaders(columns)
	widths := columnWidths(columns)
	cells := make([][]string, len(rows))
	states := make([][]string, len(rows))
	rowStyles := make([]string, len(rows))
	for i, row := range rows {
		cells[i] = projectCells(tableCells(row, options.Location), columns)
		states[i] = tableStates(row, columns)
		rowStyles[i] = stateStyle(rowState(row))
		for j, cell := range cells[i] {
			n := displayWidth(cell)
			if columns[j].wide {
				// Session names are shown in full so a long name is never truncated.
				if n > widths[j] {
					widths[j] = n
				}
				continue
			}
			if n > widths[j] {
				widths[j] = minInt(n, columns[j].cap)
			}
		}
	}
	fitTableWidths(widths, options.Width)
	writeRow := func(values, states []string, rowStyle string, header bool) error {
		for i, value := range values {
			if i > 0 {
				if err := writeStyled(out, rowStyle, " │ ", options.Color); err != nil {
					return err
				}
			}
			cell := clipCell(value, widths[i])
			cell += strings.Repeat(" ", widths[i]-displayWidth(cell))
			if header {
				if err := writeStyled(out, ansiBoldCyan, cell, options.Color); err != nil {
					return err
				}
				continue
			}
			state := ""
			if len(states) > i {
				state = states[i]
			}
			if err := writeCellState(out, cell, columns[i].warn, state, rowStyle, options.Color); err != nil {
				return err
			}
		}
		_, err := io.WriteString(out, "\n")
		return err
	}
	writeSeparator := func() error {
		for i, width := range widths {
			if i > 0 {
				if _, err := io.WriteString(out, "─┼─"); err != nil {
					return err
				}
			}
			if _, err := io.WriteString(out, strings.Repeat("─", width)); err != nil {
				return err
			}
		}
		_, err := io.WriteString(out, "\n")
		return err
	}
	// writeRule draws the full-width horizontal rule that frames the table.
	writeRule := func() error {
		total := 3 * (len(widths) - 1)
		for _, width := range widths {
			total += width
		}
		_, err := io.WriteString(out, strings.Repeat("─", total)+"\n")
		return err
	}
	if options.Width > 0 && options.Width < minimumTableWidth(len(widths)) {
		if err := writeNarrowTable(out, cells, states, rowStyles, columns, options.Width, options.Color); err != nil {
			return err
		}
	} else {
		if err := writeRule(); err != nil {
			return err
		}
		if err := writeRow(headers, nil, "", true); err != nil {
			return err
		}
		if err := writeSeparator(); err != nil {
			return err
		}
		for index, row := range cells {
			if err := writeRow(row, states[index], rowStyles[index], false); err != nil {
				return err
			}
		}
		if err := writeRule(); err != nil {
			return err
		}
	}
	if len(rows) > 0 {
		if err := writeStatusSummary(out, rows, options.Color); err != nil {
			return err
		}
	}
	if len(rows) == 0 {
		if len(failures) == 0 {
			if _, err := io.WriteString(out, "no sessions\n"); err != nil {
				return err
			}
		} else if _, err := io.WriteString(out, "no sessions available; partial failure\n"); err != nil {
			return err
		}
	}
	sort.Slice(failures, func(i, j int) bool { return failures[i].EndpointID < failures[j].EndpointID })
	for _, failure := range failures {
		if _, err := fmt.Fprintf(errors, "endpoint %s unavailable: %s\n", escapeCell(failure.EndpointID), sanitizeTerminal([]byte(failure.Err.Error()))); err != nil {
			return err
		}
	}
	return nil
}

// statusOrder fixes the summary precedence so output is deterministic.
var statusOrder = []string{"running", "waiting_input", "idle", "ready", "stopped", "completed", "failed", "error", "offline", "unknown"}

// statusCount pairs one observed SESSION_STATUS with its row count.
type statusCount struct {
	State string
	Count int
}

// statusCounts tallies rows by state in a deterministic order.
func statusCounts(rows []SessionRow) []statusCount {
	tally := make(map[string]int, len(rows))
	for _, row := range rows {
		state := row.State
		if state == "" {
			state = "unknown"
		}
		tally[state]++
	}
	counts := make([]statusCount, 0, len(tally))
	seen := make(map[string]bool, len(tally))
	for _, state := range statusOrder {
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

// writeStatusSummary renders "running(3) | input(2)" below the table, colouring
// each state with the same mapping the SESSION_STATUS column uses.
func writeStatusSummary(out io.Writer, rows []SessionRow, policy ColorPolicy) error {
	counts := statusCounts(rows)
	if len(counts) == 0 {
		return nil
	}
	for i, count := range counts {
		if i > 0 {
			if err := writeStyled(out, ansiDim, " | ", policy); err != nil {
				return err
			}
		}
		label := statusSummaryLabel(count.State) + "(" + strconv.Itoa(count.Count) + ")"
		if err := writeStyled(out, stateStyle(count.State), label, policy); err != nil {
			return err
		}
	}
	_, err := io.WriteString(out, "\n")
	return err
}

// statusSummaryLabel shortens waiting_input to the operator-facing "input".
func statusSummaryLabel(state string) string {
	if state == "waiting_input" {
		return "input"
	}
	return state
}

// stateStyle is the single state-to-colour mapping shared by the table and the
// summary row, so a state can never be coloured differently in the two places.
func stateStyle(state string) string {
	switch state {
	case "running":
		return ansiGreen
	case "stopped", "completed":
		return ansiDim
	case "failed", "error":
		return ansiRed
	default:
		return ansiYellow
	}
}

// tableCells returns every column value keyed by column key, so a layout can
// select a subset without depending on positional indices.
func tableCells(row SessionRow, location *time.Location) map[string]string {
	endpoint := row.EndpointLabel
	if endpoint == "" {
		endpoint = row.EndpointID
	}
	return map[string]string{
		columnNo:         strconv.Itoa(row.No),
		columnState:      escapeCell(row.State),
		columnName:       escapeCell(row.DisplayName),
		columnID:         escapeCell(row.ProviderSessionID),
		columnEndpoint:   escapeCell(endpoint),
		columnDataStatus: escapeCell(dataStatusCell(row, location)),
	}
}

// projectCells orders the keyed values into one layout.
func projectCells(values map[string]string, columns []tableColumn) []string {
	cells := make([]string, len(columns))
	for i, column := range columns {
		cells[i] = values[column.key]
	}
	return cells
}

// tableStates derives each column's colour state from the row itself, so a
// decorated cell such as "ok (<timestamp>)" keeps the colour of its base status.
func tableStates(row SessionRow, columns []tableColumn) []string {
	states := make([]string, len(columns))
	for i, column := range columns {
		if column.warn {
			states[i] = dataStatus(row)
			continue
		}
		states[i] = rowState(row)
	}
	return states
}

// dataStatusCell embeds the latest success stamp in DATA_STATUS.
func dataStatusCell(row SessionRow, location *time.Location) string {
	base := dataStatus(row)
	stamp := formatLastSuccess(row.LastSuccessAtMS, location)
	if stamp == "-" {
		return base
	}
	return base + " (" + stamp + ")"
}

// formatLastSuccess renders a millisecond timestamp in the given location.
func formatLastSuccess(value *int64, location *time.Location) string {
	if value == nil {
		return "-"
	}
	if location == nil {
		location = time.Local
	}
	return time.UnixMilli(*value).In(location).Format("15:04:05")
}
func escapeCell(value string) string {
	clean := sanitizeTerminal([]byte(value))
	clean = strings.NewReplacer("\n", "�", "\r", "�", "\t", "�").Replace(clean)
	return strings.ReplaceAll(clean, "\\", "\\\\")
}
func clipCell(value string, width int) string {
	if displayWidth(value) <= width {
		return value
	}
	if width <= 3 {
		return strings.Repeat(".", width)
	}
	return value[:safeClipIndex(value, width-3)] + "..."
}
func safeClipIndex(value string, limit int) int {
	used := 0
	for i, r := range value {
		runeWidth := runeDisplayWidth(r)
		if used+runeWidth > limit {
			return i
		}
		used += runeWidth
	}
	return len(value)
}
func displayWidth(value string) int {
	width := 0
	for _, r := range value {
		width += runeDisplayWidth(r)
	}
	return width
}
func runeDisplayWidth(value rune) int {
	if value == 0 || value == utf8.RuneError || value == '\u200b' || value == '\u200c' || value == '\u200d' || value == '\u2060' {
		return 0
	}
	if value >= 0x300 && value <= 0x36f {
		return 0
	}
	if (value >= 0x1100 && value <= 0x115f) || (value >= 0x2329 && value <= 0x232a) ||
		(value >= 0x2e80 && value <= 0xa4cf) || (value >= 0xac00 && value <= 0xd7a3) ||
		(value >= 0xf900 && value <= 0xfaff) || (value >= 0xfe10 && value <= 0xfe19) ||
		(value >= 0xfe30 && value <= 0xfe6f) || (value >= 0xff00 && value <= 0xff60) ||
		(value >= 0xffe0 && value <= 0xffe6) || (value >= 0x1f300 && value <= 0x1faff) {
		return 2
	}
	return 1
}
func minInt(a, b int) int {
	if a < b {
		return a
	}
	return b
}

// rowState reports the provider-reported lifecycle state that colours one row.
func rowState(row SessionRow) string {
	return row.State
}

// dataStatus combines collection outcome and data freshness for table display.
func dataStatus(row SessionRow) string {
	base := "unrecognized"
	switch row.CollectionStatus {
	case "succeeded":
		base = "ok"
	case "failed", "partial", "unknown":
		base = row.CollectionStatus
	}
	if row.Unknown && row.Stale {
		return base + "/unknown+stale"
	}
	if row.Unknown {
		return base + "/unknown"
	}
	if row.Stale {
		return base + "/stale"
	}
	return base
}

// writeCellState writes one cell with the row's colour. A data row is coloured
// as a whole from its session state, so every cell and separator of that row
// shares one style; a warning column keeps its own colour when it reports a
// collection problem, because that signal must stay visible on a healthy row.
func writeCellState(w io.Writer, cell string, warn bool, state, rowStyle string, policy ColorPolicy) error {
	if !policy.Enabled {
		_, err := io.WriteString(w, cell)
		return err
	}
	if warn {
		switch {
		case state == "ok":
			return writeStyled(w, rowStyle, cell, policy)
		case strings.HasPrefix(state, "failed"):
			return writeStyled(w, ansiRed, cell, policy)
		default:
			return writeStyled(w, ansiYellow, cell, policy)
		}
	}
	return writeStyled(w, rowStyle, cell, policy)
}

func assignRowNumbers(rows []SessionRow) {
	for index := range rows {
		rows[index].No = index + 1
	}
}
