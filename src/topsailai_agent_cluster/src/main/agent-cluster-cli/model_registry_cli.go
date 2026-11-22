package main

import (
	"context"
	"fmt"
	"io"

	"topsailai_agent_cluster/internal/protocol"
	"topsailai_agent_cluster/internal/tui"
)

// modelRegistry renders the models one Endpoint offers to launches, together with
// the model a launch from that Endpoint would use now.
//
// It is the standalone form of the interactive bare "model" read outside session
// scope. The two surfaces share the view builder, the renderer and the error mapping,
// so a column, a colour or a refusal message cannot drift between them.
//
// The endpoint is mandatory because a registry belongs to one machine: a fleet-wide
// merge would have to invent an answer for "which model would a launch use" across
// machines that may each declare a different one.
func modelRegistry(ctx context.Context, api tui.CommandAPI, output, diagnostics io.Writer, target string, jsonMode bool, color tui.ColorPolicy) error {
	querier, ok := api.(tui.ModelRegistryQuerier)
	if !ok {
		return fmt.Errorf("model registry is unavailable: this client cannot query the endpoint model registry")
	}
	endpoint, err := tui.ResolveEndpointTarget(ctx, api, target)
	if err != nil {
		return err
	}
	registry, err := querier.GetModelRegistry(ctx, endpoint.EndpointID)
	if err != nil {
		return err
	}
	if registry.ErrorCode != "" {
		return tui.ModelRegistryError(endpoint.EndpointID, registry.ErrorCode)
	}
	view := tui.NewModelRegistryView(endpoint.EndpointID, registry)
	if jsonMode {
		return tui.RenderJSON(output, view)
	}
	if len(view.Rows) == 0 {
		// An empty registry is a real answer, so it is stated plainly instead of
		// rendering an empty table that looks like a rendering fault.
		_, err := fmt.Fprintf(output, "endpoint %q offers no model to launches; configure a model on the endpoint before starting an agent\n", endpoint.EndpointID)
		return err
	}
	options := tui.TableOptionsFor(output)
	options.Color = color
	// The identifier column is dropped for the same reason the interactive render
	// drops it: the table is read, not copied from, and the identifier is a long
	// opaque value that only widens the table. The --json document still carries it,
	// so a script keeps the selector that stays valid across renders.
	options.HideSessionID = true
	// The truncation and selection notices are written by the renderer itself, so
	// this path does not repeat them: one caveat is stated once.
	return tui.RenderModelRegistry(output, view, options)
}

// modelSet declares which model a launch from one Endpoint should use.
//
// The standalone surface has no rendered table, so a row number is rejected: a row
// number is a position in a table the operator saw, and no table was rendered here.
// The selector is resolved against a live registry read instead, so an unknown or
// unavailable model is refused before anything is submitted rather than being sent to
// the provider as an opaque value.
//
// The operation is Endpoint-scoped and target-less: it changes a machine-wide
// declaration, not a live process, so it carries no generation and no session. That
// is why the request below sets no ResourceID, and why the shared submission path
// leaves the intent without a target.
func modelSet(ctx context.Context, api tui.CommandAPI, output, diagnostics io.Writer, target, profile string, confirmed, jsonMode bool, waitTimeoutMS int64) error {
	if tui.IsRowNumber(profile) {
		return fmt.Errorf("model profile %q is a row number, which only exists after a rendered registry; name the model by model_profile_id or display name", profile)
	}
	querier, ok := api.(tui.ModelRegistryQuerier)
	if !ok {
		return fmt.Errorf("model registry is unavailable: this client cannot query the endpoint model registry")
	}
	endpoint, err := tui.ResolveEndpointTarget(ctx, api, target)
	if err != nil {
		return err
	}
	registry, err := querier.GetModelRegistry(ctx, endpoint.EndpointID)
	if err != nil {
		return err
	}
	if registry.ErrorCode != "" {
		return tui.ModelRegistryError(endpoint.EndpointID, registry.ErrorCode)
	}
	view := tui.NewModelRegistryView(endpoint.EndpointID, registry)
	row, err := tui.ResolveModelRegistrySelector(view, profile)
	if err != nil {
		return err
	}
	if !row.Available {
		// The registry already reported why this entry cannot be used, so the refusal
		// repeats that reason instead of asking for a confirmation the Endpoint would
		// then reject. The provider makes the same decision in the same execution path,
		// so the two cannot disagree about which entries are usable.
		reason := row.UnavailableReason
		if reason == "" {
			reason = "unavailable"
		}
		return fmt.Errorf("model %q is unavailable (%s); run model registry %s to see the current registry", tui.ModelRegistryRowLabel(row), reason, endpoint.EndpointID)
	}
	payload, err := tui.ModelSetPayload(row.ModelProfileID)
	if err != nil {
		return err
	}
	return submitActionWithProgress(ctx, api, output, diagnostics, tui.ActionRequest{
		Operation:      protocol.OperationAgentModelSet,
		OperationLabel: "model set",
		EndpointID:     endpoint.EndpointID,
		Payload:        payload,
		Confirmed:      confirmed,
		WaitTimeoutMS:  waitTimeoutMS,
	}, jsonMode)
}
