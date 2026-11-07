package main

import (
	"context"
	"fmt"
	"io"
	"strings"

	"topsailai_agent_cluster/internal/protocol"
	"topsailai_agent_cluster/internal/tui"
)

// ctlCommand submits one provider control action for an exact session.
//
// The action is addressed by its advertised ctl.<action> spelling, so the
// Endpoint matches it against its own capability descriptor and the Server never
// interprets the action. The action list is not validated here: an unadvertised
// action is rejected by the Endpoint as unsupported, which is the same evidence
// an operator sees for any other admission refusal.
func ctlCommand(ctx context.Context, api tui.CommandAPI, output io.Writer, args []string, confirmed, jsonMode bool, waitTimeoutMS int64, generationFlag string) error {
	if len(args) < 4 {
		return fmt.Errorf("usage: ctl <endpoint-id> <resource-id> <action> [json] [generation]")
	}
	if err := rejectMisplacedFlags(args[0], args); err != nil {
		return err
	}
	endpointID, resourceID, action := args[1], args[2], args[3]
	operation, err := tui.CtlOperation(action)
	if err != nil {
		return err
	}
	payloadText := ""
	generation := generationFlag
	if len(args) >= 5 {
		payloadText = args[4]
	}
	if generation == "" && len(args) >= 6 {
		generation = args[5]
	}
	if len(args) > 6 {
		return fmt.Errorf("unexpected arguments %q; run help ctl for valid syntax", strings.Join(args[6:], " "))
	}
	payload, err := tui.CtlPayload(payloadText)
	if err != nil {
		return err
	}
	return submitAction(ctx, api, output, tui.ActionRequest{
		Operation:      operation,
		OperationLabel: "ctl " + action,
		EndpointID:     endpointID,
		ResourceID:     resourceID,
		Generation:     generation,
		Payload:        payload,
		Confirmed:      confirmed,
		WaitTimeoutMS:  waitTimeoutMS,
	}, jsonMode)
}

// execCommand submits one allowlisted argv array for an exact session.
//
// The argv array is taken from the shell's own word splitting, so it is never
// re-tokenized here: re-splitting a string would reintroduce the shell semantics
// the allowlist cannot reason about. The allowlist decision belongs to the
// Endpoint policy hook, so this path never decides policy locally.
func execCommand(ctx context.Context, api tui.CommandAPI, output io.Writer, args []string, confirmed, jsonMode bool, waitTimeoutMS int64, generationFlag string) error {
	separator := -1
	for index, arg := range args {
		if arg == "--" {
			separator = index
			break
		}
	}
	if separator < 0 {
		return fmt.Errorf("usage: exec <endpoint-id> <resource-id> <generation> -- <argv...>")
	}
	head, argv := args[1:separator], args[separator+1:]
	if len(head) < 2 || len(argv) == 0 {
		return fmt.Errorf("usage: exec <endpoint-id> <resource-id> <generation> -- <argv...>")
	}
	if err := rejectMisplacedFlags(args[0], head); err != nil {
		return err
	}
	endpointID, resourceID := head[0], head[1]
	generation := generationFlag
	if generation == "" && len(head) >= 3 {
		generation = head[2]
	}
	if len(head) > 3 {
		return fmt.Errorf("unexpected arguments %q; run help exec for valid syntax", strings.Join(head[3:], " "))
	}
	if generation == "" {
		return fmt.Errorf("exec requires a generation; run help exec for valid syntax")
	}
	payload, err := tui.ExecPayload(argv)
	if err != nil {
		return err
	}
	return submitAction(ctx, api, output, tui.ActionRequest{
		Operation:      protocol.OperationCommandExec,
		OperationLabel: "exec",
		EndpointID:     endpointID,
		ResourceID:     resourceID,
		Generation:     generation,
		Payload:        payload,
		Confirmed:      confirmed,
		WaitTimeoutMS:  waitTimeoutMS,
	}, jsonMode)
}

// submitAction prepares, submits, waits for and renders one immutable intent.
//
// Every mutating standalone command shares this sequence, so a new command cannot
// accidentally skip the confirmation, capability preflight or durable wait that
// the others perform. A command.exec receipt carries a bounded output snapshot, so
// it is rendered through the same renderer the interactive form uses; every other
// operation keeps the generic receipt rendering.
func submitAction(ctx context.Context, api tui.CommandAPI, output io.Writer, request tui.ActionRequest, jsonMode bool) error {
	runner := legacyRunner(api)
	intent, err := runner.PrepareAction(ctx, request)
	if err != nil {
		return err
	}
	actionResult, err := runner.SubmitAction(ctx, intent)
	if err != nil {
		return err
	}
	result, err := runner.WaitAction(ctx, actionResult, intent.Budget)
	if err != nil {
		return err
	}
	if jsonMode {
		return runner.RenderAction(output, result)
	}
	if request.Operation == protocol.OperationCommandExec {
		return tui.RenderCommandExecResult(output, result, tui.ResolveColorPolicy(false, true, true, true, true))
	}
	return runner.RenderAction(output, result)
}
