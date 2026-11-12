package tui

import (
	"io"
	"strings"
)

// TableLayout is the presentation policy an output boundary reports: the
// terminal width, whether truncation is disabled, and whether a growable column
// may spend width the table does not need.
type TableLayout struct {
	Width int
	Full  bool
	// Grow is set only by a boundary whose width is a real budget, such as a
	// terminal. A redirected stream reports no width, so it never grows.
	Grow bool
}

// TableLayoutProvider lets an output boundary report its layout once, so a
// renderer never has to probe global terminal state.
type TableLayoutProvider interface {
	TableLayout() TableLayout
}

// OutputWidth obtains a boundary-provided width without probing global streams.
func OutputWidth(out io.Writer) int {
	return OutputLayout(out).Width
}

// OutputLayout obtains the boundary-provided presentation policy. A writer that
// only reports a width keeps truncation enabled and growth disabled, so existing
// callers are unaffected.
func OutputLayout(out io.Writer) TableLayout {
	if provider, ok := out.(TableLayoutProvider); ok {
		return provider.TableLayout()
	}
	if terminal, ok := out.(interface{ TerminalWidth() int }); ok {
		return TableLayout{Width: terminal.TerminalWidth()}
	}
	return TableLayout{}
}

// TableOptionsFor builds the table options for one output boundary, so every
// render path applies the same width, truncation and growth policy.
func TableOptionsFor(out io.Writer) TableOptions {
	layout := OutputLayout(out)
	return TableOptions{Width: layout.Width, Full: layout.Full, Grow: layout.Grow}
}

// tableOptionsFor builds the table options for one REPL render, so the output
// boundary decides both the width and whether truncation is disabled.
//
// The parsed list arguments carry the per-command requests. Full is ORed with the
// boundary value rather than replacing it: the boundary value comes from the
// startup --no-truncate option, so an operator who disabled truncation for the
// whole session must not lose it by running a command that did not repeat the
// request. A command that has no full form passes a zero value and therefore
// inherits the boundary unchanged. Brief is not ORed with anything, because it is
// a column-set choice with no session-wide equivalent.
//
// The interactive table hides SESSION_ID: the operator selects a session by its
// row number or name, and the provider session ID is a long opaque value that
// only widens the table. The ID stays on the row, so it is still accepted as a
// command target. The standalone commands keep the column, because their output
// is parsed by scripts and tests.
func tableOptionsFor(out io.Writer, color ColorPolicy, arguments listArguments, onRows func([]SessionRow)) TableOptions {
	options := TableOptionsFor(out)
	options.Color = color
	options.Clean = arguments.Clean
	options.All = arguments.All
	options.Full = options.Full || arguments.Full
	options.Brief = arguments.Brief
	options.OnRows = onRows
	options.HideSessionID = true
	return options
}

// fitTableWidths shrinks the widest data column first, preserving row numbers.
// Widths below the separator minimum retain a readable minimum-width table.
func fitTableWidths(widths []int, limit int) {
	if limit <= 0 {
		return
	}
	total := tableWidth(widths)
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
			if columns[i].leftClip {
				// A path keeps its identifying tail in a narrow terminal too.
				cell = clipCellLeft(value, remaining)
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
