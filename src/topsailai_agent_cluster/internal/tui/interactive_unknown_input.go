package tui

import (
	"context"
	"fmt"
	"io"
	"strings"
)

// maxSendOfferPreview bounds the text echoed in the send offer question, so a
// long line cannot flood the terminal before the operator answers.
const maxSendOfferPreview = 512

// offerSendForUnknownInput handles a session-scope line whose first word is not a
// registered command. Typing a message without the command word is the common
// mistake in session scope, so the operator is offered the send action for the
// literal line instead of only a diagnostic.
//
// Every other scope keeps the plain unknown-command diagnostic, because send is
// unavailable there and an offer could never be honoured. A declined, empty or
// unreadable answer also keeps that diagnostic, so a typo is never swallowed and
// no mutating action is ever inferred from silence.
func offerSendForUnknownInput(parent context.Context, api InteractiveAPI, state *interactiveState, line, name string, lineSource <-chan lineReadResult, out, trustedOut io.Writer, options InteractiveOptions) error {
	unknownErr := fmt.Errorf("unknown command %q (try help)", name)
	if state.Scope.Kind != ScopeSession {
		return unknownErr
	}
	// The literal line is the message, not the words after the unrecognized word:
	// the operator typed one piece of text, and dropping its first word would
	// silently change what is sent.
	text := strings.TrimSpace(line)
	if text == "" {
		return unknownErr
	}
	// The offer must not promise a payload the send command itself rejects, so the
	// shared payload rule is applied before the question is asked.
	if err := rejectJSONFlagPayload(text, "send"); err != nil {
		return unknownErr
	}
	// The offer is a question, not a capability claim. The send flow performs the
	// authoritative capability preflight and reports an unsupported operation
	// precisely, so a typo never pays for an extra capability round trip and the
	// capability decision keeps exactly one implementation.
	preview := text
	if len(preview) > maxSendOfferPreview {
		preview = preview[:maxSendOfferPreview] + "..."
	}
	// Both interpolated values are operator-supplied, so they are sanitized before
	// they reach the trusted writer that carries the question styling.
	question := "unknown command " + sanitizeInlineText(name) + "; send " + sanitizeInlineText(preview) + " as a message? " + confirmationHint + " "
	if err := writeConfirmationQuestion(trustedOut, question, options.Color); err != nil {
		return err
	}
	markRecoverablePromptFailure(parent)
	confirmation, ok := nextPromptLine(parent, lineSource)
	if !ok {
		return unknownErr
	}
	if confirmation.err != nil && confirmation.err != io.EOF {
		return fmt.Errorf("confirmation failed: %w", confirmation.err)
	}
	// An incomplete or unreadable answer cannot authorize a mutating action, so the
	// typo diagnostic is reported instead of a send.
	if confirmation.err != nil || confirmation.overflow {
		return unknownErr
	}
	answer := strings.ToLower(strings.TrimSpace(confirmation.line))
	if answer != "y" && answer != "yes" {
		return unknownErr
	}
	// The accepted offer already named this exact text and action, so the send flow
	// runs with that confirmation instead of asking the same question twice.
	return sendSessionMessage(parent, api, state, text, out, options)
}
