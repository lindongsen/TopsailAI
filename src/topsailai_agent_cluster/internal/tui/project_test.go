package tui

import (
	"strings"
	"testing"

	"topsailai_agent_cluster/internal/protocol"
)

// TestRenderProjectsShowsClusterIdentityAndPath proves the project command renders
// the standard Cluster identity rather than a Provider key or Provider row.
func TestRenderProjectsShowsClusterIdentityAndPath(t *testing.T) {
	projects := []protocol.Project{
		{ProjectID: "prj_alpha", Name: "Alpha", Path: "/work/alpha"},
		{ProjectID: "prj_beta", Name: "Beta", Path: "/work/beta"},
	}
	var out strings.Builder
	if err := RenderProjects(&out, projects, TableOptions{Width: 160, Full: true}); err != nil {
		t.Fatal(err)
	}
	rendered := out.String()
	for _, expected := range []string{"NO", "PROJECT_NAME", "PROJECT_ID", "PATH", "prj_alpha", "Alpha", "/work/alpha", "prj_beta", "Beta", "/work/beta"} {
		if !strings.Contains(rendered, expected) {
			t.Fatalf("project table does not contain %q: %q", expected, rendered)
		}
	}
}

// TestProjectLayoutHidesTheIdentifierColumn proves the opaque project identifier is
// dropped when the caller asked for the interactive layout, so the row number, the
// name and the path remain readable.
func TestProjectLayoutHidesTheIdentifierColumn(t *testing.T) {
	wide := layoutProjectColumns(TableOptions{})
	if !hasColumn(wide, columnID) {
		t.Fatalf("wide layout must keep %q", columnID)
	}
	narrow := layoutProjectColumns(TableOptions{HideSessionID: true})
	if hasColumn(narrow, columnID) {
		t.Fatalf("interactive layout must drop %q", columnID)
	}
	for _, key := range []string{columnNo, columnName, columnWorkspace} {
		if !hasColumn(narrow, key) {
			t.Fatalf("interactive layout must keep %q: %#v", key, narrow)
		}
	}
}

// TestInteractiveProjectHidesTheIdentifierColumn proves the rendered interactive
// table omits PROJECT_ID while the standalone command keeps it.
//
// The two surfaces are asserted together because the flag is one shared option: a
// change that hides the column everywhere would pass the interactive assertion and
// silently remove the identity from the script-parsed output.
func TestInteractiveProjectHidesTheIdentifierColumn(t *testing.T) {
	stub := projectRegistryFixture()
	output, diagnostics := runScope(t, stub, "cd host-one/endpoint-1\nproject\nexit\n", ColorPolicy{})
	if diagnostics != "" {
		t.Fatalf("unexpected diagnostics: %q", diagnostics)
	}
	for _, expected := range []string{"NO", "PROJECT_NAME", "PATH", "Alpha", "/work/alpha", "Beta", "/work/beta"} {
		if !strings.Contains(output, expected) {
			t.Fatalf("interactive project table is missing %q: %q", expected, output)
		}
	}
	for _, hidden := range []string{"PROJECT_ID", "prj_alpha", "prj_beta"} {
		if strings.Contains(output, hidden) {
			t.Fatalf("interactive project table must not print %q: %q", hidden, output)
		}
	}

	// The standalone surface renders through the same function with the boundary
	// options only, so this asserts the real standalone layout rather than a copy.
	var standalone strings.Builder
	if err := RenderProjects(&standalone, stub.catalog.Projects, TableOptionsFor(&standalone)); err != nil {
		t.Fatal(err)
	}
	if !strings.Contains(standalone.String(), "PROJECT_ID") || !strings.Contains(standalone.String(), "prj_alpha") {
		t.Fatalf("standalone project table must keep the identity: %q", standalone.String())
	}
}
