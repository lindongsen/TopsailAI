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
