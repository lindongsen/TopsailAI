package tui

import (
	"context"
	"encoding/json"
	"fmt"
	"io"
	"strconv"
	"strings"
	"time"
	"unicode/utf8"

	"topsailai_agent_cluster/internal/protocol"
)

// interactiveLogs resolves the session inside the current endpoint scope.
// A bare ASCII row number selects the session from the most recently rendered
// list, so the operator never has to type a provider session identifier.
func interactiveLogs(parent context.Context, api InteractiveAPI, state *interactiveState, rest string, maxBytes, maxLines int, out io.Writer) error {
	if state.Invalidated {
		return state.requireUsable()
	}
	endpointID := state.Scope.EndpointID
	if endpointID == "" {
		return fmt.Errorf("no endpoint selected; use cd <number> to enter an endpoint row, or cd <hostname>/<endpoint-id>")
	}
	resourceID := state.Scope.SessionID
	target, maxLines, err := parseLogsArgs(rest, maxLines)
	if err != nil {
		return err
	}
	if target != "" {
		resourceID = target
		row, resolved, err := resolveSessionTokenInEndpoint(state, target, endpointID)
		if err != nil {
			return err
		}
		if resolved {
			resourceID = row.SessionID
		}
	}
	if resourceID == "" {
		return fmt.Errorf("no session selected; use cd <number> to select a session row, or cd <hostname>/<endpoint-id>/<session>")
	}
	ctx, cancel := commandContext(parent)
	defer cancel()
	loaded, err := loadReports(ctx, api, endpointID)
	if err != nil {
		return err
	}
	_, _, session, err := findSessionInEndpoint(loaded, endpointID, resourceID)
	if err != nil {
		return numericTokenHint(strings.TrimSpace(rest), err)
	}
	return (CommandRunner{API: api, Policy: InteractivePolicy}).Logs(ctx, out, endpointID, session.SessionID, maxBytes, maxLines, false)
}

// parseLogsArgs splits an optional session token from an optional line limit.
// Accepted forms are -n <lines>, --lines <lines>, and --lines=<lines>.
func parseLogsArgs(rest string, fallback int) (string, int, error) {
	maxLines := fallback
	target := ""
	tokens := strings.Fields(rest)
	for i := 0; i < len(tokens); i++ {
		token := tokens[i]
		switch {
		case token == "-n" || token == "--lines":
			if i+1 >= len(tokens) {
				return "", 0, fmt.Errorf("usage: logs [-n <lines>] [session]")
			}
			i++
			parsed, err := parseLineCount(tokens[i])
			if err != nil {
				return "", 0, err
			}
			maxLines = parsed
		case strings.HasPrefix(token, "--lines="):
			parsed, err := parseLineCount(strings.TrimPrefix(token, "--lines="))
			if err != nil {
				return "", 0, err
			}
			maxLines = parsed
		case strings.HasPrefix(token, "-"):
			return "", 0, fmt.Errorf("usage: logs [-n <lines>] [session]")
		default:
			if target != "" {
				return "", 0, fmt.Errorf("usage: logs [-n <lines>] [session]")
			}
			target = token
		}
	}
	return target, maxLines, nil
}

// parseLineCount validates a positive line limit.
func parseLineCount(raw string) (int, error) {
	count, err := strconv.Atoi(raw)
	if err != nil || count <= 0 {
		return 0, fmt.Errorf("line count must be a positive integer")
	}
	return count, nil
}

func interactiveValue(values map[string]any, key string) string {
	value, _ := values[key].(string)
	return value
}

// interactiveStatus answers an explicit command ID in any scope.
// Without an argument it reports the last command submitted in this CLI, so the
// operator never has to retype an opaque command identifier.
func interactiveStatus(parent context.Context, api InteractiveAPI, state *interactiveState, rest string, out io.Writer) error {
	if err := rejectInteractiveOption("status", rest); err != nil {
		return err
	}
	commandID := strings.TrimSpace(rest)
	if commandID == "" {
		commandID = state.commandID
	}
	ctx, cancel := commandContext(parent)
	defer cancel()
	if commandID != "" {
		return (CommandRunner{API: api, Policy: InteractivePolicy}).Status(ctx, out, commandID, false)
	}
	if state.Scope.Kind != ScopeSession {
		return fmt.Errorf("no command has been submitted in this CLI yet; run an action such as start, then run status without an argument")
	}
	if state.Invalidated {
		return fmt.Errorf("selected session invalidated; use the session again")
	}
	_, _, session, err := findSelected(ctx, api, state)
	if err != nil {
		return err
	}
	_, err = fmt.Fprintln(out, session.State)
	return err
}

