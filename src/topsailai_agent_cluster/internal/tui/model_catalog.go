package tui

import (
	"context"
	"fmt"
	"io"
	"strconv"

	"topsailai_agent_cluster/internal/protocol"
)

// ModelCatalogQuerier reads the model profiles one session can select.
//
// It is a separate optional interface rather than a CommandAPI method, for the same
// reason HistoryQuerier is one: a catalog read is a live provider query that only a
// client holding the model-catalog seam can serve, and adding it to CommandAPI would
// force every existing test double to implement a method it never calls. A client
// that cannot answer is reported explicitly instead of rendering an empty table,
// because an empty table would read as "this session offers no profile".
type ModelCatalogQuerier interface {
	GetModelCatalog(context.Context, string, string, string) (protocol.ModelCatalog, error)
}

// ModelCatalogViewRow is one rendered model profile row.
//
// No is the row number the operator types to select this profile. It is assigned at
// render time and never travels on the wire: the wire carries ModelProfileID, which
// is the only addressing key. The two are deliberately separate fields, so a
// renumbered table can never change which profile a request addresses.
type ModelCatalogViewRow struct {
	No                  int    `json:"no"`
	ModelProfileID      string `json:"model_profile_id"`
	ProviderDisplayName string `json:"provider_display_name,omitempty"`
	CurrentState        string `json:"current_state"`
	Available           bool   `json:"available"`
	UnavailableReason   string `json:"unavailable_reason,omitempty"`
}

// ModelCatalogView is one rendered model catalog for one session.
//
// Truncated reports that the provider returned its own capped window, so a bounded
// window is never presented as a complete catalog.
type ModelCatalogView struct {
	EndpointID       string                `json:"endpoint_id"`
	ClusterSessionID string                `json:"cluster_session_id"`
	Rows             []ModelCatalogViewRow `json:"rows"`
	CurrentProfileID string                `json:"current_profile_id,omitempty"`
	ObservedAtMS     int64                 `json:"observed_at_ms,omitempty"`
	Truncated        bool                  `json:"truncated,omitempty"`
}

// NewModelCatalogView binds one adapter answer to the session it was read for and
// assigns the row numbers the operator selects by.
//
// The view is a pure function of its inputs: it performs no provider call and no
// network call, so the same catalog always renders the same numbers.
func NewModelCatalogView(endpointID, sessionID string, catalog protocol.ModelCatalog) ModelCatalogView {
	view := ModelCatalogView{
		EndpointID:       endpointID,
		ClusterSessionID: sessionID,
		Rows:             make([]ModelCatalogViewRow, 0, len(catalog.Profiles)),
		CurrentProfileID: catalog.CurrentProfileID,
		ObservedAtMS:     catalog.ObservedAtMS,
		Truncated:        catalog.Truncated,
	}
	for _, profile := range catalog.Profiles {
		view.Rows = append(view.Rows, ModelCatalogViewRow{
			ModelProfileID:      profile.ModelProfileID,
			ProviderDisplayName: profile.ProviderDisplayName,
			CurrentState:        profile.CurrentState,
			Available:           profile.Available,
			UnavailableReason:   profile.UnavailableReason,
		})
	}
	assignModelCatalogRowNumbers(view.Rows)
	return view
}

// assignModelCatalogRowNumbers binds row numbers to one rendered catalog.
func assignModelCatalogRowNumbers(rows []ModelCatalogViewRow) {
	for index := range rows {
		rows[index].No = index + 1
	}
}

// modelCatalogColumns is the model catalog table layout.
//
// It is deliberately separate from the session and history layouts, because a model
// profile has no generation, no workspace and no data-status stamp, and reusing
// those columns would imply fields it does not have.
var modelCatalogColumns = []tableColumn{
	{key: columnNo, header: "NO", cap: 4},
	{key: columnName, header: "MODEL", cap: 48, wide: true},
	{key: "current", header: "CURRENT", cap: 8},
	{key: "available", header: "AVAILABLE", cap: 24, warn: true},
	{key: columnID, header: "MODEL_PROFILE_ID", cap: 36},
}

