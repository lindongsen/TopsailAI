package tui

import (
	"context"
	"encoding/json"
	"fmt"
	"io"
	"strconv"
	"strings"

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

// ProjectAddPayload builds the standard payload for one project registration.
//
// The folder is forwarded as the operator typed it. The Endpoint confines it to
// the configured project root and rewrites it with the resolved path, so the
// client never decides whether a folder is acceptable and never resolves a
// symlink on the Endpoint's behalf.
func ProjectAddPayload(folder, name string) (json.RawMessage, error) {
	payload := protocol.ProjectAddPayload{Folder: strings.TrimSpace(folder), Name: strings.TrimSpace(name)}
	if err := payload.Validate(); err != nil {
		return nil, err
	}
	encoded, err := json.Marshal(payload)
	if err != nil {
		return nil, fmt.Errorf("encode project add payload: %w", err)
	}
	return encoded, nil
}

// ProjectRemovePayload builds the standard payload for one project removal.
//
// The payload is empty by contract: the target carries the identity, and the
// provider path travels in the opaque slot. A payload field here would be a
// second way to name the same project.
func ProjectRemovePayload() json.RawMessage {
	return json.RawMessage(`{}`)
}

// ProjectTargetSlot builds the opaque provider addressing slot for one project.
//
// The Endpoint mapping key is a digest over the project path, so the Endpoint
// cannot recover the path from the key. The caller already holds the path from
// the catalog it rendered, so it supplies the slot and the Provider binds the
// slot to the mapping key by recomputing the digest locally. The Cluster never
// interprets the slot's contents.
func ProjectTargetSlot(path string) (string, error) {
	trimmed := strings.TrimSpace(path)
	if trimmed == "" {
		return "", fmt.Errorf("project target requires a project path")
	}
	encoded, err := json.Marshal(map[string]string{"project_path": trimmed})
	if err != nil {
		return "", fmt.Errorf("encode project target slot: %w", err)
	}
	return string(encoded), nil
}
