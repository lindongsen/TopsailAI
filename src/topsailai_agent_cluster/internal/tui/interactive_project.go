package tui

import (
	"context"
	"fmt"
	"io"
	"strings"
)

// interactiveProjects renders the managed projects of one selected Endpoint.
func interactiveProjects(parent context.Context, api InteractiveAPI, state *interactiveState, rest string, lines <-chan lineReadResult, out, trustedOut, diagnostics io.Writer, color ColorPolicy) error {
	if err := rejectInteractiveOption("project", rest); err != nil {
		return err
	}
	querier, ok := api.(ProjectCatalogQuerier)
	if !ok {
		return fmt.Errorf("project is unavailable: this client cannot query managed projects")
	}
	endpointID, err := liveReadEndpointID(parent, api, state, "project", strings.TrimSpace(rest), lines, out, trustedOut, color)
	if err != nil || endpointID == "" {
		return err
	}
	ctx, cancel := commandContext(parent)
	defer cancel()
	result, err := querier.GetProjectCatalog(ctx, endpointID)
	if err != nil {
		return err
	}
	if result.ErrorCode != "" {
		return fmt.Errorf("project catalog for endpoint %q failed: %s", endpointID, result.ErrorCode)
	}
	if result.Truncated {
		if _, err := fmt.Fprintln(diagnostics, "project catalog is a bounded provider window; additional projects are not listed"); err != nil {
			return err
		}
	}
	options := TableOptionsFor(out)
	options.Color = color
	return RenderProjects(out, result.Projects, options)
}