// modelCatalogCells renders one profile row into the keyed layout.
func modelCatalogCells(row ModelCatalogViewRow) map[string]string {
	return map[string]string{
		columnNo:    strconv.Itoa(row.No),
		columnName:  escapeCell(row.ProviderDisplayName),
		"current":   modelCurrentCell(row),
		"available": escapeCell(modelAvailableCell(row)),
		columnID:    escapeCell(row.ModelProfileID),
	}
}

// modelCurrentCell states whether the session uses this profile now.
//
// The three states are kept apart because only two of them are facts about the
// session. "unknown" means the Endpoint did not observe which profile is in use,
// so rendering it as "no" would state that the session is using nothing, which is
// a claim nobody made. Any value outside the vocabulary is treated the same way,
// so an unrecognized or empty state can never claim a definite negative.
func modelCurrentCell(row ModelCatalogViewRow) string {
	switch row.CurrentState {
	case protocol.ModelCurrentYes:
		return protocol.ModelCurrentYes
	case protocol.ModelCurrentNo:
		return protocol.ModelCurrentNo
	default:
		return protocol.ModelCurrentUnknown
	}
}

// modelAvailableCell states the adapter verdict and its standard reason.
//
// An unavailable profile stays in the table instead of being dropped, because the
// operator asked which profiles exist. Hiding it would make a configured profile
// look absent, and the reason is the only thing that explains why it cannot be
// selected.
func modelAvailableCell(row ModelCatalogViewRow) string {
	if row.Available {
		return "yes"
	}
	if row.UnavailableReason == "" {
		return "no"
	}
	return "no (" + row.UnavailableReason + ")"
}

// layoutModelCatalogColumns returns the columns one render actually prints.
//
// The opaque profile identifier is dropped on the interactive surface for the same
// reason the session identifier is: the operator selects a row by number, and the
// identifier is a long opaque value that only widens the table. It stays on the row,
// so it is still accepted as a selector and still named in diagnostics.
func layoutModelCatalogColumns(options TableOptions) []tableColumn {
	if !options.HideSessionID {
		return modelCatalogColumns
	}
	kept := make([]tableColumn, 0, len(modelCatalogColumns)-1)
	for _, column := range modelCatalogColumns {
		if column.key == columnID {
			continue
		}
		kept = append(kept, column)
	}
	return kept
}

// RenderModelCatalog writes one model catalog table.
func RenderModelCatalog(out io.Writer, view ModelCatalogView, options TableOptions) error {
	columns := layoutModelCatalogColumns(options)
	headers := columnHeaders(columns)
	cells := make([][]string, len(view.Rows))
	states := make([][]string, len(view.Rows))
	rowStyles := make([]string, len(view.Rows))
	for i, row := range view.Rows {
		values := modelCatalogCells(row)
		cells[i] = projectCells(values, columns)
		states[i] = make([]string, len(columns))
		for j, column := range columns {
			if column.key == "available" {
				states[i][j] = modelAvailableState(row)
				continue
			}
			states[i][j] = "ok"
		}
		rowStyles[i] = stateStyle(modelAvailableState(row))
	}
	widths := measureColumns(cells, columns, options.Full)
	return writeTable(out, headers, cells, states, rowStyles, widths, columns, options)
}

// modelAvailableState maps the adapter verdict to a colour state.
//
// An unavailable profile is a definite negative rather than an uncertain middle, so
// it is coloured like a failure. The reason column carries the detail.
func modelAvailableState(row ModelCatalogViewRow) string {
	if row.Available {
		return "ok"
	}
	return "failed"
}

