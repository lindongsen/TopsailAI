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

// writeNarrowTable keeps tiny terminals bounded with one clipped field per line.
func writeNarrowTable(out io.Writer, rows [][]string, width int) error {
	for _, row := range rows {
		for i, value := range row {
			line := clipCell(tableHeaders[i]+": "+value, width)
			if _, err := io.WriteString(out, line+"\n"); err != nil {
				return err
			}
		}
		if _, err := io.WriteString(out, strings.Repeat("─", width)+"\n"); err != nil {
			return err
		}
	}
	return nil
}
