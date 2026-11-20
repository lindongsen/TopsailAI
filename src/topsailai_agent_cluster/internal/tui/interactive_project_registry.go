package tui

import (
	"context"
	"fmt"
	"io"
	"sort"
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
		return interactiveProjectRemove(parent, api, state, strings.TrimSpace(strings.TrimPrefix(trimmed, "remove")), lines, out, trustedOut, diagnostics, options)
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
//
// With no selector the command renders the catalog and asks which entry to remove,
// because the operator who wants to remove a project is exactly the operator who
// needs to see which projects are registered first. Requiring them to run "project"
// and then retype a number costs two commands for one decision, and the second
// command is the one that can be typed wrong.
func interactiveProjectRemove(parent context.Context, api InteractiveAPI, state *interactiveState, rest string, lines <-chan lineReadResult, out, trustedOut, diagnostics io.Writer, options InteractiveOptions) error {
	if err := rejectInteractiveOption("project remove", rest); err != nil {
		return err
	}
	token := strings.TrimSpace(rest)
	if token == "" {
		return interactiveProjectRemoveGuided(parent, api, state, lines, out, trustedOut, diagnostics, options)
	}
	endpointID, projectID, projectPath, err := resolveProjectRemoveTarget(parent, api, state, token, lines, out, trustedOut, options.Color)
	if err != nil || projectID == "" {
		return err
	}
	return applyProjectRemoveRow(parent, api, state, endpointID, projectID, projectPath, lines, out, trustedOut, options)
}

// interactiveProjectRemoveGuided renders the catalog and asks which entry to remove.
//
// Three answers are three different outcomes and are reported as three different
// messages, because collapsing them would hide what happened:
//
//	<number>      remove that row, through the same confirmation every mutating
//	              operation uses
//	<id|name>     remove the row that value identifies, resolved against the table
//	              that was just printed
//	<empty>       remove nothing; the operator looked and kept the registry
//
// The question is written through trustedOut because it carries application styling,
// and the read uses parent rather than the command context so operator thinking time
// is never charged against the command deadline. The echo resolves through the same
// row label the table printed, so the label beside the number is the project that will
// be removed; an empty or unresolvable answer echoes nothing, because no choice was
// made.
func interactiveProjectRemoveGuided(parent context.Context, api InteractiveAPI, state *interactiveState, lines <-chan lineReadResult, out, trustedOut, diagnostics io.Writer, options InteractiveOptions) error {
	endpointID, projects, rendered, err := renderProjectCatalog(parent, api, state, "project remove", "", lines, out, trustedOut, diagnostics, options.Color)
	if err != nil || !rendered {
		// rendered is false for two different situations that were already reported
		// by the render: the operator cancelled the endpoint prompt, and the Endpoint
		// has no registered project. Neither offers anything to remove, so no
		// question is asked.
		return err
	}
	question := fmt.Sprintf("select project [1-%d] or press Enter to keep the registry unchanged: ", len(projects))
	if err := writeConfirmationQuestion(trustedOut, question, options.Color); err != nil {
		return err
	}
	echo := func(answer string) string {
		project, err := resolveProjectRemoveSelector(state.projectCatalog, answer)
		if err != nil {
			return ""
		}
		return RenderAnswerEcho(projectRowLabel(project), options.Color)
	}
	answer, ok := nextPromptLineWithEcho(parent, lines, trustedOut, echo)
	if !ok || answer.overflow || answer.err != nil {
		return fmt.Errorf("project selection requires a complete line")
	}
	choice := strings.TrimSpace(answer.line)
	if choice == "" {
		// An empty answer is a decision, not a failure: the operator saw the catalog
		// and chose to keep the registry. The rendered namespace stays in place, so
		// "project remove <number>" still works afterwards.
		_, err := fmt.Fprintln(out, "project registry unchanged")
		return err
	}
	project, err := resolveProjectRemoveSelector(state.projectCatalog, choice)
	if err != nil {
		return err
	}
	return applyProjectRemoveRow(parent, api, state, endpointID, project.ProjectID, project.Path, lines, out, trustedOut, options)
}

// resolveProjectRemoveSelector resolves one selector against the catalog the operator
// last saw.
//
// A number is a position in that table, so a number that was not printed is refused
// and never retried as an identifier: falling through would remove a project the
// operator never selected. An identifier or name is matched against the same rows, so
// the guided answer can name a project instead of counting rows.
func resolveProjectRemoveSelector(namespace *projectCatalogNamespace, token string) (protocol.Project, error) {
	if namespace == nil {
		return protocol.Project{}, fmt.Errorf("no project catalog has been rendered; run project first")
	}
	if number, numeric := parseRowNumber(token); numeric {
		project, ok := namespace.Rows[number]
		if !ok {
			return protocol.Project{}, fmt.Errorf("project remove %d: no such row in the rendered catalog", number)
		}
		return project, nil
	}
	rows := sortedProjectCatalogRows(namespace)
	matches := make([]protocol.Project, 0, 1)
	for _, project := range rows {
		if project.ProjectID == token {
			matches = append(matches, project)
		}
	}
	if len(matches) == 1 {
		return matches[0], nil
	}
	matches = matches[:0]
	for _, project := range rows {
		if project.Name != "" && project.Name == token {
			matches = append(matches, project)
		}
	}
	switch len(matches) {
	case 1:
		return matches[0], nil
	case 0:
		return protocol.Project{}, fmt.Errorf("project %q is not in the current catalog of endpoint %q; run project to see the catalog", token, namespace.EndpointID)
	default:
		// Several projects sharing a name is a real possibility, because a name is
		// chosen for a human. Removing the first would delete a registry entry the
		// operator did not choose, so the ambiguity is refused and the remedy names
		// the only unambiguous selector.
		ids := make([]string, 0, len(matches))
		for _, project := range matches {
			ids = append(ids, project.ProjectID)
		}
		sort.Strings(ids)
		return protocol.Project{}, fmt.Errorf("project %q is ambiguous: %d entries share that name (%s); select it by row number or project ID", token, len(matches), strings.Join(ids, ", "))
	}
}

// sortedProjectCatalogRows returns the rendered rows in row-number order, so a
// selector that matches several rows reports the same result on every run.
func sortedProjectCatalogRows(namespace *projectCatalogNamespace) []protocol.Project {
	numbers := make([]int, 0, len(namespace.Rows))
	for number := range namespace.Rows {
		numbers = append(numbers, number)
	}
	sort.Ints(numbers)
	projects := make([]protocol.Project, 0, len(numbers))
	for _, number := range numbers {
		projects = append(projects, namespace.Rows[number])
	}
	return projects
}

// applyProjectRemoveRow removes one resolved catalog row.
//
// It is the single submission path for the explicit form and the guided form, so the
// opaque provider slot, the pinned scope, the revalidation and the post-submit
// namespace drop cannot drift between the two surfaces.
func applyProjectRemoveRow(parent context.Context, api InteractiveAPI, state *interactiveState, endpointID, projectID, projectPath string, lines <-chan lineReadResult, out, trustedOut io.Writer, options InteractiveOptions) error {
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
		// The catalog the operator saw no longer describes the registry, so its
		// numbers are dropped rather than left to address a removed row.
		state.projectCatalog = nil
		_, err := fmt.Fprintln(out, "project registry changed; run project to see the current catalog")
		return err
	}
	target := confirmationTarget{ClusterSessionID: projectID, ProviderTarget: slot}
	return interactiveConfirmedAction(parent, api, &pinned, protocol.OperationProjectRemove, "project remove (registry entry only; the folder is not deleted)", target, "", ProjectRemovePayload(), lines, out, trustedOut, options, revalidate, postSubmit)
}

// projectRowLabel names one catalog row in operator-facing text.
//
// The name is preferred because it is what the table prints, and the opaque
// identifier follows so the operator can copy a value that `project remove` accepts.
// A row with no name falls back to the identifier alone rather than printing an empty
// pair of parentheses.
func projectRowLabel(project protocol.Project) string {
	if project.Name == "" {
		return project.ProjectID
	}
	return fmt.Sprintf("%s (%s)", project.Name, project.ProjectID)
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
