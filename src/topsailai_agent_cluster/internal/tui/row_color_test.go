package tui

import (
	"io"
	"strings"
	"testing"

	"topsailai_agent_cluster/internal/protocol"
)

// stripANSI removes every SGR sequence so a coloured row can be compared with
// its plain form byte for byte.
func stripANSI(value string) string {
	var builder strings.Builder
	for i := 0; i < len(value); {
		if strings.HasPrefix(value[i:], "\x1b[") {
			end := strings.IndexByte(value[i:], 'm')
			if end < 0 {
				builder.WriteString(value[i:])
				break
			}
			i += end + 1
			continue
		}
		builder.WriteByte(value[i])
		i++
	}
	return builder.String()
}

// sgrSequences returns every SGR sequence of one line in order.
func sgrSequences(line string) []string {
	sequences := make([]string, 0, 8)
	for i := 0; i < len(line); {
		if strings.HasPrefix(line[i:], "\x1b[") {
			end := strings.IndexByte(line[i:], 'm')
			if end < 0 {
				break
			}
			sequences = append(sequences, line[i:i+end+1])
			i += end + 1
			continue
		}
		i++
	}
	return sequences
}

// coloredColumns returns the layout used when colour is enabled, which omits
// SESSION_STATUS because the row colour already carries the state.
func coloredColumns() []tableColumn {
	return columnsFor(ColorPolicy{Enabled: true})
}

// dataRowLine returns the first data row of a wide table, which follows the top
// rule, the header row and the header separator.
func dataRowLine(t *testing.T, rendered string) string {
	t.Helper()
	lines := strings.Split(strings.TrimSuffix(rendered, "\n"), "\n")
	if len(lines) < 4 {
		t.Fatalf("table has %d lines: %q", len(lines), rendered)
	}
	return lines[3]
}

// headerLine returns the header row of a wide table.
func headerLine(t *testing.T, rendered string) string {
	t.Helper()
	lines := strings.Split(strings.TrimSuffix(rendered, "\n"), "\n")
	if len(lines) < 4 {
		t.Fatalf("table has %d lines: %q", len(lines), rendered)
	}
	return lines[1]
}

// TestTableColorsWholeRowFromSessionState proves the operator sees one colour
// across the entire data row, and that the state column is dropped because the
// row colour already carries it.
func TestTableColorsWholeRowFromSessionState(t *testing.T) {
	cases := []struct {
		state string
		style string
	}{
		{"running", ansiGreen},
		{"failed", ansiRed},
		{"stopped", ansiDim},
		{"unknown-state", ansiYellow},
		{"unknown", ansiDim},
		{"idle", ansiDim},
		{"offline", ansiRed},
	}
	for _, testCase := range cases {
		t.Run(testCase.state, func(t *testing.T) {
			rows := []SessionRow{{
				EndpointID:        "endpoint-1",
				AdapterID:         "adapter",
				ProviderSessionID: "provider-42",
				DisplayName:       "Daily work",
				State:             testCase.state,
				CollectionStatus:  protocol.CollectionSucceeded,
			}}
			var colored, plain, errors strings.Builder
			if err := RenderTable(&colored, &errors, rows, nil, TableOptions{Color: ColorPolicy{Enabled: true}}); err != nil {
				t.Fatal(err)
			}
			if err := RenderTable(&plain, &errors, rows, nil, TableOptions{}); err != nil {
				t.Fatal(err)
			}
			coloredRow := dataRowLine(t, colored.String())
			plainRow := dataRowLine(t, plain.String())
			// The coloured layout drops SESSION_STATUS, so its text must equal
			// the plain row with that one cell removed and nothing else changed.
			if got, want := stripANSI(coloredRow), withoutStateCell(t, plainRow); got != want {
				t.Fatalf("coloured row text = %q, want %q", got, want)
			}
			// Every cell and every separator of the row carries the row style,
			// so no cell is left uncoloured.
			sequences := sgrSequences(coloredRow)
			if len(sequences) == 0 {
				t.Fatalf("row has no styling: %q", coloredRow)
			}
			for _, sequence := range sequences {
				if sequence != testCase.style && sequence != ansiReset {
					t.Fatalf("row %q contains foreign style %q: %q", testCase.state, sequence, coloredRow)
				}
			}
			// One style prefix per cell plus one per separator, and one reset
			// after each, so the whole line is covered.
			if got, want := strings.Count(coloredRow, testCase.style), len(coloredColumns())*2-1; got != want {
				t.Fatalf("row %q style count = %d, want %d: %q", testCase.state, got, want, coloredRow)
			}
			if !strings.HasSuffix(coloredRow, ansiReset) {
				t.Fatalf("row does not end with a reset: %q", coloredRow)
			}
		})
	}
}

