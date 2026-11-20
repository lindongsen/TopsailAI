package tui

import (
	"context"
	"fmt"
	"io"
	"strconv"

	"topsailai_agent_cluster/internal/protocol"
)

// ProjectCatalogQuerier reads one Endpoint's live managed-project catalog.
type ProjectCatalogQuerier interface {
	GetProjectCatalog(context.Context, string) (protocol.ProjectCatalog, error)
}

var projectColumns = []tableColumn{
	{key: columnNo, header: "NO", cap: 4},
	{key: columnName, header: "PROJECT_NAME", cap: 48, wide: true},
	{key: columnID, header: "PROJECT_ID", cap: 36},
	{key: columnWorkspace, header: "PATH", cap: workspaceColumnCap, grow: true, leftClip: true},
}

// RenderProjects writes one managed-project catalog as a numbered table.
func RenderProjects(out io.Writer, projects []protocol.Project, options TableOptions) error {
	cells := make([][]string, 0, len(projects))
	states := make([][]string, 0, len(projects))
	styles := make([]string, 0, len(projects))
	for index, project := range projects {
		values := map[string]string{
			columnNo:        strconv.Itoa(index + 1),
			columnName:      escapeCell(project.Name),
			columnID:        escapeCell(project.ProjectID),
			columnWorkspace: escapeCell(project.Path),
		}
		cells = append(cells, projectCells(values, projectColumns))
		states = append(states, make([]string, len(projectColumns)))
		styles = append(styles, stateStyle("ok"))
	}
	widths := measureColumns(cells, projectColumns, options.Full)
	return writeTable(out, columnHeaders(projectColumns), cells, states, styles, widths, projectColumns, options)
}

// Projects renders the live managed-project catalog of one Endpoint.
func (r CommandRunner) Projects(ctx context.Context, out, diagnostics io.Writer, target string, jsonMode bool, options TableOptions) error {
	querier, ok := r.API.(ProjectCatalogQuerier)
	if !ok {
		return fmt.Errorf("project is unavailable: this client cannot query managed projects")
	}
	endpoint, err := resolveHistoryEndpoint(ctx, r.API, target)
	if err != nil {
		return err
	}
	result, err := querier.GetProjectCatalog(ctx, endpoint.EndpointID)
	if err != nil {
		return err
	}
	if result.ErrorCode != "" {
		return fmt.Errorf("project catalog for endpoint %q failed: %s", endpoint.EndpointID, result.ErrorCode)
	}
	if jsonMode {
		return RenderJSON(out, result)
	}
	if result.Truncated {
		if _, err := fmt.Fprintln(diagnostics, "project catalog is a bounded provider window; additional projects are not listed"); err != nil {
			return err
		}
	}
	return RenderProjects(out, result.Projects, options)
}
