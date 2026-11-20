package tui

import (
	"context"
	"encoding/json"
	"fmt"
	"io"
	"strings"

	"topsailai_agent_cluster/internal/protocol"
)

// ModelRegistryQuerier reads the models one Endpoint offers to launches.
//
// It is a separate optional interface rather than a CommandAPI method, for the same
// reason ModelCatalogQuerier is one: a registry read is a live provider query that
// only a client holding the registry seam can serve, and adding it to CommandAPI
// would force every existing test double to implement a method it never calls.
//
// It is deliberately not folded into ModelCatalogQuerier. The two answer different
// questions about different subjects, and a client that can answer one and not the
// other is a real configuration. A single interface would make that client either
// claim a capability it lacks or lose the one it has.
type ModelRegistryQuerier interface {
	GetModelRegistry(context.Context, string) (protocol.ModelRegistry, error)
}

// ModelRegistryViewRow is one rendered environment model row.
//
// No is the row number the operator types to select this model. It is assigned at
// render time and never travels on the wire: the wire carries ModelProfileID, which
// is the only addressing key. The two are deliberately separate fields, so a
// renumbered table can never change which model a request addresses.
type ModelRegistryViewRow struct {
	No                  int    `json:"no"`
	ModelProfileID      string `json:"model_profile_id"`
	ProviderDisplayName string `json:"provider_display_name,omitempty"`
	Available           bool   `json:"available"`
	UnavailableReason   string `json:"unavailable_reason,omitempty"`
	// Current marks the row a launch from this machine would use now. It is a
	// rendering flag derived from CurrentProfileID, never a separate fact, so the
	// marker and the stated selection cannot disagree.
	Current bool `json:"current,omitempty"`
}

// ModelRegistryView is one rendered environment model registry for one Endpoint.
//
// CurrentSource is carried because "this machine uses X" is ambiguous on a machine
// that resolves a model per project folder: the same machine can use different models
// in different folders. Reporting the source lets an operator tell a machine-wide
// default from a folder-specific override instead of reading one value as the whole
// truth.
type ModelRegistryView struct {
	EndpointID       string                          `json:"endpoint_id"`
	Rows             []ModelRegistryViewRow          `json:"rows"`
	CurrentProfileID string                          `json:"current_profile_id,omitempty"`
	CurrentSource    string                          `json:"current_source"`
	ProjectOverrides []protocol.ModelProjectOverride `json:"project_overrides,omitempty"`
	ObservedAtMS     int64                           `json:"observed_at_ms,omitempty"`
	Truncated        bool                            `json:"truncated,omitempty"`
}

// NewModelRegistryView binds one adapter answer to the Endpoint it was read for and
// assigns the row numbers the operator selects by.
//
// The view is a pure function of its inputs: it performs no provider call and no
// mapping, so a rendering defect cannot be mistaken for a provider defect.
func NewModelRegistryView(endpointID string, registry protocol.ModelRegistry) ModelRegistryView {
	view := ModelRegistryView{
		EndpointID:       endpointID,
		Rows:             make([]ModelRegistryViewRow, 0, len(registry.Entries)),
		CurrentProfileID: registry.CurrentProfileID,
		CurrentSource:    registry.CurrentSource,
		ProjectOverrides: registry.ProjectOverrides,
		ObservedAtMS:     registry.ObservedAtMS,
		Truncated:        registry.Truncated,
	}
	for index, entry := range registry.Entries {
		view.Rows = append(view.Rows, ModelRegistryViewRow{
			No:                  index + 1,
			ModelProfileID:      entry.ModelProfileID,
			ProviderDisplayName: entry.ProviderDisplayName,
			Available:           entry.Available,
			UnavailableReason:   entry.UnavailableReason,
			Current:             entry.ModelProfileID != "" && entry.ModelProfileID == registry.CurrentProfileID,
		})
	}
	return view
}

// modelRegistryColumns is the column layout of one environment registry render.
//
// It reuses the session catalog's column keys and caps, so the two tables line up
// and an operator who has read one already knows the other. The identifier column is
// dropped on the interactive surface for the same reason it is dropped there: the
// operator selects a row by number, and the identifier is a long opaque value that
// only widens the table.
var modelRegistryColumns = []tableColumn{
	{key: columnNo, header: "NO", cap: 4},
	{key: columnName, header: "MODEL", cap: 48, wide: true},
	{key: "available", header: "AVAILABLE", cap: 24, warn: true},
	{key: columnID, header: "MODEL_PROFILE_ID", cap: 36},
}

// layoutModelRegistryColumns returns the columns one render actually prints.
func layoutModelRegistryColumns(options TableOptions) []tableColumn {
	if !options.HideSessionID {
		return modelRegistryColumns
	}
	kept := make([]tableColumn, 0, len(modelRegistryColumns)-1)
	for _, column := range modelRegistryColumns {
		if column.key == columnID {
			continue
		}
		kept = append(kept, column)
	}
	return kept
}