// withoutStateCell removes the SESSION_STATUS cell from a plain-layout row, so a
// coloured row can be compared with the layout that actually omits the column.
func withoutStateCell(t *testing.T, plainRow string) string {
	t.Helper()
	columns := columnsFor(ColorPolicy{})
	cells := strings.Split(plainRow, " │ ")
	if len(cells) != len(columns) {
		t.Fatalf("plain cell count = %d, want %d: %q", len(cells), len(columns), plainRow)
	}
	kept := make([]string, 0, len(cells)-1)
	for index, column := range columns {
		if column.key == columnState {
			continue
		}
		kept = append(kept, cells[index])
	}
	return strings.Join(kept, " │ ")
}

// TestTableRowColorKeepsDataStatusWarning proves a collection problem stays
// visible on a healthy row instead of being absorbed by the row colour.
func TestTableRowColorKeepsDataStatusWarning(t *testing.T) {
	rows := []SessionRow{{
		EndpointID:        "endpoint-1",
		AdapterID:         "adapter",
		ProviderSessionID: "provider-42",
		State:             "running",
		Stale:             true,
		CollectionStatus:  protocol.CollectionFailed,
	}}
	var out, errors strings.Builder
	if err := RenderTable(&out, &errors, rows, nil, TableOptions{Color: ColorPolicy{Enabled: true}}); err != nil {
		t.Fatal(err)
	}
	row := dataRowLine(t, out.String())
	if !strings.Contains(row, ansiRed) {
		t.Fatalf("failed DATA_STATUS lost its red warning: %q", row)
	}
	if !strings.Contains(row, ansiGreen) {
		t.Fatalf("running row lost its green colour: %q", row)
	}
	// The warning is confined to the DATA_STATUS cell: the remaining cells stay
	// green, so the row still reads as one unit.
	columns := coloredColumns()
	cells := strings.Split(row, " │ ")
	if len(cells) != len(columns) {
		t.Fatalf("cell count = %d, want %d: %q", len(cells), len(columns), row)
	}
	for index, cell := range cells {
		if columns[index].warn {
			if !strings.Contains(cell, ansiRed) {
				t.Fatalf("DATA_STATUS cell = %q, want red", cell)
			}
			continue
		}
		if strings.Contains(cell, ansiRed) {
			t.Fatalf("cell %d = %q, want the row colour only", index, cell)
		}
	}
}

