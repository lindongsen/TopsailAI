package tui

import (
	"context"
	"encoding/json"
	"fmt"
	"io"
	"sort"
	"strings"

	"topsailai_agent_cluster/internal/protocol"
)

// modelCatalogNamespace is the profile-number namespace produced by one model
// catalog render.
//
// It is separate from the list and history namespaces, because a profile number and
// a session row number are different things: a profile number selects a model
// configuration, while a session row number selects a session. Sharing one namespace
// would let a number silently change meaning depending on which table was rendered
// last.
type modelCatalogNamespace struct {
	EndpointID          string
	ClusterSessionID    string
	ProviderSessionID   string
	ProviderDisplayName string
	ProviderGeneration  string
	Rows                map[int]ModelCatalogViewRow
}

// IsRowNumber reports whether token is a rendered row number.
//
// It is exported because the standalone surface must reject a row number for the
// same reason the interactive surface resolves one: a row number is a position in a
// table the operator saw, so it has no meaning where no table was rendered.
func IsRowNumber(token string) bool {
	_, numeric := parseRowNumber(token)
	return numeric
}

// interactiveModel lists the model profiles one session can select, or applies one
// profile to that session.
//
// The grammar is "model [session] [profile]", which covers the documented
// "model <number-or-session>" form and the two-token form the standalone surface
// needs:
//
//	model                        list the profiles of the current session
//	model <session>              list the profiles of one named session
//	model <number>               apply that profile to the current session
//	model <session> <profile>    apply one profile to one named session
//
// A number means different things in different scopes, and the scope decides it
// without guessing. In session scope the scope already names the target, so a number
// can only be a profile selector. Outside session scope there is no current session,
// so a number is a session token: a provider session ID may itself be all digits, and
// treating it as a profile number would make those sessions unaddressable.
func interactiveModel(parent context.Context, api InteractiveAPI, state *interactiveState, rest string, lines <-chan lineReadResult, out, trustedOut, diagnostics io.Writer, options InteractiveOptions) error {
	if err := rejectInteractiveOption("model", rest); err != nil {
		return err
	}
	fields := strings.Fields(rest)
	if len(fields) > 2 {
		return fmt.Errorf("usage: model [session] [profile]")
	}
	if len(fields) == 2 {
		return interactiveModelSelect(parent, api, state, fields[0], fields[1], lines, out, trustedOut, options)
	}
	token := ""
	if len(fields) == 1 {
		token = fields[0]
	}
	if token != "" && state.Scope.Kind == ScopeSession && IsRowNumber(token) {
		return interactiveModelSelect(parent, api, state, "", token, lines, out, trustedOut, options)
	}
	return interactiveModelList(parent, api, state, token, trustedOut, diagnostics, options.Color)
}

