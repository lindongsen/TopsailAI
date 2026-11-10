package tui

import (
	"fmt"
	"io"
	"sort"
	"strconv"
	"strings"
	"time"
	"unicode/utf8"

	"topsailai_agent_cluster/internal/protocol"
)

// EndpointFailure identifies an endpoint whose inventory could not be observed.
type EndpointFailure struct {
	EndpointID string
	Err        error
}

// TableOptions controls table presentation without changing query semantics.
type TableOptions struct {
	// Width bounds terminal columns; zero preserves the full table.
	Width int
	// Full disables every truncation: the width bound and the per-column caps.
	// A narrow terminal then wraps instead of losing data.
	Full bool
	// Grow lets a growable column spend the width the table does not need, so a
	// value is printed in full when the terminal has room for it. It is set only
	// by a real terminal boundary: a redirected stream and an unknown width keep
	// the capped layout, because their width is not a budget that can be spent.
	Grow   bool
	Color  ColorPolicy
	Clean  bool
	OnRows func([]SessionRow)
	// Location formats the DATA_STATUS success stamp; nil means the local timezone.
	Location *time.Location
	// HideSessionID drops the SESSION_ID column from the rendered layout. It is an
	// interactive presentation choice only: the provider session ID stays on the
	// row, so it is still accepted as a command target, but it is not printed.
	HideSessionID bool
	// Brief renders only the columns that identify a row: NO, SESSION_NAME and
	// ENDPOINT. It is a column-set choice, independent of Full, which is a
	// truncation choice, so "brief and untruncated" is a coherent request.
	Brief bool
}

// Column keys name one logical field so a layout change cannot silently shift
// colours, alignment, or the DATA_STATUS warning.
const (
	columnNo         = "no"
	columnState      = "state"
	columnDrive      = "drive"
	columnName       = "name"
	columnID         = "id"
	columnWorkspace  = "workspace"
	columnEndpoint   = "endpoint"
	columnDataStatus = "data_status"
)

// workspaceColumnCap bounds the PROJECT_WORKSPACE column. A workspace path is
// descriptive context, not a selector, so it must not push the fleet table past
// the terminal: 23 display cells keep the identifying tail of a path visible
// while leaving room for the columns that address a row. Both the session and
// the history layouts read this one constant, because two copies of the number
// would drift apart on the next change.
//
// The cap is a default, not a ceiling. A terminal with width to spare grows the
// column back towards the complete path (see growColumns), so a wide screen shows
// the whole value while a narrow one still keeps the identifying tail.
const workspaceColumnCap = 23

// tableColumn describes one column: its header, its width cap, whether it is
// never truncated, whether it keeps its own warning colour, whether it may spend
// spare width, and which end a clipped value keeps.
type tableColumn struct {
	key    string
	header string
	cap    int
	wide   bool
	warn   bool
	// grow marks a column that may widen past its cap into width the table does
	// not need. Only a descriptive column is marked: a selector column must keep
	// a predictable width so the columns that address a row stay aligned.
	grow bool
	// leftClip keeps the tail of an over-wide value instead of its head. A path
	// shares a long prefix with its siblings, so its tail identifies it.
	leftClip bool
}