// MessagePayload converts operator message text into the standard message payload.
// A JSON object is forwarded unchanged so advanced callers keep full control; any
// other input becomes literal text, so no JSON has to be written by hand.
func MessagePayload(text string) (json.RawMessage, error) {
	if strings.HasPrefix(text, "{") {
		var payload map[string]any
		if err := json.Unmarshal([]byte(text), &payload); err != nil || payload == nil {
			return nil, fmt.Errorf("payload must be a JSON object or plain text")
		}
		return json.RawMessage(text), nil
	}
	wrapped, err := json.Marshal(map[string]string{"text": text})
	if err != nil {
		return nil, fmt.Errorf("encode payload: %w", err)
	}
	return json.RawMessage(wrapped), nil
}

// interruptActions maps every accepted plain spelling to the standard action name.
var interruptActions = map[string]string{
	"soft":           "soft_interrupt",
	"soft_interrupt": "soft_interrupt",
	"s":              "soft_interrupt",
	"hard":           "hard_interrupt",
	"hard_interrupt": "hard_interrupt",
	"h":              "hard_interrupt",
}

// InterruptPayload converts the plain interrupt grammar into the standard payload.
// Accepted forms are "soft [message]" and "hard"; a JSON object is forwarded
// unchanged as the advanced form.
func InterruptPayload(name, text string) (json.RawMessage, error) {
	text = strings.TrimSpace(text)
	if strings.HasPrefix(text, "{") {
		var payload map[string]any
		if err := json.Unmarshal([]byte(text), &payload); err != nil || payload == nil {
			return nil, fmt.Errorf("usage: %s [soft|hard] [message]", name)
		}
		return json.RawMessage(text), nil
	}
	args, err := splitInteractiveArguments(text)
	if err != nil {
		return nil, err
	}
	if len(args) == 0 {
		return nil, fmt.Errorf("usage: %s [soft|hard] [message]", name)
	}
	action, known := interruptActions[strings.ToLower(args[0])]
	if !known {
		return nil, fmt.Errorf("usage: %s [soft|hard] [message]", name)
	}
	message := strings.Join(args[1:], " ")
	if action == "hard_interrupt" {
		if message != "" {
			return nil, fmt.Errorf("%s hard does not accept a message", name)
		}
		return json.RawMessage(`{"action":"hard_interrupt"}`), nil
	}
	if message == "" {
		return json.RawMessage(`{"action":"soft_interrupt"}`), nil
	}
	encoded, err := json.Marshal(map[string]string{"action": "soft_interrupt", "message": message})
	if err != nil {
		return nil, fmt.Errorf("encode payload: %w", err)
	}
	return json.RawMessage(encoded), nil
}

// TaskPayload validates one literal initial task and encodes the standard start payload.
// The same bounds are enforced again by the adapter before any provider invocation.
func TaskPayload(task string) (json.RawMessage, error) {
	if !utf8.ValidString(task) || strings.ContainsRune(task, 0) || strings.TrimSpace(task) == "" || len(task) > protocol.MaxInitialTaskBytes {
		return nil, fmt.Errorf("task must be nonblank UTF-8 without NUL and at most %d bytes", protocol.MaxInitialTaskBytes)
	}
	encoded, err := json.Marshal(map[string]string{"task": task})
	if err != nil {
		return nil, fmt.Errorf("encode payload: %w", err)
	}
	return json.RawMessage(encoded), nil
}

