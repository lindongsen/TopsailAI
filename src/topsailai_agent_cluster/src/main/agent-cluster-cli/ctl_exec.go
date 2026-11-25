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
		Operation:          operation,
		OperationLabel:     command + " " + action,
		EndpointID:         endpointID,
		ResourceID:         resourceID,
		ProviderGeneration: generation,
		Payload:            payload,
		Confirmed:          confirmed,
		WaitTimeoutMS:      waitTimeoutMS,
	}, jsonMode)
}

// execCommand submits one allowlisted argv array for an exact session or for the
// Endpoint itself.
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
//
// Two forms are accepted, and the head length decides which one applies:
//
//	exec <endpoint> <resource> <generation> -- <argv...>   session target
//	exec <endpoint> -- <argv...>                           endpoint target
//
// The endpoint form exists because the interactive "!" prefix already runs on the
// machine itself when the operator is in endpoint scope, and the Endpoint already
// serves a target-less command.exec: it resolves the working directory from its
// own configuration instead of from a session. Without this form a machine-level
// command was reachable only from the REPL, so a script could not run the same
// allowlisted command the operator could.
//
// The two forms are distinguished by the head length rather than by a flag,
// because the endpoint is always the first positional and a session target always
// names a resource after it. A head of exactly one element therefore cannot be a
// session form missing its resource, and a head of two or more cannot be the
// endpoint form, so no input is ambiguous between them.
func execCommandWithProgress(ctx context.Context, api tui.CommandAPI, output, diagnostics io.Writer, args []string, confirmed, jsonMode bool, waitTimeoutMS int64, generationFlag string) error {
	usage := "usage: exec <endpoint-id> <resource-id> <generation> -- <argv...> | exec <endpoint-id> -- <argv...>"
	separator := -1
	for index, arg := range args {
		if arg == "--" {
			separator = index
			break
		}
	}
	if separator < 0 {
		return fmt.Errorf("%s", usage)
	}
	head, argv := args[1:separator], args[separator+1:]
	if len(head) < 1 || len(argv) == 0 {
		return fmt.Errorf("%s", usage)
	}
	if err := rejectMisplacedFlags(args[0], head); err != nil {
		return err
	}
	// Everything after the separator is literal argv by contract, so a "--yes"
	// written there is a command argument and never a confirmation. The parser
	// must not hoist it across the separator, because "exec ep -- apt-get install
	// --yes pkg" is legitimate argv. What it must not do is repeat the fixed
	// advice, which tells the operator to add the flag they already wrote and so
	// sends them to add it again instead of moving it.
	hint := execConfirmationHint(argv)
	endpointID := head[0]
	// A single head element addresses the machine. It carries no resource and no
	// generation, because there is no session identity to name and no process to
	// prove; the Endpoint resolves the working directory from its own
	// configuration. A generation supplied here is refused rather than ignored,
	// because a silently discarded generation would look like a revalidation that
	// never happened.
	if len(head) == 1 {
		if generationFlag != "" {
			return fmt.Errorf("exec on an endpoint addresses no process, so it takes no generation; drop --generation or name a session resource; run help exec for valid syntax")
		}
		payload, err := tui.ExecPayload(argv)
		if err != nil {
			return err
		}
		return submitActionWithProgress(ctx, api, output, diagnostics, tui.ActionRequest{
			Operation:        protocol.OperationCommandExec,
			OperationLabel:   "exec",
			EndpointID:       endpointID,
			Payload:          payload,
			Confirmed:        confirmed,
			WaitTimeoutMS:    waitTimeoutMS,
			ConfirmationHint: hint,
		}, jsonMode)
	}
	resourceID := head[1]
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
		Operation:          protocol.OperationCommandExec,
		OperationLabel:     "exec",
		EndpointID:         endpointID,
		ResourceID:         resourceID,
		ProviderGeneration: generation,
		Payload:            payload,
		Confirmed:          confirmed,
		WaitTimeoutMS:      waitTimeoutMS,
		ConfirmationHint:   hint,
	}, jsonMode)
}

// execConfirmationHint explains a confirmation refusal when the operator wrote
// the confirming flag after the "--" separator.
//
// Everything after the separator is literal argv, so the flag became a command
// argument and the command is genuinely unconfirmed. The fixed advice is wrong
// here: it tells the operator to add a flag they already wrote, so the natural
// next step is to add it again rather than to move it. The hint names the
// placement instead, and it is returned only when the tail actually contains a
// yes spelling, so an ordinary unconfirmed invocation keeps the previous message
// byte-identical.
//
// The tail is inspected for the spelling only. It is never rewritten, because a
// command may legitimately take "--yes" as its own argument, and removing it
// would change what the operator asked to run.
func execConfirmationHint(argv []string) string {
	for _, arg := range argv {
		name, _ := splitOptionName(arg)
		if name == "yes" {
			return "the --yes after -- is part of the command argv, so it did not confirm; write --yes before --, as in exec <endpoint> --yes -- <argv...>"
		}
	}
	return ""
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
	if request.ResourceID != "" && request.ProviderTarget == "" {
		identity := tui.SessionReadIdentity(ctx, api, request.EndpointID, request.ResourceID)
		request.ProviderTarget = identity.ProviderTarget
		if request.ProviderSessionID == "" {
			request.ProviderSessionID = identity.ProviderSessionID
		}
	}
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
		return renderActionResult(output, result, true)
	}
	if request.Operation == protocol.OperationCommandExec {
		// The output boundary owns the colour decision, so a terminal run keeps
		// the provider's SGR colour and a redirected run stays plain.
		return tui.RenderCommandExecResult(output, result, tui.OutputColorPolicy(output))
	}
	return renderActionResult(output, result, false)
}
