package tui

import (
	"io"
	"strings"
	"testing"

	"topsailai_agent_cluster/internal/protocol"
)

// growWorkspace is a path longer than workspaceColumnCap, so a capped layout
// clips it and a grown layout can print it in full.
const growWorkspace = "/TopsailAI/src/topsailai_agent_cluster/internal/tui"

// growRow returns one row whose workspace exceeds the column cap.
func growRow() SessionRow {
	return SessionRow{
		EndpointID:               "ep",
		ProviderSessionID:        "sess-0123456789abcdef",
		ProviderDisplayName:      "PS11-refactor-auth-service",
		ProviderProjectWorkspace: growWorkspace,
		State:                    "running",
		CollectionStatus:         protocol.CollectionSucceeded,
	}
}

// renderGrown renders one row with the given options and returns the output.
func renderGrown(t *testing.T, options TableOptions) string {
	t.Helper()
	var out strings.Builder
	if err := RenderTable(&out, io.Discard, []SessionRow{growRow()}, nil, options); err != nil {
		t.Fatal(err)
	}
	return out.String()
}

// TestGrowReachesNaturalWidth proves a terminal with room prints the complete
// workspace path instead of the capped tail.
func TestGrowReachesNaturalWidth(t *testing.T) {
	rendered := renderGrown(t, TableOptions{Width: 200, Grow: true})
	cell := workspaceCell(t, rendered)
	if cell != growWorkspace {
		t.Fatalf("workspace cell=%q, want the complete path", cell)
	}
	if strings.Contains(cell, "...") {
		t.Fatalf("grown cell still carries a truncation marker: %q", cell)
	}
}

// cappedTableWidth reports the width the capped layout needs for this fixture,
// so a test can name a terminal that has exactly no spare width or a known
// amount of it. Hardcoding the number would break whenever a header or a fixture
// value changes, and the failure would look like a growth defect.
func cappedTableWidth(t *testing.T) int {
	t.Helper()
	rendered := renderGrown(t, TableOptions{})
	lines := strings.Split(strings.TrimSuffix(rendered, "\n"), "\n")
	if len(lines) == 0 {
		t.Fatal("empty table")
	}
	return displayWidth(lines[0])
}

// TestGrowStopsAtSpareWidth proves growth spends only the width the table does
// not need, so a table that cannot fit the whole value still fits the terminal.
func TestGrowStopsAtSpareWidth(t *testing.T) {
	// Ten spare cells are fewer than the path needs, so the column grows but
	// stays clipped.
	width := cappedTableWidth(t) + 10
	rendered := renderGrown(t, TableOptions{Width: width, Grow: true})
	cell := workspaceCell(t, rendered)
	if displayWidth(cell) <= workspaceColumnCap {
		t.Fatalf("cell width=%d did not grow past the cap: %q", displayWidth(cell), cell)
	}
	if cell == growWorkspace {
		t.Fatalf("cell=%q grew to the full path without the width for it", cell)
	}
	if !strings.HasPrefix(cell, "...") {
		t.Fatalf("partially grown cell is not left-clipped: %q", cell)
	}
	for _, line := range strings.Split(strings.TrimSuffix(rendered, "\n"), "\n") {
		if displayWidth(line) > width {
			t.Fatalf("line exceeds width %d: %q", width, line)
		}
	}
}

// TestGrowWithoutSpareWidthKeepsTheCap proves a table that already fills the
// terminal grows nothing, so the capped layout is unchanged.
func TestGrowWithoutSpareWidthKeepsTheCap(t *testing.T) {
	width := cappedTableWidth(t)
	rendered := renderGrown(t, TableOptions{Width: width, Grow: true})
	cell := workspaceCell(t, rendered)
	if got := displayWidth(cell); got != workspaceColumnCap {
		t.Fatalf("cell width=%d, want the cap %d: %q", got, workspaceColumnCap, cell)
	}
}

// TestGrowDisabledKeepsCappedOutput proves growth is opt-in: the default layout
// keeps clipping the same value on a wide terminal.
func TestGrowDisabledKeepsCappedOutput(t *testing.T) {
	rendered := renderGrown(t, TableOptions{Width: 200})
	cell := workspaceCell(t, rendered)
	if got := displayWidth(cell); got != workspaceColumnCap {
		t.Fatalf("cell width=%d, want the cap %d: %q", got, workspaceColumnCap, cell)
	}
}

// TestGrowUnknownWidthIsByteIdentical proves an unknown width is not a budget
// that can be spent, so a redirected stream keeps its previous output exactly.
func TestGrowUnknownWidthIsByteIdentical(t *testing.T) {
	capped := renderGrown(t, TableOptions{})
	grown := renderGrown(t, TableOptions{Grow: true})
	if capped != grown {
		t.Fatalf("unknown width changed with growth enabled:\ncapped=%q\ngrown=%q", capped, grown)
	}
}

// TestGrowNeverExceedsTheTerminal proves growth cannot push a table past the
// terminal at any width, including widths where the table already fits.
func TestGrowNeverExceedsTheTerminal(t *testing.T) {
	for _, width := range []int{60, 80, 100, 120, 140, 147, 160, 200, 260} {
		rendered := renderGrown(t, TableOptions{Width: width, Grow: true})
		for _, line := range strings.Split(strings.TrimSuffix(rendered, "\n"), "\n") {
			if displayWidth(line) > width {
				t.Fatalf("width=%d line=%q", width, line)
			}
		}
	}
}

// TestGrowAppliesToHistoryLayout proves the history table shares the growth
// rule, so the two layouts cannot drift apart.
func TestGrowAppliesToHistoryLayout(t *testing.T) {
	view := HistoryView{Rows: []HistoryViewRow{{
		ProviderSessionID:        "sess-0123456789abcdef",
		ProviderDisplayName:      "PS11-refactor-auth-service",
		ProviderProjectWorkspace: growWorkspace,
		ProviderStatus:           "running",
		Resumable:                true,
	}}}
	var out strings.Builder
	if err := RenderHistory(&out, view, TableOptions{Width: 200, Grow: true}); err != nil {
		t.Fatal(err)
	}
	if !strings.Contains(out.String(), growWorkspace) {
		t.Fatalf("history layout did not grow the workspace: %q", out.String())
	}
}

// TestGrowLeavesFullLayoutUnchanged proves --no-truncate still prints every
// value in full and is unaffected by the growth switch.
func TestGrowLeavesFullLayoutUnchanged(t *testing.T) {
	rendered := renderGrown(t, TableOptions{Width: 40, Full: true, Grow: true})
	if !strings.Contains(rendered, growWorkspace) {
		t.Fatalf("full layout truncated the workspace: %q", rendered)
	}
	if strings.Contains(rendered, "...") {
		t.Fatalf("full layout emitted a truncation marker: %q", rendered)
	}
}

// TestGrowLeavesNarrowLayoutUnchanged proves the narrow layout still spends the
// whole width on one field per line, so growth adds nothing there.
func TestGrowLeavesNarrowLayoutUnchanged(t *testing.T) {
	width := minimumTableWidth(len(allColumns)) - 1
	capped := renderGrown(t, TableOptions{Width: width})
	grown := renderGrown(t, TableOptions{Width: width, Grow: true})
	if capped != grown {
		t.Fatalf("narrow layout changed with growth enabled:\ncapped=%q\ngrown=%q", capped, grown)
	}
	if !strings.Contains(grown, "PROJECT_WORKSPACE: ") {
		t.Fatalf("expected the narrow layout, got %q", grown)
	}
}
