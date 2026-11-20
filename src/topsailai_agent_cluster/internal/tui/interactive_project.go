package tui

import (
	"context"
	"fmt"
	"io"
	"strings"

	"topsailai_agent_cluster/internal/protocol"
)

// interactiveProjects renders the managed projects of one selected Endpoint.
func interactiveProjects(parent context.Context, api InteractiveAPI, state *interactiveState, rest string, lines <-chan lineReadResult, out, trustedOut, diagnostics io.Writer, color ColorPolicy) error {
	if err := rejectInteractiveOption("project", rest); err != nil {
		return err
	}
	_, _, _, err := renderProjectCatalog(parent, api, state, "project", strings.TrimSpace(rest), lines, out, trustedOut, diagnostics, color)
	return err
}

// renderProjectCatalog reads one Endpoint's project catalog, renders it, and records
// the row namespace the table produced.
//
// It is shared by the bare "project" read and by the no-argument "project remove"
// form, because both ask the same question before doing anything else: which projects
// does this machine have registered. Sharing the render keeps the two surfaces from
// drifting in columns, colour, truncation notice or namespace handling.
//
// The returned slice is empty and rendered is false when there is nothing to choose
// from, which happens in two different situations that must not be confused: the
// operator cancelled the endpoint prompt, and the Endpoint genuinely has no registered
// project. The first prints nothing, the second prints a statement, so the caller can
// tell them apart by rendered rather than by inspecting the slice.
func renderProjectCatalog(parent context.Context, api InteractiveAPI, state *interactiveState, command, target string, lines <-chan lineReadResult, out, trustedOut, diagnostics io.Writer, color ColorPolicy) (string, []protocol.Project, bool, error) {
	querier, ok := api.(ProjectCatalogQuerier)
	if !ok {
		return "", nil, false, fmt.Errorf("%s is unavailable: this client cannot query managed projects", command)
	}
	// The endpoint prompt waits for a human, so it runs on the parent context: a
	// command budget would expire while the operator is still reading the list and
	// would abort the REPL instead of the prompt. The bounded budget starts after
	// the endpoint is known, because only the provider read is command work.
	endpointID, err := liveReadEndpointID(parent, api, state, command, target, lines, out, trustedOut, color)
	if err != nil {
		return "", nil, false, err
	}
	// An empty identifier means the operator cancelled the endpoint prompt, so
	// there is nothing to read and no diagnostic to print.
	if endpointID == "" {
		return "", nil, false, nil
	}
	ctx, cancel := commandContext(parent)
	defer cancel()
	result, err := querier.GetProjectCatalog(ctx, endpointID)
	if err != nil {
		return "", nil, false, err
	}
	if result.ErrorCode != "" {
		return "", nil, false, fmt.Errorf("project catalog for endpoint %q failed: %s", endpointID, result.ErrorCode)
	}
	// The previous namespace is dropped before the catalog is rendered, so a row
	// number from an earlier table can never be applied to a project row.
	state.projectCatalog = nil
	if result.Truncated {
		if _, err := fmt.Fprintln(diagnostics, "project catalog is a bounded provider window; additional projects are not listed"); err != nil {
			return "", nil, false, err
		}
	}
	if len(result.Projects) == 0 {
		// An empty catalog is a real answer, so it is stated plainly instead of
		// rendering an empty table that looks like a rendering fault.
		_, err := fmt.Fprintf(out, "endpoint %q has no registered project; run project add <folder> to register one\n", endpointID)
		return endpointID, nil, false, err
	}
	options := TableOptionsFor(out)
	options.Color = color
	// The identifier column is dropped for the same reason the session list and the
	// model tables drop it: the operator selects a project by its row number, and the
	// opaque Cluster project ID only widens the table. The ID stays on the row, so
	// `project remove <project-id>` still accepts it.
	options.HideSessionID = true
	if err := RenderProjects(out, result.Projects, options); err != nil {
		return endpointID, nil, false, err
	}
	// The namespace is recorded only after a successful render, because a number
	// is a position in the table the operator actually saw.
	namespace := &projectCatalogNamespace{
		EndpointID: endpointID,
		Rows:       make(map[int]protocol.Project, len(result.Projects)),
	}
	for index, project := range result.Projects {
		namespace.Rows[index+1] = project
	}
	state.projectCatalog = namespace
	return endpointID, result.Projects, true, nil
}