// TestNarrowTableColorsWholeRow proves the narrow layout colours each value with
// the same row colour while keeping labels as structural bold cyan.
func TestNarrowTableColorsWholeRow(t *testing.T) {
	rows := []SessionRow{
		{No: 1, EndpointID: "ep", AdapterID: "ad", ProviderSessionID: "prov", DisplayName: "name", State: "running", CollectionStatus: protocol.CollectionSucceeded},
		{No: 2, EndpointID: "ep", AdapterID: "ad", ProviderSessionID: "prov2", DisplayName: "other", State: "failed", CollectionStatus: protocol.CollectionSucceeded},
	}
	var colored, plain strings.Builder
	options := TableOptions{Width: narrowProbeWidth()}
	if err := RenderTable(&colored, io.Discard, rows, nil, TableOptions{Width: options.Width, Color: ColorPolicy{Enabled: true}}); err != nil {
		t.Fatal(err)
	}
	if err := RenderTable(&plain, io.Discard, rows, nil, options); err != nil {
		t.Fatal(err)
	}
	// The coloured narrow layout omits the SESSION_STATUS field, so its text
	// must equal the plain layout with that one field line removed.
	if got, want := stripANSI(colored.String()), withoutStateFieldLines(t, plain.String()); got != want {
		t.Fatalf("coloured narrow text = %q, want %q", got, want)
	}
	// Each field line is "label: value"; the label stays bold cyan and the value
	// carries the row colour. Blocks are separated by the horizontal rules, so
	// every value line of one block must share that row's single colour.
	wantStyles := []string{ansiGreen, ansiRed}
	blocks := narrowFieldBlocks(t, colored.String())
	if len(blocks) != len(rows) {
		t.Fatalf("blocks = %d, want %d: %q", len(blocks), len(rows), colored.String())
	}
	for index, block := range blocks {
		if len(block) != len(coloredColumns()) {
			t.Fatalf("block %d has %d field lines, want %d: %q", index, len(block), len(coloredColumns()), colored.String())
		}
		for _, line := range block {
			if !strings.Contains(line, wantStyles[index]) {
				t.Fatalf("block %d line lost its row colour %q: %q", index, wantStyles[index], line)
			}
			for _, foreign := range []string{ansiGreen, ansiRed, ansiDim, ansiYellow} {
				if foreign == wantStyles[index] {
					continue
				}
				if strings.Contains(line, foreign) {
					t.Fatalf("block %d line carries foreign style %q: %q", index, foreign, line)
				}
			}
		}
	}
}

// narrowFieldBlocks groups the narrow layout's field lines by row, using the
// horizontal rules as block boundaries.
func narrowFieldBlocks(t *testing.T, rendered string) [][]string {
	t.Helper()
	blocks := make([][]string, 0, 2)
	current := make([]string, 0, len(tableHeaders))
	for _, line := range strings.Split(strings.TrimSuffix(rendered, "\n"), "\n") {
		if strings.HasPrefix(line, "─") {
			if len(current) > 0 {
				blocks = append(blocks, current)
				current = make([]string, 0, len(tableHeaders))
			}
			continue
		}
		if strings.HasPrefix(line, ansiBoldCyan) {
			current = append(current, line)
		}
	}
	if len(current) > 0 {
		blocks = append(blocks, current)
	}
	return blocks
}

// withoutStateFieldLines removes the SESSION_STATUS field line from every block
// of a plain narrow layout, so it can be compared with the coloured layout that
// omits the field.
func withoutStateFieldLines(t *testing.T, rendered string) string {
	t.Helper()
	label := "SESSION_STATUS: "
	kept := make([]string, 0, 16)
	for _, line := range strings.Split(strings.TrimSuffix(rendered, "\n"), "\n") {
		if strings.HasPrefix(line, label) {
			continue
		}
		kept = append(kept, line)
	}
	return strings.Join(kept, "\n") + "\n"
}

// TestTableRowColorDisabledStaysPlain proves redirected output stays free of
// escapes even though every cell is now written through the styling helper.
func TestTableRowColorDisabledStaysPlain(t *testing.T) {
	rows := []SessionRow{{EndpointID: "ep", AdapterID: "ad", ProviderSessionID: "prov", State: "running", CollectionStatus: protocol.CollectionSucceeded}}
	var out, errors strings.Builder
	if err := RenderTable(&out, &errors, rows, nil, TableOptions{}); err != nil {
		t.Fatal(err)
	}
	if strings.Contains(out.String(), "\x1b") {
		t.Fatalf("plain output contains escapes: %q", out.String())
	}
	if !strings.Contains(out.String(), " │ ") {
		t.Fatalf("plain output lost its separators: %q", out.String())
	}
}

