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
// The grammar is "model set [<row|model-profile-id>]". With no selector the command
// renders the registry and asks which row to declare, because the operator who wants
// to change the launch default is exactly the operator who needs to see what the
// machine offers first. Requiring them to run "model" and then retype a number costs
// two commands for one decision, and the second command is the one that can be typed
// wrong.
//
// The selector resolves against the registry the operator last saw, so a number can
// only ever address a row that was printed. The operation is Endpoint-scoped and
// target-less: it changes a machine-wide declaration, not a live process, so it
// carries no generation and no session.
//
// The endpoint is resolved through the same helper the registry read uses, so
// workspace scope asks which machine to change and endpoint scope changes the current
// one.
func interactiveModelSet(parent context.Context, api InteractiveAPI, state *interactiveState, rest string, lines <-chan lineReadResult, out, trustedOut, diagnostics io.Writer, options InteractiveOptions) error {
	if err := rejectInteractiveOption("model set", rest); err != nil {
		return err
	}
	token := strings.TrimSpace(rest)
	if token == "" {
		return interactiveModelSetGuided(parent, api, state, lines, out, trustedOut, diagnostics, options)
	}
	endpointID, row, err := resolveModelSetTarget(parent, api, state, token, lines, out, trustedOut, options.Color)
	if err != nil || row.ModelProfileID == "" {
		return err
	}
	return applyModelSetRow(parent, api, state, endpointID, row, lines, out, trustedOut, options)
}

// interactiveModelSetGuided renders the registry and asks which row to declare.
//
// Three answers are three different outcomes and are reported as three different
// messages, because collapsing them would hide what happened:
//
//	<number>  declare that row, through the same confirmation every mutating
//	          operation uses
//	<name>    declare the row that name identifies, resolved against the table that
//	          was just printed
//	<empty>   declare nothing; the operator looked and kept the current default
//
// The question is written through trustedOut because it carries application styling,
// and the read uses parent rather than the command context so operator thinking time
// is never charged against the command deadline. The echo resolves through the same
// row label the table printed, so the label beside the number is the model that will
// be declared; an empty or unusable answer echoes nothing, because no choice was made.
func interactiveModelSetGuided(parent context.Context, api InteractiveAPI, state *interactiveState, lines <-chan lineReadResult, out, trustedOut, diagnostics io.Writer, options InteractiveOptions) error {
	endpointID, view, rendered, err := renderModelRegistry(parent, api, state, "model set", lines, out, trustedOut, diagnostics, options)
	if err != nil || !rendered {
		return err
	}
	// A table where every row is unavailable offers nothing to declare, so the
	// refusal is stated now instead of asking a question whose every answer the
	// Endpoint would then reject.
	usable := 0
	for _, row := range view.Rows {
		if row.Available {
			usable++
		}
	}
	if usable == 0 {
		_, err := fmt.Fprintf(out, "endpoint %q offers no usable model: every listed model is unavailable, so no launch default can be declared\n", endpointID)
		return err
	}
	question := fmt.Sprintf("select model [1-%d] or press Enter to keep the current launch default: ", len(view.Rows))
	if err := writeConfirmationQuestion(trustedOut, question, options.Color); err != nil {
		return err
	}
	echo := func(answer string) string {
		row, err := resolveModelSetSelector(state.modelRegistry, answer)
		if err != nil || !row.Available {
			return ""
		}
		return RenderAnswerEcho(modelRegistryRowLabel(row), options.Color)
	}
	answer, ok := nextPromptLineWithEcho(parent, lines, trustedOut, echo)
	if !ok || answer.overflow || answer.err != nil {
		return fmt.Errorf("model selection requires a complete line")
	}
	choice := strings.TrimSpace(answer.line)
	if choice == "" {
		// An empty answer is a decision, not a failure: the operator saw the registry
		// and chose to keep the current launch default. The rendered namespace stays in
		// place, so "model set <number>" still works afterwards.
		_, err := fmt.Fprintln(out, "launch default unchanged")
		return err
	}
	row, err := resolveModelSetSelector(state.modelRegistry, choice)
	if err != nil {
		return err
	}
	return applyModelSetRow(parent, api, state, endpointID, row, lines, out, trustedOut, options)
}

