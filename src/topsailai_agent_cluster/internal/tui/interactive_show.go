package tui

import (
	"context"
	"fmt"
	"io"
	"strings"
)

// showGuidedPrompt is the question a bare "show" asks in workspace scope.
//
// The range is part of the question because the operator is choosing a position in
// the table that was just printed, so the accepted answers are visible instead of
// remembered.
const showGuidedPrompt = "select endpoint or session [1-%d] or press Enter to cancel: "

// showCancelled is the report of an empty guided answer.
//
// An empty answer is a decision, not a failure: the operator looked at the table and
// chose to show nothing. Reporting it as an error would make a deliberate cancel look
// like a defect in the command.
const showCancelled = "show cancelled"

// showNothingAvailable is the report of a guided "show" with no row to choose from.
//
// It names the remedy rather than only the condition, because the usual reason a
// workspace table is empty is that every endpoint is offline and the default list
// filter skips them. Without the remedy the operator would read an empty table as a
// broken inventory.
const showNothingAvailable = "nothing is available to show; run list --all to include endpoints that are not online"

// interactiveShowGuided renders the workspace table and asks which row to show.
//
// This exists because "show" in workspace scope used to refuse with a usage line and
// tell the operator to run a different command first. That costs two commands for one
// decision, and the second command is the one that can be typed wrong: the operator has
// to read a table, remember a number, and retype it. Rendering the table and asking is
// the same one round trip the explicit form already pays, and the answer can only name
// a row that was printed.
//
// The already-rendered table is reused when one exists, because the REPL renders the
// workspace inventory before the first prompt. Re-rendering would issue a second
// inventory read for a table the operator is already looking at, and it would clear the
// row namespaces of any other table rendered since.
//
// The question is written through trustedOut because it carries application styling,
// and the read uses parent rather than the command context so operator thinking time is
// never charged against the command deadline.
func interactiveShowGuided(parent context.Context, api InteractiveAPI, state *interactiveState, lines <-chan lineReadResult, out, trustedOut, diagnostics io.Writer, options InteractiveOptions) error {
	if len(state.Rows) == 0 {
		// No table is available, so one is rendered. This is the only read the guided
		// form performs, and it is the same read the explicit form's row number
		// resolves against.
		if err := interactiveList(parent, api, state, listArguments{}, trustedOut, diagnostics, options.Color); err != nil {
			return err
		}
	}
	if len(state.Rows) == 0 {
		_, err := fmt.Fprintln(out, showNothingAvailable)
		return err
	}
	question := fmt.Sprintf(showGuidedPrompt, len(state.Rows))
	if err := writeConfirmationQuestion(trustedOut, question, options.Color); err != nil {
		return err
	}
	echo := func(answer string) string {
		row, resolved, err := resolveReadSessionToken(state, answer)
		if err != nil || !resolved {
			return ""
		}
		return RenderAnswerEcho(showRowLabel(row), options.Color)
	}
	answer, ok := nextPromptLineWithEcho(parent, lines, trustedOut, echo)
	if !ok || answer.overflow || answer.err != nil {
		return fmt.Errorf("show selection requires a complete line")
	}
	choice := strings.TrimSpace(answer.line)
	if choice == "" {
		_, err := fmt.Fprintln(out, showCancelled)
		return err
	}
	// The answer is resolved through the same helper the explicit form uses, so the
	// guided question accepts exactly what "show <token>" accepts. A row number is a
	// position in the table that was just printed; anything else is a literal
	// identifier, which is what an operator who copied a provider session ID types.
	row, resolved, err := resolveReadSessionToken(state, choice)
	if err != nil {
		return err
	}
	if resolved {
		return showResolvedRow(parent, api, row, out)
	}
	return showIdentifier(parent, api, choice, out)
}

// showResolvedRow renders one already-resolved table row.
//
// A row with no session identity is an endpoint placeholder row, so the endpoint
// identifier is the only identity it carries. Falling back to it keeps the row
// readable instead of reporting that it identifies nothing, which is exactly what the
// explicit "show <endpoint-id>" form already does.
func showResolvedRow(parent context.Context, api InteractiveAPI, row SessionRow, out io.Writer) error {
	id := row.ClusterSessionID
	if id == "" {
		id = row.EndpointID
	}
	return showIdentifier(parent, api, id, out)
}

// showIdentifier renders one literal identifier.
//
// It is the single call both the explicit form and the guided answer make, so a
// provider session identifier pasted at the question behaves exactly as it does after
// the command word. The numeric hint is applied here too, because a numeric token that
// failed to resolve as a row may still be a provider session identifier, and the
// failure must name both remedies.
func showIdentifier(parent context.Context, api InteractiveAPI, id string, out io.Writer) error {
	ctx, cancel := commandContext(parent)
	defer cancel()
	if err := (CommandRunner{API: api, Policy: InteractivePolicy}).Show(ctx, out, id, false); err != nil {
		return numericTokenHint(id, err)
	}
	return nil
}

// showRowLabel names one table row in operator-facing text.
//
// The display name is preferred because it is what the table prints, and the identity
// follows so the operator can copy a value that "show" accepts. A row with no display
// name falls back to its identity alone rather than printing an empty pair of
// parentheses.
func showRowLabel(row SessionRow) string {
	identity := row.ClusterSessionID
	if identity == "" {
		identity = row.EndpointID
	}
	if row.ProviderDisplayName == "" {
		return identity
	}
	return fmt.Sprintf("%s (%s)", row.ProviderDisplayName, identity)
}