func interactiveSend(parent context.Context, api InteractiveAPI, state *interactiveState, rest string, lineSource <-chan lineReadResult, out, trustedOut io.Writer, options InteractiveOptions) error {
	if err := state.requireUsable(); err != nil {
		return err
	}
	payloadText := strings.TrimSpace(rest)
	if !json.Valid([]byte(payloadText)) && strings.Contains(payloadText, "--json") {
		return fmt.Errorf("interactive send does not support --json")
	}
	if payloadText == "" {
		return fmt.Errorf("payload must not be empty")
	}
	if len(payloadText) > options.LineLimit {
		return fmt.Errorf("payload exceeds the maximum length")
	}
	sendPayload, err := MessagePayload(payloadText)
	if err != nil {
		return err
	}
	preflightCtx, cancelPreflight := commandContext(parent)
	beforeCapability, err := PreflightCapability(preflightCtx, api, state.EndpointID, protocol.OperationMessageSend)
	cancelPreflight()
	if err != nil {
		return err
	}
	preview := payloadText
	if len(preview) > 512 {
		preview = preview[:512] + "..."
	}
	// The preview is operator-supplied text, so it must be sanitized before it
	// reaches the trusted writer that carries the question styling.
	question := "send " + sanitizeInlineText(preview) + "? Confirm send? " + confirmationHint + " "
	if err := writeConfirmationQuestion(trustedOut, question, options.Color); err != nil {
		return err
	}
	markRecoverablePromptFailure(parent)
	confirmation, ok := nextPromptLine(parent, lineSource)
	if !ok {
		return fmt.Errorf("confirmation requires a complete line")
	}
	answer, overflow, err := confirmation.line, confirmation.overflow, confirmation.err
	if err == io.EOF {
		return fmt.Errorf("confirmation requires a complete line")
	}
	if err != nil {
		return fmt.Errorf("confirmation failed: %w", err)
	}
	if overflow {
		return fmt.Errorf("confirmation requires a complete line")
	}
	answer = strings.ToLower(strings.TrimSpace(answer))
	if answer != "y" && answer != "yes" {
		_, writeErr := fmt.Fprintln(out, "send cancelled")
		return writeErr
	}
	ctx, cancel := commandContext(parent)
	defer cancel()
	_, _, session, err := findSelected(ctx, api, state)
	if err != nil {
		return err
	}
	afterCapability, err := PreflightCapability(ctx, api, state.EndpointID, protocol.OperationMessageSend)
	if err != nil {
		return err
	}
	if afterCapability.Revision != beforeCapability.Revision {
		return fmt.Errorf("capability changed after confirmation; send cancelled")
	}
	runner := CommandRunner{API: api, Policy: InteractivePolicy, NewID: func() string { return fmt.Sprintf("cli-%d", time.Now().UnixNano()) }}
	intent, err := runner.PrepareAction(ctx, ActionRequest{Operation: protocol.OperationMessageSend, EndpointID: state.EndpointID, ResourceID: state.SessionID, Generation: session.Generation, Payload: sendPayload, Confirmed: true, WaitTimeoutMS: options.WaitTimeoutMS})
	if err != nil {
		return err
	}
	actionResult, err := runner.SubmitAction(ctx, intent)
	if err != nil {
		state.commandID = intent.CommandID
		return fmt.Errorf("command %s result unknown; use status %s to query; %w", intent.CommandID, intent.CommandID, err)
	}
	state.commandID = actionResult.CommandID
	if _, err = fmt.Fprintln(out, "command submitted:", state.commandID); err != nil {
		return err
	}
	actionResultData, err := runner.WaitAction(ctx, actionResult, intent.Budget)
	if err != nil {
		return err
	}
	return runner.RenderAction(out, actionResultData)
}

func nextLine(source <-chan lineReadResult) (lineReadResult, bool) {
	result, ok := <-source
	return result, ok
}

// interactiveStartRequest contains the parsed arguments for the interactive start command.
type interactiveStartRequest struct {
	EndpointID      string
	ResourceID      string
	Profile         string
	ProfileRevision string
	Folder          string
	Payload         json.RawMessage
}

// parseInteractiveStart parses the explicit interactive start grammar.
func parseInteractiveStart(rest string) (interactiveStartRequest, error) {
	args, err := splitInteractiveArguments(rest)
	if err != nil {
		return interactiveStartRequest{}, err
	}
	if len(args) < 2 {
		return interactiveStartRequest{}, fmt.Errorf("usage: start <endpoint> <resource> [--profile <id>] [--profile-revision <revision>] [--folder <path>]")
	}
	if args[0] == "" || args[1] == "" || strings.HasPrefix(args[0], "-") || strings.HasPrefix(args[1], "-") {
		return interactiveStartRequest{}, fmt.Errorf("start requires endpoint and resource")
	}
	request, missing, err := parseInteractiveStartTokens(args, false)
	if err != nil {
		return interactiveStartRequest{}, err
	}
	if missing != 0 {
		return interactiveStartRequest{}, fmt.Errorf("start requires --profile and --profile-revision")
	}
	return request, nil
}

