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

// Column indices are named so a column change cannot silently shift colors or alignment.
const (
	columnState      = 5
	columnDataStatus = 6
	columnName       = 3
)

var tableHeaders = []string{"NO", "ENDPOINT", "ADAPTER", "SESSION_NAME", "SESSION_ID", "SESSION_STATUS", "DATA_STATUS"}
var tableCaps = []int{4, 20, 18, 64, 36, 14, 35}

// minimumTableWidth reports the smallest width able to hold one column per field.
func minimumTableWidth(columns int) int {
	return 3*(columns-1) + columns
}

// RenderTable writes a bounded table and sorted endpoint diagnostics.
func RenderTable(out, errors io.Writer, rows []SessionRow, failures []EndpointFailure, options TableOptions) error {
	assignRowNumbers(rows)
	widths := append([]int(nil), tableCaps...)
	for i, header := range tableHeaders {
		widths[i] = len(header)
	}
	cells := make([][]string, len(rows))
	states := make([][]string, len(rows))
	for i, row := range rows {
		cells[i] = tableCells(row, options.Location)
		states[i] = tableStates(row, cells[i])
		for j, cell := range cells[i] {
			n := displayWidth(cell)
			if j == columnName {
				// Session names are shown in full so a long name is never truncated.
				if n > widths[j] {
					widths[j] = n
				}
				continue
			}
			if n > widths[j] {
				widths[j] = minInt(n, tableCaps[j])
			}
		}
	}
	fitTableWidths(widths, options.Width)
	writeRow := func(values, states []string, header bool) error {
		for i, value := range values {
			if i > 0 {
				if _, err := io.WriteString(out, " │ "); err != nil {
					return err
				}
			}
			cell := clipCell(value, widths[i])
			cell += strings.Repeat(" ", widths[i]-displayWidth(cell))
			if header && options.Color.Enabled {
				if err := writeStyled(out, ansiBoldCyan, cell, options.Color); err != nil {
					return err
				}
			} else {
				state := ""
				if len(states) > i {
					state = states[i]
				}
				if err := writeCellState(out, cell, i, state, options.Color); err != nil {
					return err
				}
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
	if options.Width > 0 && options.Width < minimumTableWidth(len(widths)) {
		if err := writeNarrowTable(out, cells, states, options.Width, options.Color); err != nil {
			return err
		}
	} else {
		if err := writeRow(tableHeaders, nil, true); err != nil {
			return err
		}
		if err := writeSeparator(); err != nil {
			return err
		}
		for index, row := range cells {
			if err := writeRow(row, states[index], false); err != nil {
				return err
			}
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

func tableCells(row SessionRow, location *time.Location) []string {
	endpoint := row.EndpointLabel
	if endpoint == "" {
		endpoint = row.EndpointID
	}
	adapter := row.AdapterLabel
	if adapter == "" {
		adapter = row.AdapterID
	}
	return []string{strconv.Itoa(row.No), escapeCell(endpoint), escapeCell(adapter), escapeCell(row.DisplayName), escapeCell(row.ProviderSessionID), escapeCell(row.State), escapeCell(dataStatusCell(row, location))}
}

// tableStates derives each column's colour state from the row itself, so a
// decorated cell such as "ok (<timestamp>)" keeps the colour of its base status.
func tableStates(row SessionRow, cells []string) []string {
	states := make([]string, len(cells))
	for i := range cells {
		states[i] = rowState(cells)
	}
	states[columnDataStatus] = dataStatus(row)
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
	return time.UnixMilli(*value).In(location).Format("2006-01-02T15:04:05")
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
func rowState(values []string) string {
	if len(values) > columnState {
		return values[columnState]
	}
	return ""
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

func writeCellState(w io.Writer, cell string, index int, state string, policy ColorPolicy) error {
	if policy.Enabled && index == columnDataStatus {
		switch {
		case state == "ok":
			_, err := io.WriteString(w, cell)
			return err
		case strings.HasPrefix(state, "failed"):
			return writeStyled(w, ansiRed, cell, policy)
		default:
			return writeStyled(w, ansiYellow, cell, policy)
		}
	}
	if policy.Enabled && index == columnState {
		switch state {
		case "running":
			return writeStyled(w, ansiGreen, cell, policy)
		case "stopped", "completed":
			return writeStyled(w, ansiDim, cell, policy)
		case "failed", "error":
			return writeStyled(w, ansiRed, cell, policy)
		default:
			return writeStyled(w, ansiYellow, cell, policy)
		}
	}
	_, err := io.WriteString(w, cell)
	return err
}

func assignRowNumbers(rows []SessionRow) {
	for index := range rows {
		rows[index].No = index + 1
	}
}
