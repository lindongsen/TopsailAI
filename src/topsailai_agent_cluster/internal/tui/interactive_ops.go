package tui

import (
	"bufio"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"strings"
	"time"

	"topsailai_agent_cluster/internal/protocol"
)

func interactiveLogs(parent context.Context, api InteractiveAPI, state *interactiveState, rest string, maxBytes int, out io.Writer) error {
	if err := state.requireUsable(); err != nil {
		return err
	}
	endpointID, resourceID := state.EndpointID, state.SessionID
	if rest != "" {
		args := strings.Fields(rest)
		if len(args) != 2 {
			return fmt.Errorf("usage: logs [endpoint] [session]")
		}
		endpointID, resourceID = args[0], args[1]
	}
	if endpointID == "" || resourceID == "" {
		return fmt.Errorf("no session selected; use <endpoint> <session>")
	}
	ctx, cancel := commandContext(parent)
	defer cancel()
	return (CommandRunner{API: api, Policy: InteractivePolicy}).Logs(ctx, out, endpointID, resourceID, maxBytes, false)
}

func interactiveValue(values map[string]any, key string) string {
	value, _ := values[key].(string)
	return value
}

func interactiveStatus(parent context.Context, api InteractiveAPI, state *interactiveState, rest string, out io.Writer) error {
	if state.Invalidated {
		return fmt.Errorf("selected session invalidated; use the session again")
	}
	commandID := strings.TrimSpace(rest)
	if commandID == "" {
		commandID = state.commandID
	}
	ctx, cancel := commandContext(parent)
	defer cancel()
	if commandID == "" {
		_, _, session, err := findSelected(ctx, api, state)
		if err != nil {
			return err
		}
		_, err = fmt.Fprintln(out, session.State)
		return err
	}
	return (CommandRunner{API: api, Policy: InteractivePolicy}).Status(ctx, out, commandID, false)
}

func interactiveSend(parent context.Context, api InteractiveAPI, state *interactiveState, rest string, reader *bufio.Reader, out io.Writer, options InteractiveOptions) error {
	if err := state.requireUsable(); err != nil {
		return err
	}
	payloadText := strings.TrimSpace(rest)
	if payloadText == "" {
		return fmt.Errorf("payload must be a JSON object")
	}
	if len(payloadText) == 0 || len(payloadText) > options.LineLimit {
		return fmt.Errorf("payload exceeds the maximum length")
	}
	var payload map[string]any
	if err := json.Unmarshal([]byte(payloadText), &payload); err != nil || payload == nil {
		return fmt.Errorf("payload must be a JSON object")
	}
	ctx, cancel := commandContext(parent)
	defer cancel()
	beforeCapability, err := PreflightCapability(ctx, api, state.EndpointID, protocol.OperationMessageSend)
	if err != nil {
		return err
	}
	preview := payloadText
	if len(preview) > 512 {
		preview = preview[:512] + "..."
	}
	if _, err := fmt.Fprintf(out, "send %s? Confirm send? [y/N] ", preview); err != nil {
		return err
	}
	answer, overflow, err := readLine(reader, options.LineLimit)
	if overflow || err != nil {
		return fmt.Errorf("confirmation requires a complete line")
	}
	answer = strings.ToLower(strings.TrimSpace(answer))
	if answer != "y" && answer != "yes" {
		_, writeErr := fmt.Fprintln(out, "send cancelled")
		return writeErr
	}
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
	intent, err := runner.PrepareAction(ctx, ActionRequest{Operation: protocol.OperationMessageSend, EndpointID: state.EndpointID, ResourceID: state.SessionID, Generation: session.Generation, Payload: json.RawMessage(payloadText), Confirmed: true, WaitTimeoutMS: options.WaitTimeoutMS})
	if err != nil {
		return err
	}
	actionResult, err := runner.SubmitAction(ctx, intent)
	if err != nil {
		return err
	}
	state.commandID = actionResult.CommandID
	if _, err = fmt.Fprintln(out, "command submitted:", state.commandID); err != nil {
		return err
	}
	result, err := runner.WaitAction(ctx, actionResult, intent.Budget)
	if err != nil {
		return err
	}
	return runner.RenderAction(out, result)
}