// parseInteractiveStartTokens decodes shared start positions and options for strict and draft paths.
func parseInteractiveStartTokens(args []string, allowMissing bool) (interactiveStartRequest, uint8, error) {
	request := interactiveStartRequest{Payload: json.RawMessage(`{}`)}
	position := 0
	for position < len(args) && position < 2 && !strings.HasPrefix(args[position], "--") {
		if position == 0 {
			request.EndpointID = args[position]
		} else {
			request.ResourceID = args[position]
		}
		position++
	}
	if position < 2 && position < len(args) && !strings.HasPrefix(args[position], "--") {
		return interactiveStartRequest{}, 0, fmt.Errorf("start requires endpoint and resource")
	}
	var missing uint8
	for position < len(args) {
		name := args[position]
		switch name {
		case "--json":
			return interactiveStartRequest{}, 0, fmt.Errorf("interactive start does not support --json")
		case "--profile", "--profile-revision":
			bit := uint8(1 << 2)
			label := "--profile"
			if name == "--profile-revision" {
				bit = 1 << 3
				label = "--profile-revision"
			}
			if position+1 >= len(args) || strings.HasPrefix(args[position+1], "--") {
				if !allowMissing {
					return interactiveStartRequest{}, 0, fmt.Errorf("%s requires a value", label)
				}
				missing |= bit
				position++
				continue
			}
			position++
			if name == "--profile" {
				request.Profile = args[position]
			} else {
				request.ProfileRevision = args[position]
			}
			missing &^= bit
		case "--folder":
			if position+1 >= len(args) || (strings.HasPrefix(args[position+1], "--") && args[position+1] != "--") {
				return interactiveStartRequest{}, 0, fmt.Errorf("--folder requires a value")
			}
			position++
			request.Folder = args[position]
		case "--task":
			if position+1 >= len(args) || strings.HasPrefix(args[position+1], "--") {
				return interactiveStartRequest{}, 0, fmt.Errorf("--task requires a value")
			}
			position++
			payload, err := TaskPayload(args[position])
			if err != nil {
				return interactiveStartRequest{}, 0, err
			}
			request.Payload = payload
		case "--payload":
			return interactiveStartRequest{}, 0, fmt.Errorf("interactive start does not accept --payload; use --task <text>")
		default:
			return interactiveStartRequest{}, 0, fmt.Errorf("unknown start option %q", name)
		}
		position++
	}
	if request.EndpointID == "" {
		missing |= 1
	}
	if request.ResourceID == "" {
		missing |= 1 << 1
	}
	if request.Profile == "" {
		missing |= 1 << 2
	}
	if request.ProfileRevision == "" {
		missing |= 1 << 3
	}
	return request, missing, nil
}

// interactiveStart submits and renders an agent.start action using shared action logic.
func interactiveStart(parent context.Context, api InteractiveAPI, state *interactiveState, request interactiveStartRequest, out io.Writer, options InteractiveOptions) error {
	ctx, cancel := commandContext(parent)
	defer cancel()
	runner := CommandRunner{API: api, Policy: InteractivePolicy, NewID: func() string { return fmt.Sprintf("cli-%d", time.Now().UnixNano()) }}
	intent, err := runner.PrepareAction(ctx, ActionRequest{
		Operation:       protocol.OperationAgentStart,
		OperationLabel:  "start",
		EndpointID:      request.EndpointID,
		ResourceID:      request.ResourceID,
		Payload:         request.Payload,
		Confirmed:       true,
		Profile:         request.Profile,
		ProfileRevision: request.ProfileRevision,
		Folder:          request.Folder,
		WaitTimeoutMS:   options.WaitTimeoutMS,
	})
	if err != nil {
		return err
	}
	state.commandID = intent.CommandID
	action, err := runner.SubmitAction(ctx, intent)
	if err != nil {
		return fmt.Errorf("command %s result unknown; use status %s to query; %w", intent.CommandID, intent.CommandID, err)
	}
	state.commandID = action.CommandID
	if _, err := fmt.Fprintf(out, "command submitted: %s; use status %s to query\n", state.commandID, state.commandID); err != nil {
		return err
	}
	result, err := runner.WaitAction(ctx, action, intent.Budget)
	if err != nil {
		return fmt.Errorf("command %s status unavailable; use status %s to query; %w", state.commandID, state.commandID, err)
	}
	return renderInteractiveStartResult(out, action.CommandID, result)
}

