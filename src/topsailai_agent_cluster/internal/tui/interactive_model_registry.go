package tui

import (
	"context"
	"fmt"
	"io"

	"topsailai_agent_cluster/internal/protocol"
)

// interactiveModelRegistry renders the models one Endpoint offers to launches,
// together with the model a launch from that Endpoint would use now.
//
// It is the no-argument form of "model" outside session scope. Session scope keeps
// its existing meaning, because there the scope already names one session and a bare
// "model" can only mean that session's catalog. Outside session scope there is no
// session to list profiles for, so the question the operator is asking is about the
// machine: which models can a launch here use, and which one is in use.
//
// The endpoint is resolved through the same helper history and project use, so
// workspace scope prompts for one and endpoint scope uses the current one. The
// argument is deliberately not accepted as an endpoint identifier here: outside
// session scope the argument already means a session row number or a provider
// session identifier, and giving one token two meanings would make a provider
// session identifier that happens to equal an endpoint name unresolvable.
func interactiveModelRegistry(parent context.Context, api InteractiveAPI, state *interactiveState, rest string, lines <-chan lineReadResult, out, trustedOut, diagnostics io.Writer, options InteractiveOptions) error {
	if err := rejectInteractiveOption("model", rest); err != nil {
		return err
	}
	querier, ok := api.(ModelRegistryQuerier)
	if !ok {
		return fmt.Errorf("model is unavailable: this client cannot query the endpoint model registry")
	}
	// The endpoint prompt waits for a human, so it runs on the parent context: a
	// command budget would expire while the operator is still reading the list and
	// would abort the REPL instead of the prompt. The bounded budget starts after
	// the endpoint is known, because only the provider read is command work.
	endpointID, err := liveReadEndpointID(parent, api, state, "model", "", lines, out, trustedOut, options.Color)
	if err != nil {
		return err
	}
	// An empty identifier means the operator cancelled the endpoint prompt, so
	// there is nothing to read and no diagnostic to print.
	if endpointID == "" {
		return nil
	}
	ctx, cancel := commandContext(parent)
	defer cancel()
	registry, err := querier.GetModelRegistry(ctx, endpointID)
	if err != nil {
		return err
	}
	if registry.ErrorCode != "" {
		return modelRegistryError(endpointID, registry.ErrorCode)
	}
	view := NewModelRegistryView(endpointID, registry)
	// Every other row-number namespace is dropped before this table is rendered, so
	// a number from a previous table can never be applied to a row of this one. The
	// registry itself records no namespace, because it offers no operation: a
	// number that selected nothing would look selectable and do nothing.
	state.Rows = nil
	state.history = nil
	state.modelCatalog = nil
	state.projectCatalog = nil
	if len(view.Rows) == 0 {
		// An empty registry is a real answer, so it is stated plainly instead of
		// rendering an empty table that looks like a rendering fault.
		_, err := fmt.Fprintf(out, "endpoint %q offers no model to launches; configure a model on the endpoint before starting an agent\n", endpointID)
		return err
	}
	tableOptions := TableOptionsFor(out)
	tableOptions.Color = options.Color
	// The identifier column is dropped for the same reason the session catalog drops
	// it: the table is read, not copied from, and the identifier is a long opaque
	// value that only widens the table.
	tableOptions.HideSessionID = true
	if err := RenderModelRegistry(out, view, tableOptions); err != nil {
		return err
	}
	// The truncation notice is a diagnostic rather than part of the answer, because
	// it describes the read rather than the machine.
	if view.Truncated {
		if _, err := fmt.Fprintln(diagnostics, "model registry is a bounded provider window; additional models are not listed"); err != nil {
			return err
		}
	}
	return nil
}

// modelRegistryError maps a standard registry error code to an operator message.
//
// The unsupported case is named separately because it is not a failure: the Endpoint
// is healthy and simply has no adapter that can answer the question. Reporting it as
// a provider error would send the operator to investigate a provider that is behaving
// correctly, and would hide the real remedy, which is to configure an adapter.
func modelRegistryError(endpointID, code string) error {
	switch code {
	case protocol.ModelRegistryUnsupported:
		return fmt.Errorf("the model registry is unavailable for endpoint %q: no configured adapter can report the models it offers", endpointID)
	case protocol.ModelRegistrySelectionInvalid:
		return fmt.Errorf("endpoint %q holds a model selection that cannot be resolved; correct or clear it on the endpoint", endpointID)
	default:
		return fmt.Errorf("the model registry for endpoint %q failed: %s", endpointID, code)
	}
}