// interactiveModelList renders the model profiles one session can select.
//
// Session scope already names its target, so a bare model lists the profiles of the
// selected session. Outside session scope the argument is required, because a catalog
// read is session-scoped and fanning out across sessions would multiply provider calls
// and mix profiles that belong to different runtimes.
func interactiveModelList(parent context.Context, api InteractiveAPI, state *interactiveState, token string, out, diagnostics io.Writer, color ColorPolicy) error {
	ctx, cancel := commandContext(parent)
	defer cancel()
	target, err := resolveSessionTarget(ctx, api, state, "model", token)
	if err != nil {
		return err
	}
	querier, ok := api.(ModelCatalogQuerier)
	if !ok {
		return fmt.Errorf("model profiles are unavailable: this client cannot query model profiles")
	}
	catalog, err := querier.GetModelCatalog(ctx, target.endpointID, target.sessionID, target.generation)
	if err != nil {
		return err
	}
	if catalog.ErrorCode != "" {
		return modelCatalogError(sessionIdentityLabel(target.displayName, target.providerSessionID, target.sessionID), catalog.ErrorCode)
	}
	view := NewModelCatalogView(target.endpointID, target.sessionID, catalog)
	// The live and history namespaces are dropped before the catalog is rendered, so
	// a number from a previous table can never be applied to a profile row.
	state.Rows = nil
	state.history = nil
	state.modelCatalog = nil
	if view.Truncated {
		if _, err := fmt.Fprintln(diagnostics, "model profiles are a bounded provider window; some profiles are not listed"); err != nil {
			return err
		}
	}
	if len(view.Rows) == 0 {
		// An empty catalog is a real answer, so it is stated plainly instead of
		// rendering an empty table that looks like a rendering fault.
		_, err := fmt.Fprintf(out, "session %s offers no selectable model profile\n", sessionIdentityLabel(target.displayName, target.providerSessionID, target.sessionID))
		return err
	}
	options := TableOptionsFor(out)
	options.Color = color
	options.HideSessionID = true
	if err := RenderModelCatalog(out, view, options); err != nil {
		return err
	}
	state.modelCatalog = &modelCatalogNamespace{
		EndpointID:          target.endpointID,
		ClusterSessionID:    target.sessionID,
		ProviderSessionID:   target.providerSessionID,
		ProviderDisplayName: target.displayName,
		ProviderGeneration:  target.generation,
		Rows:                make(map[int]ModelCatalogViewRow, len(view.Rows)),
	}
	for _, row := range view.Rows {
		state.modelCatalog.Rows[row.No] = row
	}
	return nil
}

// interactiveModelSelect applies one model profile to one session.
//
// The selector is resolved against the catalog the operator last saw, and only the
// resolved row's ModelProfileID travels on the wire. A number is never sent, because a
// number is a position in a table and the table is a client-side rendering: sending it
// would let a renumbered catalog change which profile a request addresses.
func interactiveModelSelect(parent context.Context, api InteractiveAPI, state *interactiveState, sessionToken, profileToken string, lines <-chan lineReadResult, out, trustedOut io.Writer, options InteractiveOptions) error {
	ctx, cancel := commandContext(parent)
	target, err := resolveSessionTarget(ctx, api, state, "model", sessionToken)
	cancel()
	if err != nil {
		return err
	}
	row, err := resolveModelProfileSelector(state.modelCatalog, target.sessionID, profileToken, sessionIdentityLabel(target.displayName, target.providerSessionID, target.sessionID))
	if err != nil {
		return err
	}
	if !row.Available {
		reason := row.UnavailableReason
		if reason == "" {
			reason = "unavailable"
		}
		return fmt.Errorf("model profile %q is unavailable (%s); run model to see the current catalog", modelProfileLabel(row), reason)
	}
	payload, err := json.Marshal(protocol.ModelSelectRequest{ModelProfileID: row.ModelProfileID})
	if err != nil {
		return err
	}
	label := "model select"
	postSubmit := func(_ context.Context, _ map[string]any) error {
		// The rendered catalog is stale after a successful change, so its numbers are
		// dropped: a number must never address a profile from a table that no longer
		// describes the session.
		state.modelCatalog = nil
		_, err := fmt.Fprintf(trustedOut, "model profile %q selected; run model to see the updated catalog\n", modelProfileLabel(row))
		return err
	}
	if state.Scope.Kind == ScopeSession {
		return interactiveConfirmedAction(parent, api, state, protocol.OperationAgentModelSelect, label, target.confirmationTarget(), target.generation, payload, lines, out, trustedOut, options, nil, postSubmit)
	}
	// Outside session scope the pinned selection is not the target, so the shared
	// confirmation path receives a detached copy that pins exactly this target.
	pinned := *state
	pinned.EndpointID = target.endpointID
	pinned.ClusterSessionID = target.sessionID
	pinned.ProviderGeneration = target.generation
	pinned.Invalidated = false
	pinned.InvalidReason = ""
	revalidate := func(revalidateCtx context.Context) error {
		_, err := validateSessionTarget(revalidateCtx, api, target.endpointID, target.sessionID, target.generation)
		return err
	}
	copyBack := func(postCtx context.Context, result map[string]any) error {
		// The shared confirmation path records the command ID on the detached copy,
		// so copy it back before the caller can query status on the real state.
		state.commandID = pinned.commandID
		return postSubmit(postCtx, result)
	}
	return interactiveConfirmedAction(parent, api, &pinned, protocol.OperationAgentModelSelect, label, target.confirmationTarget(), target.generation, payload, lines, out, trustedOut, options, revalidate, copyBack)
}