// renderInteractiveStartResult writes the durable start result without JSON formatting.
// The provider's own return document is printed as a separate section so the
// operator sees both this service's receipt and the provider's raw answer.
func renderInteractiveStartResult(out io.Writer, commandID string, result map[string]any) error {
	if _, err := fmt.Fprintf(out, "CommandID: %s\nStatus: %s\nDeliveryBoundary: %s\nEffectCertainty: %s\nErrorCode: %s\n", commandID, valueString(result, "status", "Status"), valueString(result, "delivery_boundary", "DeliveryBoundary"), valueString(result, "effect_certainty", "EffectCertainty"), valueString(result, "error_code", "ErrorCode")); err != nil {
		return err
	}
	receipt := ReceiptForStatus(result)
	return renderProviderResponse(out, receipt.ProviderResponse, receipt.ProviderResponseTruncated)
}

// parseInteractivePayload rejects every argument for a lifecycle command that takes none.
// The interactive grammar never asks the operator to compose a JSON payload: the standard
// empty object is supplied here, so the provider contract is unchanged while the operator
// only ever types the command name.
func parseInteractivePayload(name, rest string) (json.RawMessage, error) {
	args, err := splitInteractiveArguments(rest)
	if err != nil {
		return nil, err
	}
	if len(args) == 0 {
		return json.RawMessage(`{}`), nil
	}
	if len(args) == 1 && args[0] == "--json" {
		return nil, fmt.Errorf("interactive %s does not support --json", name)
	}
	return nil, fmt.Errorf("usage: %s", name)
}

// interactiveSessionLifecycle executes resume or stop against the selected fresh session.
// Preflight authority checks run under the command deadline; the human confirmation is
// read afterwards with the cancel-only parent context.
func interactiveSessionLifecycle(parent context.Context, api InteractiveAPI, state *interactiveState, name, rest string, lines <-chan lineReadResult, out, trustedOut io.Writer, options InteractiveOptions) error {
	payload := json.RawMessage(`{}`)
	var err error
	if name == "resume" {
		payload, err = parseInteractivePayload(name, rest)
	} else {
		err = rejectInteractiveOption(name, rest)
		if err == nil && strings.TrimSpace(rest) != "" {
			err = fmt.Errorf("usage: stop")
		}
	}
	if err != nil {
		return err
	}
	ctx, cancel := commandContext(parent)
	if err := state.requireUsable(); err != nil {
		cancel()
		return err
	}
	if name == "resume" {
		if err := validateResumeSelectionAbsent(ctx, api, state); err != nil {
			cancel()
			return err
		}
		cancel()
		revalidate := func(revalidateCtx context.Context) error {
			return validateResumeSelectionAbsent(revalidateCtx, api, state)
		}
		return interactiveConfirmedAction(parent, api, state, protocol.OperationAgentResume, name, state.SessionID, state.Generation, payload, lines, out, trustedOut, options, revalidate, nil)
	}
	_, _, session, err := findSelected(ctx, api, state)
	cancel()
	if err != nil {
		return err
	}
	postSubmit := func(postCtx context.Context, result map[string]any) error {
		return reconcileStoppedSelection(postCtx, api, state, session.SessionID, out)
	}
	return interactiveConfirmedAction(parent, api, state, protocol.OperationAgentStop, name, session.SessionID, session.Generation, payload, lines, out, trustedOut, options, nil, postSubmit)
}

