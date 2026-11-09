package tui

import (
	"io"
	"strings"
	"testing"
	"unicode/utf8"

	"topsailai_agent_cluster/internal/protocol"
)

// workspaceCell returns the PROJECT_WORKSPACE cell of the first data row.
func workspaceCell(t *testing.T, rendered string) string {
	t.Helper()
	lines := strings.Split(strings.TrimSuffix(rendered, "\n"), "\n")
	if len(lines) < 4 {
		t.Fatalf("table too short: %q", rendered)
	}
	return plainCell(t, lines[3], columnWorkspace)
}

// TestWorkspaceColumnKeepsItsTail proves a long workspace path is clipped from
// the left, so the identifying tail survives instead of a shared prefix.
func TestWorkspaceColumnKeepsItsTail(t *testing.T) {
	workspace := "/TopsailAI/src/topsailai_agent_cluster/internal/tui"
	rows := []SessionRow{{EndpointID: "ep", ProjectWorkspace: workspace, State: "running", CollectionStatus: protocol.CollectionSucceeded}}
	var out strings.Builder
	if err := RenderTable(&out, io.Discard, rows, nil, TableOptions{}); err != nil {
		t.Fatal(err)
	}
	cell := workspaceCell(t, out.String())
	if got := displayWidth(cell); got != workspaceColumnCap {
		t.Fatalf("workspace cell width=%d, want %d: %q", got, workspaceColumnCap, cell)
	}
	if !strings.HasPrefix(cell, "...") {
		t.Fatalf("workspace cell is not left-clipped: %q", cell)
	}
	if !strings.HasSuffix(cell, "internal/tui") {
		t.Fatalf("workspace cell lost its identifying tail: %q", cell)
	}
	if strings.HasPrefix(cell, "/TopsailAI") {
		t.Fatalf("workspace cell kept the shared prefix: %q", cell)
	}
}

// TestWorkspaceColumnKeepsShortValue proves a value inside the cap is untouched.
func TestWorkspaceColumnKeepsShortValue(t *testing.T) {
	rows := []SessionRow{{EndpointID: "ep", ProjectWorkspace: "/work/project-a", State: "running", CollectionStatus: protocol.CollectionSucceeded}}
	var out strings.Builder
	if err := RenderTable(&out, io.Discard, rows, nil, TableOptions{}); err != nil {
		t.Fatal(err)
	}
	if got := workspaceCell(t, out.String()); got != "/work/project-a" {
		t.Fatalf("workspace cell=%q", got)
	}
}

// TestWorkspaceLeftClipIsRuneSafe proves a CJK path is clipped on a rune
// boundary and still fits the requested display width.
func TestWorkspaceLeftClipIsRuneSafe(t *testing.T) {
	value := "/工作区/" + strings.Repeat("中文目录", 12)
	clipped := clipCellLeft(value, 20)
	if !utf8.ValidString(clipped) {
		t.Fatalf("clipped value is not valid UTF-8: %q", clipped)
	}
	if displayWidth(clipped) > 20 {
		t.Fatalf("clipped width=%d value=%q", displayWidth(clipped), clipped)
	}
	if !strings.HasPrefix(clipped, "...") || !strings.HasSuffix(clipped, "中文目录") {
		t.Fatalf("clipped value=%q", clipped)
	}
}

// TestWorkspaceLeftClipDegenerateWidths proves a width too small for the marker
// degrades to dots instead of producing an over-wide cell.
func TestWorkspaceLeftClipDegenerateWidths(t *testing.T) {
	for _, width := range []int{0, 1, 2, 3} {
		got := clipCellLeft("/work/project-a", width)
		if displayWidth(got) > width {
			t.Fatalf("width=%d got=%q", width, got)
		}
	}
}

// TestWorkspaceLeftClipInNarrowLayout proves the narrow terminal layout keeps
// the identifying tail as well, so both layouts share one clipping rule.
func TestWorkspaceLeftClipInNarrowLayout(t *testing.T) {
	workspace := "/TopsailAI/src/topsailai_agent_cluster/internal/tui"
	rows := []SessionRow{{EndpointID: "ep", ProjectWorkspace: workspace, State: "running", CollectionStatus: protocol.CollectionSucceeded}}
	var out strings.Builder
	// One column below the plain-layout threshold, so the narrow layout is used
	// and the value still has room for a tail behind the ellipsis.
	width := minimumTableWidth(len(allColumns)) - 1
	if err := RenderTable(&out, io.Discard, rows, nil, TableOptions{Width: width}); err != nil {
		t.Fatal(err)
	}
	rendered := out.String()
	const prefix = "PROJECT_WORKSPACE: "
	index := strings.Index(rendered, prefix)
	if index < 0 {
		t.Fatalf("expected narrow layout, got %q", rendered)
	}
	cell := rendered[index+len(prefix):]
	if end := strings.IndexByte(cell, '\n'); end >= 0 {
		cell = cell[:end]
	}
	// The exact tail length depends on how many columns the layout carries, so
	// assert the property the rule exists for: the cell is clipped with a leading
	// ellipsis and still ends with the real identifying tail of the path.
	if !strings.HasPrefix(cell, "...") {
		t.Fatalf("narrow layout did not clip with an ellipsis: %q", cell)
	}
	if cell == "..." {
		t.Fatalf("narrow layout lost the identifying tail: %q", cell)
	}
	if !strings.HasSuffix(cell, "tui") || !strings.HasSuffix(workspace, strings.TrimPrefix(cell, "...")) {
		t.Fatalf("narrow layout tail is not the real path tail: %q", cell)
	}
}

// TestWorkspaceLeftClipSkippedInFullLayout proves --no-truncate still prints the
// complete path, so the left clip only applies to a bounded layout.
func TestWorkspaceLeftClipSkippedInFullLayout(t *testing.T) {
	workspace := "/TopsailAI/src/topsailai_agent_cluster/internal/tui"
	rows := []SessionRow{{EndpointID: "ep", ProjectWorkspace: workspace, State: "running", CollectionStatus: protocol.CollectionSucceeded}}
	var out strings.Builder
	if err := RenderTable(&out, io.Discard, rows, nil, TableOptions{Width: 40, Full: true}); err != nil {
		t.Fatal(err)
	}
	if !strings.Contains(out.String(), workspace) {
		t.Fatalf("full layout truncated the workspace: %q", out.String())
	}
}
