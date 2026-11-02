package tui

import (
	"context"
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
	OnRows func([]SessionRow)
}

var tableHeaders = []string{"NO", "ENDPOINT", "ADAPTER", "SESSION", "GENERATION", "STATE", "STALE", "UNKNOWN", "COLLECTION", "LAST_SUCCESS_MS"}
var tableCaps = []int{4, 20, 18, 36, 20, 12, 5, 7, 16, 15}

// Table queries and renders the session table, preserving successful rows on partial failure.
func (r CommandRunner) Table(ctx context.Context, out, errors io.Writer, filter string, jsonMode bool, options TableOptions) error {
	loaded, err := loadReports(ctx, r.API, filter)
	if err != nil {
		return err
	}
	rows := ListRows(loaded.endpoints, loaded.reports, filter)
	if jsonMode {
		return RenderJSON(out, rows)
	}
	if len(loaded.errors) > 0 {
		filtered := rows[:0]
		for _, row := range rows {
			if _, failed := loaded.errors[row.EndpointID]; !failed {
				filtered = append(filtered, row)
			}
		}
		rows = filtered
	}
	assignRowNumbers(rows)
	if options.OnRows != nil {
		options.OnRows(append([]SessionRow(nil), rows...))
	}
	failures := make([]EndpointFailure, 0, len(loaded.errors))
	for id, fetchErr := range loaded.errors {
		failures = append(failures, EndpointFailure{EndpointID: id, Err: fetchErr})
	}
	return RenderTable(out, errors, rows, failures, options)
}

// RenderTable writes a bounded ASCII table and sorted endpoint diagnostics.
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
				if _, err := io.WriteString(out, "  "); err != nil {
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
	if err := writeRow(tableHeaders, true); err != nil {
		return err
	}
	for i, row := range cells {
		_ = i
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
	return []string{strconv.Itoa(row.No), escapeCell(endpoint), escapeCell(adapter), escapeCell(row.SessionID), escapeCell(row.Generation), escapeCell(row.State), strconv.FormatBool(row.Stale), strconv.FormatBool(row.Unknown), escapeCell(row.CollectionStatus), last}
}
func escapeCell(value string) string {
	var b strings.Builder
	for len(value) > 0 {
		r, n := utf8.DecodeRuneInString(value)
		if r == utf8.RuneError && n == 1 {
			b.WriteString("\\uFFFD")
			value = value[1:]
			continue
		}
		if r < 0x20 || r == 0x7f {
			fmt.Fprintf(&b, "\\u%04X", r)
		} else if r > 0x7e {
			if r <= 0xffff {
				fmt.Fprintf(&b, "\\u%04X", r)
			} else {
				fmt.Fprintf(&b, "\\U%08X", r)
			}
		} else if r == '\\' {
			b.WriteString("\\\\")
		} else {
			b.WriteRune(r)
		}
		value = value[n:]
	}
	return b.String()
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
		n := utf8.RuneLen(r)
		if used+n > limit {
			return i
		}
		used += n
	}
	return len(value)
}
func displayWidth(value string) int { return len([]rune(value)) }
func minInt(a, b int) int {
	if a < b {
		return a
	}
	return b
}
func rowState(values []string) string {
	if len(values) > 4 {
		return values[4]
	}
	return ""
}
func writeCellState(w io.Writer, cell string, index int, state string, policy ColorPolicy) error {
	if policy.Enabled && index == 4 {
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