// resolveModelProfileSelector resolves one profile selector against the catalog the
// operator last saw.
//
// Every selector form resolves through that catalog, including an explicit identifier
// or display name, so the operator can only ever select a profile that was shown to
// them. A number that is not in the table is an error and is never retried as an
// identifier: falling through would silently apply a profile the operator never
// selected, which is the one outcome this command must not produce.
//
// requestedLabel is the canonical identity expression of the session being addressed,
// so a refusal names the session the same way every other message does. It is passed
// in rather than derived here, because the requested session and the rendered session
// are different targets and only the caller knows which one it asked for.
func resolveModelProfileSelector(namespace *modelCatalogNamespace, sessionID, token, requestedLabel string) (ModelCatalogViewRow, error) {
	if namespace == nil {
		return ModelCatalogViewRow{}, fmt.Errorf("no model catalog has been rendered for session %s; run model first", requestedLabel)
	}
	if namespace.ClusterSessionID != sessionID {
		renderedLabel := sessionIdentityLabel(namespace.ProviderDisplayName, namespace.ProviderSessionID, namespace.ClusterSessionID)
		return ModelCatalogViewRow{}, fmt.Errorf("the last rendered model catalog belongs to session %s, not %s; run model again", renderedLabel, requestedLabel)
	}
	if number, numeric := parseRowNumber(token); numeric {
		row, ok := namespace.Rows[number]
		if !ok {
			return ModelCatalogViewRow{}, fmt.Errorf("model profile %d is not in the last rendered catalog; run model again", number)
		}
		return row, nil
	}
	rows := sortedModelCatalogRows(namespace)
	if matches := modelCatalogMatches(rows, func(row ModelCatalogViewRow) bool { return row.ModelProfileID == token }); len(matches) == 1 {
		return matches[0], nil
	}
	matches := modelCatalogMatches(rows, func(row ModelCatalogViewRow) bool {
		return row.ProviderDisplayName != "" && row.ProviderDisplayName == token
	})
	switch len(matches) {
	case 1:
		return matches[0], nil
	case 0:
		return ModelCatalogViewRow{}, fmt.Errorf("model profile %q is not in the last rendered catalog; run model again", token)
	default:
		return ModelCatalogViewRow{}, fmt.Errorf("model profile %q is ambiguous: %d profiles share that display name; select it by row number or model_profile_id", token, len(matches))
	}
}

// sortedModelCatalogRows returns the rendered rows in row-number order, so a selector
// that matches several rows reports the same result on every run.
func sortedModelCatalogRows(namespace *modelCatalogNamespace) []ModelCatalogViewRow {
	numbers := make([]int, 0, len(namespace.Rows))
	for number := range namespace.Rows {
		numbers = append(numbers, number)
	}
	sort.Ints(numbers)
	rows := make([]ModelCatalogViewRow, 0, len(numbers))
	for _, number := range numbers {
		rows = append(rows, namespace.Rows[number])
	}
	return rows
}

// modelCatalogMatches returns every row the predicate accepts.
func modelCatalogMatches(rows []ModelCatalogViewRow, accept func(ModelCatalogViewRow) bool) []ModelCatalogViewRow {
	matches := make([]ModelCatalogViewRow, 0, 1)
	for _, row := range rows {
		if accept(row) {
			matches = append(matches, row)
		}
	}
	return matches
}

// modelProfileLabel names one profile in operator-facing text.
func modelProfileLabel(row ModelCatalogViewRow) string {
	if row.ProviderDisplayName == "" {
		return row.ModelProfileID
	}
	return fmt.Sprintf("%s (%s)", row.ProviderDisplayName, row.ModelProfileID)
}
