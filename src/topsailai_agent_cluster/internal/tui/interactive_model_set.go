package tui

import (
	"context"
	"fmt"
	"io"
	"sort"
	"strings"

	"topsailai_agent_cluster/internal/protocol"
)

// modelRegistryNamespace is the environment-model-number namespace produced by the
// most recent endpoint registry render.
//
// A number is a position in the table the operator last saw, so it is resolved
// against this namespace and never treated as durable identity. It is separate from
// modelCatalogNamespace because the two tables describe different subjects: a catalog
// row is a profile one session can select, while a registry row is a model this
// machine offers to launches. Sharing one namespace would let a number silently change
// meaning depending on which table was rendered last.
type modelRegistryNamespace struct {
	EndpointID string
	Rows       map[int]ModelRegistryViewRow
}

// interactiveModelSet declares which model a launch from one Endpoint should use.
//
// The grammar is "model set <row|model-profile-id>". The selector resolves against the
// registry the operator last saw, so a number can only ever address a row that was
// printed. The operation is Endpoint-scoped and target-less: it changes a machine-wide
// declaration, not a live process, so it carries no generation and no session.
//
// The endpoint is resolved through the same helper the registry read uses, so
// workspace scope asks which machine to change and endpoint scope changes the current
// one. A row number is resolved against the namespace recorded by the last registry
// render, which is why the render now records one.
func interactiveModelSet(parent context.Context, api InteractiveAPI, state *interactiveState, rest string, lines <-chan lineReadResult, out, trustedOut io.Writer, options InteractiveOptions) error {
	if err := rejectInteractiveOption("model set", rest); err != nil {
		return err
	}
	token := strings.TrimSpace(rest)
	if token == "" {
		return fmt.Errorf("usage: model set <row|model-profile-id>")
	}
	endpointID, row, err := resolveModelSetTarget(parent, api, state, token, lines, out, trustedOut, options.Color)
	if err != nil || row.ModelProfileID == "" {
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
		return fmt.Errorf("model %q is unavailable (%s); run model to see the current registry", modelRegistryRowLabel(row), reason)
	}
	payload, err := ModelSetPayload(row.ModelProfileID)
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
		// The registry the operator saw no longer describes the machine, so its
		// numbers are dropped rather than left to address a stale row.
		state.modelRegistry = nil
		_, err := fmt.Fprintf(out, "model %q is now the launch default; run model to see the updated registry\n", modelRegistryRowLabel(row))
		return err
	}
	// The confirmation names the model rather than the endpoint, because the model is
	// the value the operator chose and the only one that identifies what is changing.
	// The operation carries no target, so the label is presentation only.
	target := confirmationTarget{ClusterSessionID: modelRegistryRowLabel(row)}
	return interactiveConfirmedAction(parent, api, &pinned, protocol.OperationAgentModelSet, "model set", target, "", payload, lines, out, trustedOut, options, revalidate, postSubmit)
}

// resolveModelSetTarget resolves one selector to the Endpoint and the registry row it
// names.
//
// A row number is resolved against the last rendered registry, because a number is a
// position in a table the operator saw. An identifier is resolved against a fresh
// registry read, because the operator may name a model the current table does not
// show, and the Endpoint needs the exact opaque identifier rather than a guess.
//
// The endpoint is resolved before the selector, because a row number belongs to the
// machine whose table was rendered: resolving the number against one machine and then
// changing another would apply a position from one table to a different machine.
func resolveModelSetTarget(parent context.Context, api InteractiveAPI, state *interactiveState, token string, lines <-chan lineReadResult, out, trustedOut io.Writer, color ColorPolicy) (string, ModelRegistryViewRow, error) {
	if row, numeric := parseRowNumber(token); numeric {
		if state.modelRegistry == nil {
			return "", ModelRegistryViewRow{}, fmt.Errorf("model set %s: no model registry has been rendered; run model first", token)
		}
		rendered, ok := state.modelRegistry.Rows[row]
		if !ok {
			return "", ModelRegistryViewRow{}, fmt.Errorf("model set %s: no such row in the rendered registry", token)
		}
		return state.modelRegistry.EndpointID, rendered, nil
	}
	endpointID, err := liveReadEndpointID(parent, api, state, "model set", "", lines, out, trustedOut, color)
	if err != nil || endpointID == "" {
		return "", ModelRegistryViewRow{}, err
	}
	querier, ok := api.(ModelRegistryQuerier)
	if !ok {
		return "", ModelRegistryViewRow{}, fmt.Errorf("model set is unavailable: this client cannot query the endpoint model registry")
	}
	ctx, cancel := commandContext(parent)
	defer cancel()
	registry, err := querier.GetModelRegistry(ctx, endpointID)
	if err != nil {
		return "", ModelRegistryViewRow{}, err
	}
	if registry.ErrorCode != "" {
		return "", ModelRegistryViewRow{}, modelRegistryError(endpointID, registry.ErrorCode)
	}
	view := NewModelRegistryView(endpointID, registry)
	matches := make([]ModelRegistryViewRow, 0, 1)
	for _, row := range view.Rows {
		if row.ModelProfileID == token {
			matches = append(matches, row)
		}
	}
	if len(matches) == 1 {
		return endpointID, matches[0], nil
	}
	// The current row is marked with a leading "* " in the rendered table, so an
	// operator copying a row from the screen types the marker too. Both spellings are
	// accepted, and the bare name is matched first, so a display name that genuinely
	// begins with "*" still resolves as itself instead of being read as a marker.
	matches = matches[:0]
	for _, row := range view.Rows {
		if row.ProviderDisplayName == "" {
			continue
		}
		if row.ProviderDisplayName == token || modelCurrentMarker+row.ProviderDisplayName == token {
			matches = append(matches, row)
		}
	}
	switch len(matches) {
	case 1:
		return endpointID, matches[0], nil
	case 0:
		return "", ModelRegistryViewRow{}, fmt.Errorf("model %q is not in the current registry of endpoint %q; run model to see the registry", token, endpointID)
	default:
		// Several rows sharing a display name is a real possibility, because a display
		// name is chosen for a human. Selecting the first would apply a model the
		// operator did not choose, so the ambiguity is refused and the remedy names the
		// only unambiguous selector.
		ids := make([]string, 0, len(matches))
		for _, row := range matches {
			ids = append(ids, row.ModelProfileID)
		}
		sort.Strings(ids)
		return "", ModelRegistryViewRow{}, fmt.Errorf("model %q is ambiguous: %d entries share that display name (%s); select it by row number or model_profile_id", token, len(matches), strings.Join(ids, ", "))
	}
}

// modelRegistryRowLabel names one registry row in operator-facing text.
//
// The display name is preferred because it is what the table prints, and the opaque
// identifier follows so the operator can copy a value that `model set` accepts. A row
// with no display name falls back to the identifier alone rather than printing an
// empty pair of parentheses.
func modelRegistryRowLabel(row ModelRegistryViewRow) string {
	if row.ProviderDisplayName == "" {
		return row.ModelProfileID
	}
	return fmt.Sprintf("%s (%s)", row.ProviderDisplayName, row.ModelProfileID)
}