// reconcileStoppedSelection leaves the session scope once a fresh inventory proves the
// stopped session is no longer reported. The durable receipt stays the only authority for
// what happened; this reconciliation only decides where the operator continues working, so
// an inventory failure keeps the scope and never turns an acknowledged stop into an error.
func reconcileStoppedSelection(ctx context.Context, api InteractiveAPI, state *interactiveState, sessionID string, out io.Writer) error {
	if state.Scope.Kind != ScopeSession || state.SessionID != sessionID {
		return nil
	}
	loaded, err := loadReports(ctx, api, state.EndpointID)
	if err != nil {
		_, writeErr := fmt.Fprintf(out, "session %s scope unchanged: endpoint inventory unavailable; use cd .. to leave the session scope\n", sessionID)
		return writeErr
	}
	report, ok := loaded.reports[state.EndpointID]
	if !ok || !report.ReportComplete {
		_, writeErr := fmt.Fprintf(out, "session %s scope unchanged: endpoint inventory unavailable; use cd .. to leave the session scope\n", sessionID)
		return writeErr
	}
	for _, session := range report.Sessions {
		if session.SessionID == sessionID {
			return nil
		}
	}
	endpoint, found := endpointByID(loaded, state.EndpointID)
	if !found {
		endpoint = protocol.Endpoint{EndpointID: state.EndpointID, Hostname: state.Scope.Hostname}
	}
	state.enterEndpoint(endpoint)
	_, err = fmt.Fprintf(out, "session %s is no longer reported by endpoint %s; returned to endpoint scope\n", sessionID, endpoint.EndpointID)
	return err
}

// validateResumeSelectionAbsent proves from a complete fresh adapter inventory that the selected historical session has no live generation.
func validateResumeSelectionAbsent(ctx context.Context, api InteractiveAPI, state *interactiveState) error {
	if err := state.requireUsable(); err != nil {
		return err
	}
	loaded, err := loadReports(ctx, api, state.EndpointID)
	if err != nil {
		return err
	}
	report, ok := loaded.reports[state.EndpointID]
	if !ok || !report.ReportComplete || report.CollectionStatus != protocol.CollectionSucceeded {
		return fmt.Errorf("endpoint %q inventory cannot prove the selected session is stopped", state.EndpointID)
	}
	if state.Scope.AdapterID == "" {
		return fmt.Errorf("selected session adapter is unknown; use the session again")
	}
	if err := validateAdapterFreshness(report, state.Scope.AdapterID); err != nil {
		return err
	}
	for _, session := range report.Sessions {
		if session.SessionID != state.SessionID {
			continue
		}
		if session.Generation != state.Generation {
			state.invalidate("selected session generation changed")
			return fmt.Errorf("selected session generation changed; use the session again")
		}
		return fmt.Errorf("selected session %q is still live; stop it before resume", state.SessionID)
	}
	return nil
}

// interactiveSessionPayload executes context injection or interruption with confirmation.
// Selection authority is resolved under the command deadline; the confirmation itself is
// read with the cancel-only parent context. Context injection takes literal text, and a
// bare interrupt guides the operator through the action choice instead of demanding JSON.
func interactiveSessionPayload(parent context.Context, api InteractiveAPI, state *interactiveState, op, name, rest string, lines <-chan lineReadResult, out, trustedOut io.Writer, options InteractiveOptions) error {
	payloadText := strings.TrimSpace(rest)
	if !json.Valid([]byte(payloadText)) && strings.Contains(payloadText, "--json") {
		return fmt.Errorf("interactive %s does not support --json", name)
	}
	var payload json.RawMessage
	var err error
	if op == protocol.OperationContextInject {
		if payloadText == "" {
			return fmt.Errorf("usage: %s <text>", name)
		}
		payload, err = MessagePayload(payloadText)
	} else if payloadText == "" {
		payload, err = promptInterruptPayload(parent, name, lines, out, trustedOut, options)
	} else {
		payload, err = InterruptPayload(name, payloadText)
	}
	if err != nil {
		return err
	}
	ctx, cancel := commandContext(parent)
	if err := state.requireUsable(); err != nil {
		cancel()
		return err
	}
	_, _, session, err := findSelected(ctx, api, state)
	cancel()
	if err != nil {
		return err
	}
	return interactiveConfirmedAction(parent, api, state, op, name, session.SessionID, session.Generation, payload, lines, out, trustedOut, options, nil, nil)
}

