package tui

import (
	"context"
	"fmt"
	"io"
	"strings"
)

// maxSendOfferPreview bounds the text echoed in the send offer, so a long line
// cannot flood the terminal before the operator answers.
const maxSendOfferPreview = 512

// sendOfferMarker prefixes the offer's question row. The row is the input row, so
// the marker separates the application's question from the message row above it
// without repeating the unknown-command diagnostic.
const sendOfferMarker = ">>> "

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
	// The stream fallback has no answer prompt and no terminal echo, so the
	// prompt row is still open here. It is closed before the message row, so the
	// message always starts on a row of its own. The terminal editor already
	// echoes the typed line and ends that row, so a second newline would leave a
	// blank row.
	streamFallback := promptReader(parent) == nil
	if streamFallback {
		if _, err := io.WriteString(trustedOut, "\n"); err != nil {
			return err
		}
	}
	// The message row comes first and carries its own colour, so the operator
	// reads exactly what would be sent before reading the question. The payload
	// is operator-supplied, so it is sanitized before it reaches the trusted
	// writer that carries the styling. The row is not indented, because the
	// question row below carries the ">>>" marker that separates the two.
	if err := writeStyled(trustedOut, ansiMagenta, sanitizeInlineText(preview), options.Color); err != nil {
		return err
	}
	// The message row ends here on the stream fallback, which has no editor to end
	// it. The terminal editor writes its own row break before the question row, so
	// writing one here as well would leave a blank row between the two.
	if streamFallback {
		if _, err := io.WriteString(trustedOut, "\n"); err != nil {
			return err
		}
	}
	// The question row is the input row: the terminal editor redraws it and leaves
	// the cursor after the answer hint, so no separate answer prompt is printed.
	// The stream fallback has no editor, so the question is written here and the
	// answer is read from the line source. Its leading newline is dropped there,
	// because the message row already ended.
	question := sendOfferMarker + "send the text above as a message? " + confirmationHint + " "
	prompt := RenderConfirmationPrompt(question, options.Color)
	if streamFallback {
		if _, err := io.WriteString(trustedOut, strings.TrimPrefix(prompt, "\n")); err != nil {
			return err
		}
		// The stream fallback has no editor that ends the question row, so the row
		// is closed here instead of sharing it with the receipt.
		if _, err := io.WriteString(trustedOut, "\n"); err != nil {
			return err
		}
	}
	markRecoverablePromptFailure(parent)
	confirmation, ok := nextPromptLine(parent, lineSource, prompt)
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
	return sendSessionMessage(parent, api, state, text, out, trustedOut, options)
}
