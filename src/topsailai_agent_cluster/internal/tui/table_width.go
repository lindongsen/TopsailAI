package tui

import (
	"io"
	"strings"
)

// OutputWidth obtains a boundary-provided width without probing global streams.
func OutputWidth(out io.Writer) int {
	if terminal, ok := out.(interface{ TerminalWidth() int }); ok {
		return terminal.TerminalWidth()
	}
	return 0
}

// fitTableWidths shrinks the widest data column first, preserving row numbers.
// Widths below the separator minimum retain a readable minimum-width table.
func fitTableWidths(widths []int, limit int) {
	if limit <= 0 {
		return
	}
	total := 3 * (len(widths) - 1)
	for _, width := range widths {
		total += width
	}
	for total > limit {
		widest := -1
		for i := 1; i < len(widths); i++ {
			if widths[i] > 1 && (widest == -1 || widths[i] > widths[widest]) {
				widest = i
			}
		}
		if widest == -1 {
			return
		}
		widths[widest]--
		total--
	}
}

// writeNarrowTable keeps tiny terminals bounded with one labelled field per line.
// Labels stay bold cyan as structural field names, while each value carries the
// same whole-row colour the wide table uses, so a row reads as one unit.
func writeNarrowTable(out io.Writer, rows, states [][]string, rowStyles []string, columns []tableColumn, width int, policy ColorPolicy) error {
	if len(rows) > 0 {
		if _, err := io.WriteString(out, strings.Repeat("─", width)+"\n"); err != nil {
			return err
		}
	}
	for index, row := range rows {
		rowStyle := rowStyles[index]
		for i, value := range row {
			label := clipCell(columns[i].header+": ", width)
			if err := writeStyled(out, ansiBoldCyan, label, policy); err != nil {
				return err
			}
			remaining := width - displayWidth(label)
			if remaining < 0 {
				remaining = 0
			}
			cell := clipCell(value, remaining)
			if columns[i].wide {
				// Session names stay complete even in a narrow terminal.
				cell = value
			}
			state := states[index][i]
			if err := writeCellState(out, cell, columns[i].warn, state, rowStyle, policy); err != nil {
				return err
			}
			if _, err := io.WriteString(out, "\n"); err != nil {
				return err
			}
		}
		if _, err := io.WriteString(out, strings.Repeat("─", width)+"\n"); err != nil {
			return err
		}
	}
	return nil
}