// promptInterruptPayload guides a bare interrupt through the action choice and, for a soft
// interrupt, one optional message. Empty answers select the safe defaults, so the operator
// never has to compose a JSON object.
func promptInterruptPayload(parent context.Context, name string, lines <-chan lineReadResult, out, trustedOut io.Writer, options InteractiveOptions) (json.RawMessage, error) {
	question := name + " action? soft or hard, empty selects soft " + confirmationHint + " "
	if err := writeConfirmationQuestion(trustedOut, question, options.Color); err != nil {
		return nil, err
	}
	markRecoverablePromptFailure(parent)
	answer, err := readStartAnswer(parent, lines, name+".action> ")
	if err != nil {
		return nil, err
	}
	action := strings.ToLower(strings.TrimSpace(answer))
	if action == "" {
		action = "soft"
	}
	if _, known := interruptActions[action]; !known {
		return nil, fmt.Errorf("usage: %s [soft|hard] [message]", name)
	}
	if interruptActions[action] == "hard_interrupt" {
		return json.RawMessage(`{"action":"hard_interrupt"}`), nil
	}
	if _, err := fmt.Fprintln(out, "Optional message for the soft interrupt; empty sends none."); err != nil {
		return nil, err
	}
	markRecoverablePromptFailure(parent)
	message, err := readStartAnswer(parent, lines, name+".message> ")
	if err != nil {
		return nil, err
	}
	return InterruptPayload(name, "soft "+strings.TrimSpace(message))
}

// interactiveConfirmedAction keeps mutating confirmation and shared intent submission in one path.
// The human confirmation is read with the cancel-only parent context so that a slow
// operator answer is never truncated by the command deadline; the command deadline
// starts only after the answer has been accepted. postSubmit runs after the durable
// receipt has been rendered and may reconcile the interactive scope with that receipt.
// The question is written through trustedOut because it carries application styling;
// the interpolated resource identifier is provider data and is sanitized first.
func interactiveConfirmedAction(parent context.Context, api InteractiveAPI, state *interactiveState, op, name, resource, generation string, payload json.RawMessage, lines <-chan lineReadResult, out, trustedOut io.Writer, options InteractiveOptions, revalidate func(context.Context) error, postSubmit func(context.Context, map[string]any) error) error {
	question := name + " " + sanitizeInlineText(resource) + "? Confirm " + name + "? " + confirmationHint + " "
	if err := writeConfirmationQuestion(trustedOut, question, options.Color); err != nil {
		return err
	}
	markRecoverablePromptFailure(parent)
	answer, ok := nextPromptLine(parent, lines)
	if !ok {
		return fmt.Errorf("confirmation requires a complete line")
	}
	if answer.err == io.EOF {
		return fmt.Errorf("confirmation requires a complete line")
	}
	if answer.err != nil {
		return fmt.Errorf("confirmation failed: %w", answer.err)
	}
	if answer.overflow {
		return fmt.Errorf("confirmation requires a complete line")
	}
	if value := strings.ToLower(strings.TrimSpace(answer.line)); value != "y" && value != "yes" {
		_, err := fmt.Fprintln(out, name+" cancelled")
		return err
	}
	ctx, cancel := commandContext(parent)
	defer cancel()
	// Revalidate the operation-specific authority after the user confirmation.
	if revalidate != nil {
		if err := revalidate(ctx); err != nil {
			return err
		}
	} else if _, _, _, err := findSelected(ctx, api, state); err != nil {
		return err
	}
	runner := CommandRunner{API: api, Policy: InteractivePolicy, NewID: func() string { return fmt.Sprintf("cli-%d", time.Now().UnixNano()) }}
	intent, err := runner.PrepareAction(ctx, ActionRequest{Operation: op, OperationLabel: name, EndpointID: state.EndpointID, ResourceID: resource, Generation: generation, Payload: payload, Confirmed: true, WaitTimeoutMS: options.WaitTimeoutMS})
	if err != nil {
		return err
	}
	state.commandID = intent.CommandID
	action, err := runner.SubmitAction(ctx, intent)
	if err != nil {
		return fmt.Errorf("command %s result unknown; use status %s to query; %w", intent.CommandID, intent.CommandID, err)
	}
	state.commandID = action.CommandID
	result, err := runner.WaitAction(ctx, action, intent.Budget)
	if err != nil {
		return err
	}
	if err := renderInteractiveStartResult(out, action.CommandID, result); err != nil {
		return err
	}
	if postSubmit == nil {
		return nil
	}
	// The command deadline may already be exhausted by the local wait, so the scope
	// reconciliation gets its own bounded budget instead of inheriting a dead context.
	postCtx, cancelPost := commandContext(parent)
	defer cancelPost()
	return postSubmit(postCtx, result)
}