// TestTableHeaderRowUnchangedByRowColour proves the header keeps its previous
// rendering: bold cyan cells with plain separators and no stray reset, so the
// whole-row colour change touches data rows only.
func TestTableHeaderRowUnchangedByRowColour(t *testing.T) {
	rows := []SessionRow{{EndpointID: "ep", AdapterID: "ad", ProviderSessionID: "prov", State: "running", CollectionStatus: protocol.CollectionSucceeded}}
	var out, errors strings.Builder
	if err := RenderTable(&out, &errors, rows, nil, TableOptions{Color: ColorPolicy{Enabled: true}}); err != nil {
		t.Fatal(err)
	}
	lines := strings.Split(strings.TrimSuffix(out.String(), "\n"), "\n")
	if len(lines) < 4 {
		t.Fatalf("table has %d lines: %q", len(lines), out.String())
	}
	header := lines[1]
	columns := coloredColumns()
	if got, want := strings.Count(header, ansiBoldCyan), len(columns); got != want {
		t.Fatalf("header style count = %d, want %d: %q", got, want, header)
	}
	if got, want := strings.Count(header, " │ "), len(columns)-1; got != want {
		t.Fatalf("header separator count = %d, want %d: %q", got, want, header)
	}
	// Exactly one reset per cell: a separator must not add a reset of its own,
	// which would mean the header row was styled as a whole.
	if got, want := strings.Count(header, ansiReset), len(columns); got != want {
		t.Fatalf("header reset count = %d, want %d: %q", got, want, header)
	}
	// Every header cell is exactly one bold cyan span, so separators stay plain.
	for index, cell := range strings.Split(header, " │ ") {
		if !strings.HasPrefix(cell, ansiBoldCyan) || !strings.HasSuffix(cell, ansiReset) {
			t.Fatalf("header cell %d = %q, want one bold cyan span", index, cell)
		}
		if strings.Count(cell, ansiBoldCyan) != 1 {
			t.Fatalf("header cell %d = %q, want a single style prefix", index, cell)
		}
	}
}

// TestTableDropsStateColumnOnlyWithColor proves the state column is removed
// exactly when the row colour already carries the state, and kept otherwise so
// redirected output still reports the state in text.
func TestTableDropsStateColumnOnlyWithColor(t *testing.T) {
	rows := []SessionRow{{EndpointID: "ep", AdapterID: "ad", ProviderSessionID: "prov", State: "running", CollectionStatus: protocol.CollectionSucceeded}}
	var colored, plain, errors strings.Builder
	if err := RenderTable(&colored, &errors, rows, nil, TableOptions{Color: ColorPolicy{Enabled: true}}); err != nil {
		t.Fatal(err)
	}
	if err := RenderTable(&plain, &errors, rows, nil, TableOptions{}); err != nil {
		t.Fatal(err)
	}
	coloredHeader := headerLine(t, colored.String())
	plainHeader := headerLine(t, plain.String())
	if strings.Contains(coloredHeader, "SESSION_STATUS") {
		t.Fatalf("coloured header still shows the state column: %q", coloredHeader)
	}
	if !strings.Contains(plainHeader, "SESSION_STATUS") {
		t.Fatalf("plain header lost the only textual state signal: %q", plainHeader)
	}
	// The state text itself must be gone from the coloured row, because the row
	// colour is now the only state signal there.
	if strings.Contains(stripANSI(dataRowLine(t, colored.String())), "running") {
		t.Fatalf("coloured row still repeats the state text: %q", dataRowLine(t, colored.String()))
	}
	if !strings.Contains(dataRowLine(t, plain.String()), "running") {
		t.Fatalf("plain row lost the state text: %q", dataRowLine(t, plain.String()))
	}
	// The remaining columns keep their order and content in both layouts.
	if got, want := len(coloredColumns()), len(tableHeaders)-1; got != want {
		t.Fatalf("coloured column count = %d, want %d", got, want)
	}
}