// ModelCatalog renders the model profiles one session can select.
//
// The endpoint argument is resolved like history and messages, so an ID and a
// unique hostname are both accepted and an ambiguous hostname is rejected with the
// candidate list. The read is a live provider query, so it never returns a cached
// projection.
//
// Three outcomes are kept apart, because collapsing any two of them would mislead
// the operator:
//
//   - the client cannot query model profiles at all, which is reported as an
//     explicit error rather than an empty table;
//   - the endpoint has no catalog-capable adapter, which is reported with the
//     adapter's own unsupported code rather than as an empty catalog;
//   - the session genuinely offers no selectable profile, which is a real answer and
//     is stated as such.
func (r CommandRunner) ModelCatalog(ctx context.Context, out, errors io.Writer, target, resourceID, generation string, jsonMode bool, options TableOptions) error {
	querier, ok := r.API.(ModelCatalogQuerier)
	if !ok {
		return fmt.Errorf("model profiles are unavailable: this client cannot query model profiles")
	}
	endpoint, err := resolveHistoryEndpoint(ctx, r.API, target)
	if err != nil {
		return err
	}
	catalog, err := querier.GetModelCatalog(ctx, endpoint.EndpointID, resourceID, generation)
	if err != nil {
		return err
	}
	if catalog.ErrorCode != "" {
		return modelCatalogError(SessionIdentityLabelFromInventory(ctx, r.API, endpoint.EndpointID, resourceID), catalog.ErrorCode)
	}
	view := NewModelCatalogView(endpoint.EndpointID, resourceID, catalog)
	if jsonMode {
		return RenderJSON(out, view)
	}
	if view.Truncated {
		if _, err := fmt.Fprintln(errors, "model profiles are a bounded provider window; some profiles are not listed"); err != nil {
			return err
		}
	}
	if len(view.Rows) == 0 {
		// An empty catalog is a real answer, not a failure and not an unsupported
		// adapter, so it is stated plainly instead of rendering an empty table that
		// looks like a rendering fault.
		_, err := fmt.Fprintf(out, "session %s offers no selectable model profile\n", SessionIdentityLabelFromInventory(ctx, r.API, endpoint.EndpointID, resourceID))
		return err
	}
	return RenderModelCatalog(out, view, options)
}

// modelCatalogError maps a standard catalog error code to an operator message.
//
// The unsupported code is named explicitly, because "this endpoint cannot answer"
// and "this session has no profiles" need different remedies: the first is an
// integration gap, the second is a configuration choice.
func modelCatalogError(label, code string) error {
	if code == "" {
		return nil
	}
	if code == protocol.ModelCatalogUnsupported {
		return fmt.Errorf("model profiles are unavailable for session %s: the endpoint has no model-catalog-capable adapter", label)
	}
	return fmt.Errorf("model profiles for session %s failed: %s", label, code)
}

// ResolveEndpointTarget resolves one endpoint ID or unique hostname.
//
// It is exported so the standalone surface resolves an endpoint exactly like the
// interactive surface does, including the ambiguous-hostname rejection. A second
// implementation would drift, and the two surfaces would disagree about which
// endpoints a name addresses.
func ResolveEndpointTarget(ctx context.Context, api CommandAPI, target string) (protocol.Endpoint, error) {
	return resolveHistoryEndpoint(ctx, api, target)
}

// ModelCatalogError maps a standard catalog error code to an operator message.
//
// It is exported for the same reason: the standalone surface must report an
// unsupported adapter and an empty catalog as two different outcomes, and a second
// mapping would let the two surfaces disagree about which one the operator sees.
func ModelCatalogError(label, code string) error {
	return modelCatalogError(label, code)
}

// ResolveModelProfileSelector resolves one profile selector against a rendered view.
//
// The standalone surface has no rendered table, so it passes the view it just built
// from a live read. That keeps one resolution rule for both surfaces: a selector only
// ever resolves against a catalog that was actually read, never against a guess.
//
// label is the canonical identity expression of the session being addressed. The view
// carries only the opaque resource ID, so the caller supplies the label it resolved
// from the committed inventory; a refusal then names the session the same way every
// other message does.
func ResolveModelProfileSelector(view ModelCatalogView, token, label string) (ModelCatalogViewRow, error) {
	namespace := &modelCatalogNamespace{
		EndpointID:       view.EndpointID,
		ClusterSessionID: view.ClusterSessionID,
		Rows:             make(map[int]ModelCatalogViewRow, len(view.Rows)),
	}
	for _, row := range view.Rows {
		namespace.Rows[row.No] = row
	}
	return resolveModelProfileSelector(namespace, view.ClusterSessionID, token, label)
}

// ModelProfileLabel names one profile in operator-facing text.
func ModelProfileLabel(row ModelCatalogViewRow) string {
	return modelProfileLabel(row)
}
