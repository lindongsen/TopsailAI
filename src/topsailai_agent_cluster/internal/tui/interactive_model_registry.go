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
	_, _, _, err := renderModelRegistry(parent, api, state, "model", lines, out, trustedOut, diagnostics, options)
	return err
}

// renderModelRegistry reads one Endpoint's model registry, renders it, and records the
// row namespace the table produced.
//
// It is shared by the bare "model" read and by the no-argument "model set" form,
// because both ask the same question before doing anything else: which models does
// this machine offer, and which one is in use. Sharing the render keeps the two
// surfaces from drifting in columns, colour, truncation notice or namespace handling.
//
// The returned view is empty and rendered is false when there is nothing to choose
// from, which happens in two different situations that must not be confused: the
// operator cancelled the endpoint prompt, and the Endpoint genuinely offers no model.
// The first prints nothing, the second prints a statement, so the caller can tell them
// apart by rendered rather than by inspecting the view.
func renderModelRegistry(parent context.Context, api InteractiveAPI, state *interactiveState, command string, lines <-chan lineReadResult, out, trustedOut, diagnostics io.Writer, options InteractiveOptions) (string, ModelRegistryView, bool, error) {
	querier, ok := api.(ModelRegistryQuerier)
	if !ok {
		return "", ModelRegistryView{}, false, fmt.Errorf("%s is unavailable: this client cannot query the endpoint model registry", command)
	}
	// The endpoint prompt waits for a human, so it runs on the parent context: a
	// command budget would expire while the operator is still reading the list and
	// would abort the REPL instead of the prompt. The bounded budget starts after
	// the endpoint is known, because only the provider read is command work.
	endpointID, err := liveReadEndpointID(parent, api, state, command, "", lines, out, trustedOut, options.Color)
	if err != nil {
		return "", ModelRegistryView{}, false, err
	}
	// An empty identifier means the operator cancelled the endpoint prompt, so
	// there is nothing to read and no diagnostic to print.
	if endpointID == "" {
		return "", ModelRegistryView{}, false, nil
	}
	ctx, cancel := commandContext(parent)
	defer cancel()
	registry, err := querier.GetModelRegistry(ctx, endpointID)
	if err != nil {
		return "", ModelRegistryView{}, false, err
	}
	if registry.ErrorCode != "" {
		return "", ModelRegistryView{}, false, modelRegistryError(endpointID, registry.ErrorCode)
	}
	view := NewModelRegistryView(endpointID, registry)
	// Every other row-number namespace is dropped before this table is rendered, so
	// a number from a previous table can never be applied to a row of this one. The
	// registry's own namespace is dropped here too and recorded only after a
	// successful render, because a number is a position in the table the operator
	// actually saw.
	state.Rows = nil
	state.history = nil
	state.modelCatalog = nil
	state.projectCatalog = nil
	state.modelRegistry = nil
	if len(view.Rows) == 0 {
		// An empty registry is a real answer, so it is stated plainly instead of
		// rendering an empty table that looks like a rendering fault.
		_, err := fmt.Fprintf(out, "endpoint %q offers no model to launches; configure a model on the endpoint before starting an agent\n", endpointID)
		return endpointID, view, false, err
	}
	tableOptions := TableOptionsFor(out)
	tableOptions.Color = options.Color
	// The identifier column is dropped for the same reason the session catalog drops
	// it: the table is read, not copied from, and the identifier is a long opaque
	// value that only widens the table.
	tableOptions.HideSessionID = true
	if err := RenderModelRegistry(out, view, tableOptions); err != nil {
		return endpointID, view, false, err
	}
	// The namespace is recorded only after a successful render, because a number is
	// a position in the table the operator actually saw. It is recorded even when the
	// table is bounded, because the rows that were printed are exactly the rows a
	// number may address.
	state.modelRegistry = &modelRegistryNamespace{
		EndpointID: endpointID,
		Rows:       make(map[int]ModelRegistryViewRow, len(view.Rows)),
	}
	for _, row := range view.Rows {
		state.modelRegistry.Rows[row.No] = row
	}
	// The truncation notice is a diagnostic rather than part of the answer, because
	// it describes the read rather than the machine.
	if view.Truncated {
		if _, err := fmt.Fprintln(diagnostics, "model registry is a bounded provider window; additional models are not listed"); err != nil {
			return endpointID, view, false, err
		}
	}
	return endpointID, view, true, nil
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
