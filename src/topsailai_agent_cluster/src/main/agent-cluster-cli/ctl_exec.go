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
	return ctlCommandWithProgress(ctx, api, output, nil, args, confirmed, jsonMode, waitTimeoutMS, generationFlag)
}

// ctlCommandWithProgress is ctlCommand with a diagnostics stream for progress
// lines. A nil diagnostics stream keeps the previous silent behaviour, so a
// caller that has no diagnostics boundary loses nothing.
func ctlCommandWithProgress(ctx context.Context, api tui.CommandAPI, output, diagnostics io.Writer, args []string, confirmed, jsonMode bool, waitTimeoutMS int64, generationFlag string) error {
	// A "--" after the command word ends option parsing, so a JSON payload that
	// begins with a dash is accepted literally. The head is still checked for
	// misplaced flags, because a flag written before the terminator would silently
	// become the action or the payload. The command word is checked before it is
	// read, because a bare "ctl" has no word to inspect.
	if len(args) < 1 {
		return fmt.Errorf("usage: ctl <endpoint-id> <resource-id> <action> [json] [generation]")
	}
	// control is an accepted alias of ctl, so every message names the spelling the
	// operator typed. A usage error that answered "ctl" to a "control" line would
	// point at a command the operator did not write.
	command := args[0]
	usage := "usage: " + command + " <endpoint-id> <resource-id> <action> [json] [generation]"
	head, tail := splitTerminator(args)
	if err := rejectMisplacedFlags(args[0], head); err != nil {
		return err
	}
	args = append(append([]string{}, head...), tail...)
	if len(args) < 4 {
		return fmt.Errorf("%s", usage)
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
		return fmt.Errorf("unexpected arguments %q; run help %s for valid syntax", strings.Join(args[6:], " "), command)
	}
	payload, err := tui.CtlPayload(payloadText)
	if err != nil {
		return err
	}
	return submitActionWithProgress(ctx, api, output, diagnostics, tui.ActionRequest{
		Operation:      operation,
		OperationLabel: command + " " + action,
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
	return execCommandWithProgress(ctx, api, output, nil, args, confirmed, jsonMode, waitTimeoutMS, generationFlag)
}

// execCommandWithProgress is execCommand with a diagnostics stream for progress
// lines. A nil diagnostics stream keeps the previous silent behaviour.
func execCommandWithProgress(ctx context.Context, api tui.CommandAPI, output, diagnostics io.Writer, args []string, confirmed, jsonMode bool, waitTimeoutMS int64, generationFlag string) error {
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
	return submitActionWithProgress(ctx, api, output, diagnostics, tui.ActionRequest{
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
	return submitActionWithProgress(ctx, api, output, nil, request, jsonMode)
}

// submitActionWithProgress is submitAction with a diagnostics stream for progress
// lines. The reporter is built from that stream, so a nil or redirected stream
// stays silent and the machine-readable output is never touched.
func submitActionWithProgress(ctx context.Context, api tui.CommandAPI, output, diagnostics io.Writer, request tui.ActionRequest, jsonMode bool) error {
	runner := legacyRunner(api)
	progress := tui.NewActionProgress(diagnostics, request)
	intent, err := runner.PrepareAction(ctx, request)
	if err != nil {
		return err
	}
	actionResult, err := runner.SubmitAction(ctx, intent)
	if err != nil {
		return err
	}
	result, err := runner.WaitActionWithProgress(ctx, actionResult, intent.Budget, progress)
	if err != nil {
		return err
	}
	if jsonMode {
		return runner.RenderAction(output, result)
	}
	if request.Operation == protocol.OperationCommandExec {
		// The output boundary owns the colour decision, so a terminal run keeps
		// the provider's SGR colour and a redirected run stays plain.
		return tui.RenderCommandExecResult(output, result, tui.OutputColorPolicy(output))
	}
	return runner.RenderAction(output, result)
}