// allColumns is the complete column set. SESSION_STATUS is dropped when the row
// colour already carries the state, because the column would only repeat it.
var allColumns = []tableColumn{
	{key: columnNo, header: "NO", cap: 4},
	{key: columnState, header: "SESSION_STATUS", cap: 14},
	{key: columnName, header: "SESSION_NAME", cap: 64, wide: true},
	{key: columnID, header: "SESSION_ID", cap: 36},
	{key: columnDrive, header: "DRIVER", cap: 10},
	{key: columnWorkspace, header: "PROJECT_WORKSPACE", cap: workspaceColumnCap, grow: true, leftClip: true},
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

// briefColumnKeys is the column set a brief layout prints: the three fields that
// identify a row and nothing else. It is a set rather than a list of removals, so
// a column added later is absent from a brief table by default instead of
// silently widening it.
var briefColumnKeys = map[string]bool{
	columnNo:       true,
	columnName:     true,
	columnEndpoint: true,
}

// layoutColumns returns the columns one render actually prints. It starts from
// the colour-dependent layout and then applies the presentation choices that do
// not depend on colour, so a hidden column is dropped for every colour policy.
//
// Brief is applied last and is a set, so it wins over the colour layout: a brief
// table prints the same three columns whether or not colour is enabled, which is
// what makes the layout predictable for an operator who redirected the output.
func layoutColumns(options TableOptions) []tableColumn {
	columns := columnsFor(options.Color)
	kept := make([]tableColumn, 0, len(columns))
	for _, column := range columns {
		if options.HideSessionID && column.key == columnID {
			continue
		}
		if options.Brief && !briefColumnKeys[column.key] {
			continue
		}
		kept = append(kept, column)
	}
	return kept
}

// layoutHeaders lists the headers of one rendered layout, so a caller that needs
// the printed headers never has to rebuild the layout itself.
func layoutHeaders(options TableOptions) []string {
	return columnHeaders(layoutColumns(options))
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

// measureColumns derives every column width from the header and the rendered
// cells. A full layout ignores the per-column caps, so a long value is never
// shortened; a bounded layout keeps the cap that stops one field from consuming
// the whole terminal.
func measureColumns(cells [][]string, columns []tableColumn, full bool) []int {
	widths := columnWidths(columns)
	for _, row := range cells {
		for j, cell := range row {
			n := displayWidth(cell)
			if n <= widths[j] {
				continue
			}
			if full || columns[j].wide {
				// A full layout and a wide column keep the complete value.
				widths[j] = n
				continue
			}
			widths[j] = minInt(n, columns[j].cap)
		}
	}
	return widths
}

// writeTable renders one measured table. A full layout never applies the
// terminal bound, so a narrow terminal wraps the complete values instead of
// clipping them; a bounded layout keeps the existing fitting and narrow rules.
//
// Growth runs before fitting, so the shrinker stays the final safety net: a
// column can only spend width the table does not need, and a table that still
// does not fit is reduced exactly as before.
func writeTable(out io.Writer, headers []string, cells, states [][]string, rowStyles []string, widths []int, columns []tableColumn, options TableOptions) error {
	if options.Full {
		return writeFramedTable(out, headers, cells, states, rowStyles, widths, columns, options.Color)
	}
	if options.Grow {
		growColumns(widths, cells, columns, options.Width)
	}
	fitTableWidths(widths, options.Width)
	if options.Width > 0 && options.Width < minimumTableWidth(len(widths)) {
		return writeNarrowTable(out, cells, states, rowStyles, columns, options.Width, options.Color)
	}
	return writeFramedTable(out, headers, cells, states, rowStyles, widths, columns, options.Color)
}

// growColumns spends the width a table does not need on the columns that may
// grow, so a value is printed in full when the terminal has room for it.
//
// The spare width is what the terminal offers beyond the measured table, so a
// table that already fills the terminal grows nothing and keeps its capped
// layout. Columns are visited in layout order and each takes only what it needs
// to reach its natural width, so the result never depends on which column
// happens to be widest. A zero limit means the width is unknown, which is not a
// budget that can be spent, so nothing grows.
func growColumns(widths []int, cells [][]string, columns []tableColumn, limit int) {
	if limit <= 0 {
		return
	}
	spare := limit - tableWidth(widths)
	if spare <= 0 {
		return
	}
	for j, column := range columns {
		if spare <= 0 {
			return
		}
		if !column.grow {
			continue
		}
		natural := naturalColumnWidth(cells, j, widths[j])
		if natural <= widths[j] {
			continue
		}
		add := minInt(natural-widths[j], spare)
		widths[j] += add
		spare -= add
	}
}

// naturalColumnWidth reports the widest rendered value of one column, so a
// growable column can be widened to exactly the width its content needs.
func naturalColumnWidth(cells [][]string, index, current int) int {
	natural := current
	for _, row := range cells {
		if index >= len(row) {
			continue
		}
		if n := displayWidth(row[index]); n > natural {
			natural = n
		}
	}
	return natural
}

// tableWidth reports the rendered width of one measured table, including the
// separators between columns.
func tableWidth(widths []int) int {
	if len(widths) == 0 {
		return 0
	}
	total := 3 * (len(widths) - 1)
	for _, width := range widths {
		total += width
	}
	return total
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
	columns := layoutColumns(options)
	headers := columnHeaders(columns)
	cells := make([][]string, len(rows))
	states := make([][]string, len(rows))
	rowStyles := make([]string, len(rows))
	for i, row := range rows {
		cells[i] = projectCells(tableCells(row, options.Location), columns)
		states[i] = tableStates(row, columns)
		rowStyles[i] = stateStyle(rowState(row))
	}
	widths := measureColumns(cells, columns, options.Full)
	if err := writeTable(out, headers, cells, states, rowStyles, widths, columns, options); err != nil {
		return err
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

// writeFramedTable draws one full-width table: a rule, the header row, a column
// separator, every data row, and a closing rule. It is shared by the session and
// endpoint layouts so both keep identical framing, clipping and colour rules.
func writeFramedTable(out io.Writer, headers []string, cells, states [][]string, rowStyles []string, widths []int, columns []tableColumn, policy ColorPolicy) error {
	writeRow := func(values, rowStates []string, rowStyle string, header bool) error {
		for i, value := range values {
			if i > 0 {
				if err := writeStyled(out, rowStyle, " │ ", policy); err != nil {
					return err
				}
			}
			cell := clipCell(value, widths[i])
			if !header && columns[i].leftClip {
				cell = clipCellLeft(value, widths[i])
			}
			cell += strings.Repeat(" ", widths[i]-displayWidth(cell))
			if header {
				if err := writeStyled(out, ansiBoldCyan, cell, policy); err != nil {
					return err
				}
				continue
			}
			state := ""
			if len(rowStates) > i {
				state = rowStates[i]
			}
			if err := writeCellState(out, cell, columns[i].warn, state, rowStyle, policy); err != nil {
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
	return writeRule()
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
//
// A session whose liveness the provider could not verify is reported as
// unknown, so it lands in the unknown bucket like any other unknown state. The
// summary deliberately does not name that subset: the line reports one
// dimension, the reported state, and a second label on the same line made the
// numbers ambiguous about which dimension each one counted. The per-row
// distinction stays visible in the table, in the info detail and in the refusal
// message, so dropping the label here hides nothing.
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
//
// "unverified" is not a session state: it is the colour key rowState returns for
// a session whose liveness the provider could not verify, whose reported state is
// already the standard "unknown". It shares the dim colour with "unknown" and
// "idle", so the row itself does not distinguish them; the summary subset label
// and the refusal message carry that difference instead.
func stateStyle(state string) string {
	switch state {
	case "running":
		return ansiGreen
	case "stopped", "completed", "idle", "unknown", "unverified":
		return ansiDim
	case "failed", "error", "offline":
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
		columnDrive:      escapeCell(driveCell(row)),
		columnName:       escapeCell(row.DisplayName),
		columnID:         escapeCell(row.ProviderSessionID),
		columnWorkspace:  escapeCell(row.ProjectWorkspace),
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
//
// The DRIVER cell is the one exception: a verified running controller is marked
// with its own state so it can be emphasised in place. The row colour already
// carries the session state, and a controller is a separate fact, so colouring the
// whole row for it would make one cell contradict its own row.
func tableStates(row SessionRow, columns []tableColumn) []string {
	states := make([]string, len(columns))
	for i, column := range columns {
		if column.warn {
			states[i] = dataStatus(row)
			continue
		}
		if column.key == columnDrive && driveRunningVerified(row) {
			states[i] = stateDriveRunning
			continue
		}
		states[i] = rowState(row)
	}
	return states
}

// driveRunningVerified reports whether the provider verified a live controller.
// An unverified, stale, exited, failed, absent or unknown record is never
// emphasised, because emphasis must mean "a controller is running right now".
func driveRunningVerified(row SessionRow) bool {
	return row.Drive != nil && row.Drive.State == protocol.DriveStateRunning && row.Drive.Verified
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

// clipCellLeft keeps the tail of an over-wide value, so a path that shares a
// long prefix with its siblings still shows the part that identifies it.
func clipCellLeft(value string, width int) string {
	if displayWidth(value) <= width {
		return value
	}
	if width <= 3 {
		return strings.Repeat(".", width)
	}
	return "..." + value[safeClipStartIndex(value, width-3):]
}

// safeClipStartIndex returns the byte offset where the last limit display
// columns of value begin, so a left clip never splits a rune.
func safeClipStartIndex(value string, limit int) int {
	used := 0
	for i := len(value); i > 0; {
		r, size := utf8.DecodeLastRuneInString(value[:i])
		runeWidth := runeDisplayWidth(r)
		if used+runeWidth > limit {
			return i
		}
		used += runeWidth
		i -= size
	}
	return 0
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

// rowState reports the colour key for one row. A session whose liveness the
// provider could not verify reports the standard "unknown" state, so returning
// row.State alone would colour it exactly like a provider-reported unknown
// session. The "unverified" key is a colour key only: the SESSION_STATUS cell
// still renders row.State, because the state vocabulary is a protocol contract
// and "unverified" is not a state.
func rowState(row SessionRow) string {
	if row.Unverified {
		return "unverified"
	}
	return row.State
}

// driveCell projects the controller summary into one short table value.
//
// A nil summary means the provider reported no driver observation, so it renders
// as "-" rather than "none": "none" would claim a confirmed absence of a
// controller, which the provider never stated. A running state whose liveness was
// not verified renders as "unverified", because presenting it as running would
// let an operator stop supervising a session whose controller is not actually
// alive.
func driveCell(row SessionRow) string {
	if row.Drive == nil {
		return "-"
	}
	if row.Drive.State == protocol.DriveStateRunning && !row.Drive.Verified {
		return "unverified"
	}
	if row.Drive.State == "" {
		return "unknown"
	}
	return row.Drive.State
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

// stateDriveRunning is a per-cell emphasis marker, not a session state. It is
// deliberately outside the session state vocabulary so it can never be confused
// with, or counted as, a row state by the summary or the row colour.
const stateDriveRunning = "drive_running"

// writeCellState writes one cell with the row's colour. A data row is coloured
// as a whole from its session state, so every cell and separator of that row
// shares one style; a warning column keeps its own colour when it reports a
// collection problem, because that signal must stay visible on a healthy row.
//
// The drive emphasis marker overrides the row colour for exactly one cell, so a
// verified running controller is visible without recolouring the row it belongs
// to. It is bold green rather than plain green so it stays distinguishable from a
// running session row, which is plain green.
func writeCellState(w io.Writer, cell string, warn bool, state, rowStyle string, policy ColorPolicy) error {
	if !policy.Enabled {
		_, err := io.WriteString(w, cell)
		return err
	}
	if state == stateDriveRunning {
		return writeStyled(w, ansiBoldGreen, cell, policy)
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
