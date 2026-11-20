package tui

import (
	"context"
	"fmt"
	"io"
	"strings"

	"topsailai_agent_cluster/internal/protocol"
)

// projectCatalogNamespace is the project-number namespace produced by the most
// recent project catalog render.
//
// A number is a position in the table the operator last saw, so it is resolved
// against this namespace and never treated as durable identity. The namespace is
// dropped whenever another table renders, so a stale number cannot address a
// project the operator is no longer looking at.
type projectCatalogNamespace struct {
	EndpointID string
	Rows       map[int]protocol.Project
}

// interactiveProject dispatches the project command in the interactive surface.
//
// The grammar is "project [endpoint]" for the read, "project add <folder> [name]"
// and "project remove <row|project-id>" for the two registry mutations. The read
// form stays the default so the existing command keeps working.
func interactiveProject(parent context.Context, api InteractiveAPI, state *interactiveState, rest string, lines <-chan lineReadResult, out, trustedOut, diagnostics io.Writer, options InteractiveOptions) error {
	trimmed := strings.TrimSpace(rest)
	if trimmed == "add" || strings.HasPrefix(trimmed, "add ") {
		return interactiveProjectAdd(parent, api, state, strings.TrimSpace(strings.TrimPrefix(trimmed, "add")), lines, out, trustedOut, options)
	}
	if trimmed == "remove" || strings.HasPrefix(trimmed, "remove ") {
		return interactiveProjectRemove(parent, api, state, strings.TrimSpace(strings.TrimPrefix(trimmed, "remove")), lines, out, trustedOut, options)
	}
	return interactiveProjects(parent, api, state, rest, lines, out, trustedOut, diagnostics, options.Color)
}

// revalidateEndpointOnline confirms the pinned Endpoint is still registered and
// online.
//
// A project operation is Endpoint-scoped, so it has no session to revalidate. The
// confirmed form would otherwise fall back to the session-scoped selection check,
// which refuses every project command because no session is selected.
func revalidateEndpointOnline(ctx context.Context, api InteractiveAPI, endpointID string) error {
	endpoints, err := api.ListEndpoints(ctx)
	if err != nil {
		return err
	}
	for _, endpoint := range endpoints {
		if endpoint.EndpointID == endpointID {
			return validateEndpointOnline(endpoint)
		}
	}
	return fmt.Errorf("endpoint %q is not registered", endpointID)
}

// interactiveProjectAdd registers one folder in the selected Endpoint's project
// registry.
//
// The folder is confined by the Endpoint to its configured project root, so this
// surface forwards what the operator typed and never decides whether a folder is
// acceptable. The command edits the registry entry only: no project data is
// created or modified.
func interactiveProjectAdd(parent context.Context, api InteractiveAPI, state *interactiveState, rest string, lines <-chan lineReadResult, out, trustedOut io.Writer, options InteractiveOptions) error {
	if err := rejectInteractiveOption("project add", rest); err != nil {
		return err
	}
	fields := strings.Fields(rest)
	if len(fields) == 0 || len(fields) > 2 {
		return fmt.Errorf("usage: project add <folder> [name]")
	}
	endpointID, err := liveReadEndpointID(parent, api, state, "project add", "", lines, out, trustedOut, options.Color)
	if err != nil || endpointID == "" {
		return err
	}
	name := ""
	if len(fields) == 2 {
		name = fields[1]
	}
	payload, err := ProjectAddPayload(fields[0], name)
	if err != nil {
		return err
	}
	pinned := *state
	pinned.EndpointID = endpointID
	pinned.Invalidated = false
	pinned.InvalidReason = ""
	revalidate := func(revalidateCtx context.Context) error {
		return revalidateEndpointOnline(revalidateCtx, api, endpointID)
	}
	postSubmit := func(context.Context, map[string]any) error {
		// The catalog the operator saw no longer describes the registry, so the
		// number namespace is dropped rather than left to address a stale row.
		state.projectCatalog = nil
		_, err := fmt.Fprintln(out, "project registry changed; run project to see the current catalog")
		return err
	}
	// The confirmation names the folder, because that is the value the operator
	// typed and the only one that identifies what is being registered. The
	// operation carries no target, so the label is presentation only.
	target := confirmationTarget{ClusterSessionID: fields[0]}
	return interactiveConfirmedAction(parent, api, &pinned, protocol.OperationProjectAdd, "project add", target, "", payload, lines, out, trustedOut, options, revalidate, postSubmit)
}

