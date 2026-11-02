package tui

import (
	"fmt"
	"io"
	"sort"
	"strconv"
	"strings"
	"unicode/utf8"
)

// EndpointFailure identifies an endpoint whose inventory could not be observed.
type EndpointFailure struct {
	EndpointID string
	Err        error
}

// TableOptions controls table presentation without changing query semantics.
type TableOptions struct {
	Color  ColorPolicy
	Clean  bool
	OnRows func([]SessionRow)
}

var tableHeaders = []string{"NO", "ENDPOINT", "ADAPTER", "SESSION", "GENERATION", "STATE", "STALE", "UNKNOWN", "COLLECTION", "LAST_SUCCESS_MS"}
var tableCaps = []int{4, 20, 18, 36, 20, 12, 5, 7, 16, 15}

// RenderTable writes a bounded table and sorted endpoint diagnostics.
func RenderTable(out, errors io.Writer, rows []SessionRow, failures []EndpointFailure, options TableOptions) error {
	assignRowNumbers(rows)
	widths := append([]int(nil), tableCaps...)
	for i, header := range tableHeaders {
		widths[i] = len(header)
	}
	cells := make([][]string, len(rows))
	for i, row := range rows {
		cells[i] = tableCells(row)
		for j, cell := range cells[i] {
			if n := displayWidth(cell); n > widths[j] {
				widths[j] = minInt(n, tableCaps[j])
			}
		}
	}
	writeRow := func(values []string, header bool) error {
		for i, value := range values {
			if i > 0 {
				if _, err := io.WriteString(out, " │ "); err != nil {
					return err
				}
			}
			cell := clipCell(value, widths[i])
			if i == 9 {
				cell = strings.Repeat(" ", widths[i]-displayWidth(cell)) + cell
			} else {
				cell += strings.Repeat(" ", widths[i]-displayWidth(cell))
			}
			if header && options.Color.Enabled {
				if err := writeStyled(out, ansiBoldCyan, cell, options.Color); err != nil {
					return err
				}
			} else if err := writeCellState(out, cell, i, rowState(values), options.Color); err != nil {
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
	if err := writeRow(tableHeaders, true); err != nil {
		return err
	}
	if err := writeSeparator(); err != nil {
		return err
	}
	for _, row := range cells {
		if err := writeRow(row, false); err != nil {
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

func tableCells(row SessionRow) []string {
	last := "never"
	if row.LastSuccessAtMS != nil {
		last = strconv.FormatInt(*row.LastSuccessAtMS, 10)
	}
	endpoint := row.EndpointLabel
	if endpoint == "" {
		endpoint = row.EndpointID
	}
	adapter := row.AdapterLabel
	if adapter == "" {
		adapter = row.AdapterID
	}
	session := row.DisplayName
	if session == "" {
		session = row.SessionID
	}
	return []string{strconv.Itoa(row.No), escapeCell(endpoint), escapeCell(adapter), escapeCell(session), escapeCell(row.Generation), escapeCell(row.State), strconv.FormatBool(row.Stale), strconv.FormatBool(row.Unknown), escapeCell(row.CollectionStatus), last}
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
	if len(values) > 5 {
		return values[5]
	}
	return ""
}
func writeCellState(w io.Writer, cell string, index int, state string, policy ColorPolicy) error {
	if policy.Enabled && index == 5 {
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