// resolveModelSetSelector resolves one selector against the registry the operator last
// saw.
//
// A number is a position in that table, so a number that was not printed is refused
// and never retried as an identifier: falling through would declare a model the
// operator never selected. An identifier or display name is matched against the same
// rows, so the guided answer can name a model instead of counting rows.
func resolveModelSetSelector(namespace *modelRegistryNamespace, token string) (ModelRegistryViewRow, error) {
	if namespace == nil {
		return ModelRegistryViewRow{}, fmt.Errorf("no model registry has been rendered; run model first")
	}
	if number, numeric := parseRowNumber(token); numeric {
		row, ok := namespace.Rows[number]
		if !ok {
			return ModelRegistryViewRow{}, fmt.Errorf("model set %d: no such row in the rendered registry", number)
		}
		return row, nil
	}
	rows := sortedModelRegistryRows(namespace)
	matches := make([]ModelRegistryViewRow, 0, 1)
	for _, row := range rows {
		if row.ModelProfileID == token {
			matches = append(matches, row)
		}
	}
	if len(matches) == 1 {
		return matches[0], nil
	}
	// The current row is marked with a leading "* " in the rendered table, so an
	// operator copying a row from the screen types the marker too. Both spellings are
	// accepted, and the bare name is matched first, so a display name that genuinely
	// begins with "*" still resolves as itself instead of being read as a marker.
	matches = matches[:0]
	for _, row := range rows {
		if row.ProviderDisplayName == "" {
			continue
		}
		if row.ProviderDisplayName == token || modelCurrentMarker+row.ProviderDisplayName == token {
			matches = append(matches, row)
		}
	}
	switch len(matches) {
	case 1:
		return matches[0], nil
	case 0:
		return ModelRegistryViewRow{}, fmt.Errorf("model %q is not in the current registry of endpoint %q; run model to see the registry", token, namespace.EndpointID)
	default:
		// Several rows sharing a display name is a real possibility, because a display
		// name is chosen for a human. Selecting the first would declare a model the
		// operator did not choose, so the ambiguity is refused and the remedy names the
		// only unambiguous selector.
		ids := make([]string, 0, len(matches))
		for _, row := range matches {
			ids = append(ids, row.ModelProfileID)
		}
		sort.Strings(ids)
		return ModelRegistryViewRow{}, fmt.Errorf("model %q is ambiguous: %d entries share that display name (%s); select it by row number or model_profile_id", token, len(matches), strings.Join(ids, ", "))
	}
}

// sortedModelRegistryRows returns the rendered rows in row-number order, so a selector
// that matches several rows reports the same result on every run.
func sortedModelRegistryRows(namespace *modelRegistryNamespace) []ModelRegistryViewRow {
	numbers := make([]int, 0, len(namespace.Rows))
	for number := range namespace.Rows {
		numbers = append(numbers, number)
	}
	sort.Ints(numbers)
	rows := make([]ModelRegistryViewRow, 0, len(numbers))
	for _, number := range numbers {
		rows = append(rows, namespace.Rows[number])
	}
	return rows
}

// applyModelSetRow declares one resolved registry row as the launch default.
//
// It is the single submission path for the explicit form and the guided form, so the
// availability check, the payload and the pinned-scope handling cannot drift between
// the two surfaces.
func applyModelSetRow(parent context.Context, api InteractiveAPI, state *interactiveState, endpointID string, row ModelRegistryViewRow, lines <-chan lineReadResult, out, trustedOut io.Writer, options InteractiveOptions) error {
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

// resolveModelSetTarget resolves one explicit selector to the Endpoint and the
// registry row it names.
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
	namespace := &modelRegistryNamespace{
		EndpointID: endpointID,
		Rows:       make(map[int]ModelRegistryViewRow, len(view.Rows)),
	}
	for _, row := range view.Rows {
		namespace.Rows[row.No] = row
	}
	row, err := resolveModelSetSelector(namespace, token)
	if err != nil {
		return "", ModelRegistryViewRow{}, err
	}
	return endpointID, row, nil
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
