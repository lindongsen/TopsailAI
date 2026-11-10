package tui

import (
	"context"
	"fmt"
	"io"
	"strings"
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
	EndpointID string
	SessionID  string
	Generation string
	Rows       map[int]ModelCatalogViewRow
}

// interactiveModel renders the model profiles one session can select.
//
// The grammar is "model [session]". Session scope already names its target, so a bare
// model lists the profiles of the selected session and an explicit argument is
// rejected as ambiguous. Outside session scope the argument is required, because a
// catalog read is session-scoped and fanning out across sessions would multiply
// provider calls and mix profiles that belong to different runtimes.
//
// A bare number is rejected here rather than resolved as a session row number. The
// number after this command selects a model profile, not a session, so accepting it
// as a session selector would give one token two meanings and would silently retarget
// the command once profile selection lands.
func interactiveModel(parent context.Context, api InteractiveAPI, state *interactiveState, rest string, out, diagnostics io.Writer, color ColorPolicy) error {
	if err := rejectInteractiveOption("model", rest); err != nil {
		return err
	}
	token := strings.TrimSpace(rest)
	if _, numeric := parseRowNumber(token); numeric {
		return fmt.Errorf("model %s is not a session selector: a number selects a model profile, so name the session first with model <session>", token)
	}
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
		return modelCatalogError(target.sessionID, catalog.ErrorCode)
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
		_, err := fmt.Fprintf(out, "session %q offers no selectable model profile\n", target.sessionID)
		return err
	}
	options := TableOptionsFor(out)
	options.Color = color
	options.HideSessionID = true
	if err := RenderModelCatalog(out, view, options); err != nil {
		return err
	}
	state.modelCatalog = &modelCatalogNamespace{
		EndpointID: target.endpointID,
		SessionID:  target.sessionID,
		Generation: target.generation,
		Rows:       make(map[int]ModelCatalogViewRow, len(view.Rows)),
	}
	for _, row := range view.Rows {
		state.modelCatalog.Rows[row.No] = row
	}
	return nil
}