// interactiveProjectRemove removes one registry entry from the selected
// Endpoint's project catalog.
//
// The selector is a rendered row number or the opaque Cluster project ID. A row
// number is resolved locally against the last rendered catalog, so it never
// becomes durable identity. The command removes the registry entry only: the
// folder on disk is never deleted, and the confirmation says so.
func interactiveProjectRemove(parent context.Context, api InteractiveAPI, state *interactiveState, rest string, lines <-chan lineReadResult, out, trustedOut io.Writer, options InteractiveOptions) error {
	if err := rejectInteractiveOption("project remove", rest); err != nil {
		return err
	}
	token := strings.TrimSpace(rest)
	if token == "" {
		return fmt.Errorf("usage: project remove <row|project-id>")
	}
	endpointID, projectID, projectPath, err := resolveProjectRemoveTarget(parent, api, state, token, lines, out, trustedOut, options.Color)
	if err != nil || projectID == "" {
		return err
	}
	slot, err := ProjectTargetSlot(projectPath)
	if err != nil {
		return err
	}
	pinned := *state
	pinned.EndpointID = endpointID
	pinned.Invalidated = false
	pinned.InvalidReason = ""
	revalidate := func(revalidateCtx context.Context) error {
		return revalidateEndpointOnline(revalidateCtx, api, endpointID)
	}
	postSubmit := func(context.Context, map[string]any) error {
		state.projectCatalog = nil
		_, err := fmt.Fprintln(out, "project registry changed; run project to see the current catalog")
		return err
	}
	target := confirmationTarget{ClusterSessionID: projectID, ProviderTarget: slot}
	return interactiveConfirmedAction(parent, api, &pinned, protocol.OperationProjectRemove, "project remove (registry entry only; the folder is not deleted)", target, "", ProjectRemovePayload(), lines, out, trustedOut, options, revalidate, postSubmit)
}

// resolveProjectRemoveTarget resolves one project selector to the Endpoint, the
// opaque Cluster project ID and the provider path.
//
// A row number is resolved against the last rendered catalog, because a number is
// a position in a table the operator saw. A project ID is resolved against a fresh
// catalog read, because the operator may name a project the current table does not
// show, and the provider path is required to address the registry entry exactly.
func resolveProjectRemoveTarget(parent context.Context, api InteractiveAPI, state *interactiveState, token string, lines <-chan lineReadResult, out, trustedOut io.Writer, color ColorPolicy) (string, string, string, error) {
	if row, numeric := parseRowNumber(token); numeric {
		if state.projectCatalog == nil {
			return "", "", "", fmt.Errorf("project remove %s: no project catalog has been rendered; run project first", token)
		}
		project, ok := state.projectCatalog.Rows[row]
		if !ok {
			return "", "", "", fmt.Errorf("project remove %s: no such row in the rendered catalog", token)
		}
		return state.projectCatalog.EndpointID, project.ProjectID, project.Path, nil
	}
	endpointID, err := liveReadEndpointID(parent, api, state, "project remove", "", lines, out, trustedOut, color)
	if err != nil || endpointID == "" {
		return "", "", "", err
	}
	querier, ok := api.(ProjectCatalogQuerier)
	if !ok {
		return "", "", "", fmt.Errorf("project remove is unavailable: this client cannot query managed projects")
	}
	ctx, cancel := commandContext(parent)
	defer cancel()
	catalog, err := querier.GetProjectCatalog(ctx, endpointID)
	if err != nil {
		return "", "", "", err
	}
	if catalog.ErrorCode != "" {
		return "", "", "", fmt.Errorf("project catalog for endpoint %q failed: %s", endpointID, catalog.ErrorCode)
	}
	for _, project := range catalog.Projects {
		if project.ProjectID == token {
			return endpointID, project.ProjectID, project.Path, nil
		}
	}
	return "", "", "", fmt.Errorf("project %q is not in the current catalog of endpoint %q", token, endpointID)
}