// modelRegistryCells builds the value of every column for one row.
func modelRegistryCells(row ModelRegistryViewRow) map[string]string {
	name := row.ProviderDisplayName
	if name == "" {
		name = row.ModelProfileID
	}
	if row.Current {
		name = modelCurrentMarker + name
	}
	available := "yes"
	if !row.Available {
		available = "no"
		if row.UnavailableReason != "" {
			available = "no (" + row.UnavailableReason + ")"
		}
	}
	return map[string]string{
		columnNo:    fmt.Sprintf("%d", row.No),
		columnName:  name,
		"available": available,
		columnID:    row.ModelProfileID,
	}
}

// modelRegistryAvailableState maps availability onto the shared state vocabulary, so
// an unavailable model is coloured like every other definite negative.
func modelRegistryAvailableState(row ModelRegistryViewRow) string {
	if row.Available {
		return "ok"
	}
	return "failed"
}

// modelRegistryNameState emphasises the MODEL cell of the model in use, so the marker
// can be emphasised without recolouring the name printed beside it.
func modelRegistryNameState(row ModelRegistryViewRow) string {
	if row.Current {
		return stateModelCurrent
	}
	return "ok"
}

// RenderModelRegistry writes the environment model table.
//
// The table is rendered with the same column machinery the session catalog uses, so
// the two surfaces cannot drift in width, colour or alignment. The current row is
// marked in the name cell rather than in a separate column, because a marker beside
// the name is read together with the name while a separate column has to be looked up.
func RenderModelRegistry(out io.Writer, view ModelRegistryView, options TableOptions) error {
	columns := layoutModelRegistryColumns(options)
	headers := columnHeaders(columns)
	cells := make([][]string, len(view.Rows))
	states := make([][]string, len(view.Rows))
	rowStyles := make([]string, len(view.Rows))
	for i, row := range view.Rows {
		cells[i] = projectCells(modelRegistryCells(row), columns)
		states[i] = make([]string, len(columns))
		for j, column := range columns {
			switch column.key {
			case "available":
				states[i][j] = modelRegistryAvailableState(row)
			case columnName:
				states[i][j] = modelRegistryNameState(row)
			default:
				states[i][j] = "ok"
			}
		}
		rowStyles[i] = stateStyle(modelRegistryAvailableState(row))
	}
	widths := measureColumns(cells, columns, options.Full)
	if err := writeTable(out, headers, cells, states, rowStyles, widths, columns, options); err != nil {
		return err
	}
	return writeModelRegistryNotices(out, view)
}

// writeModelRegistryNotices states the caveats one rendered registry carries.
//
// Both notices are part of the answer rather than diagnostics, so they are written
// beside the table: they explain what the operator is reading. A registry that marks
// a current row and is complete needs neither, because the table already answers both
// questions.
func writeModelRegistryNotices(out io.Writer, view ModelRegistryView) error {
	if view.Truncated {
		if _, err := fmt.Fprintln(out, "models are a bounded provider window; some models are not listed"); err != nil {
			return err
		}
	}
	if view.CurrentProfileID == "" {
		// Every entry reporting selected:false means nothing is selected, so the model
		// in use is unknown. It is stated as unknown rather than as "no model is
		// configured", because the registry may well list usable models while none of
		// them is the declared default; calling that "not configured" would tell the
		// operator to add a model they already have.
		if _, err := fmt.Fprintln(out, "the model in use is unknown: no entry is marked selected, so a launch from this endpoint has no declared default"); err != nil {
			return err
		}
		return nil
	}
	if _, err := fmt.Fprintf(out, "launches from this endpoint use the model marked * from %s\n", modelRegistrySourceLabel(view.CurrentSource)); err != nil {
		return err
	}
	// Overrides are stated separately rather than folded into the marked row, because
	// folding would claim one model for a machine that resolves a model per folder.
	if len(view.ProjectOverrides) > 0 {
		if _, err := fmt.Fprintf(out, "%d project folder(s) override the machine default\n", len(view.ProjectOverrides)); err != nil {
			return err
		}
	}
	return nil
}

// modelRegistrySourceLabel describes where the current selection came from.
//
// An unknown source is stated as unknown rather than omitted, because an omitted
// source reads as "there is no selection" while an unknown source reads as "the
// provider did not say", which is the honest answer.
func modelRegistrySourceLabel(source string) string {
	switch source {
	case protocol.ModelSourceWorkspace:
		return "the machine default"
	case protocol.ModelSourceProject:
		return "a project override"
	case protocol.ModelSourceInherited:
		return "the provider's inherited default"
	default:
		return "an unknown source"
	}
}

// ModelSetPayload builds the standard payload for one environment model change.
//
// It carries only the opaque Cluster profile identifier, so the caller never needs
// to know how the provider stores a model. Validation happens here as well as at
// the Endpoint, because a caller that submits a malformed identifier would
// otherwise learn about it only after a round trip, and the Endpoint would have to
// report a caller defect as a provider-facing rejection.
func ModelSetPayload(modelProfileID string) (json.RawMessage, error) {
	payload := protocol.ModelSetPayload{ModelProfileID: strings.TrimSpace(modelProfileID)}
	encoded, err := json.Marshal(payload)
	if err != nil {
		return nil, fmt.Errorf("encode model set payload: %w", err)
	}
	if _, err := protocol.ValidateModelSetPayload(encoded); err != nil {
		return nil, err
	}
	return encoded, nil
}
