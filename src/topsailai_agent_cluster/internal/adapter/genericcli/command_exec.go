package genericcli

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"time"

	"topsailai_agent_cluster/internal/adapter"
	"topsailai_agent_cluster/internal/commandexec"
	"topsailai_agent_cluster/internal/protocol"
)

// executeCommand runs one allowlisted argv array in the session working
// directory and returns a bounded snapshot receipt.
//
// The allowlist decision is made by the Endpoint policy hook before this method
// runs, so this method only establishes the directory, confines the arguments and
// executes. It never re-decides policy, because a second decision point would let
// the two disagree.
//
// The working directory comes from provider evidence rather than from a local
// guess: the Endpoint asks the provider where the session lives and refuses the
// command when the provider reports no usable directory. Falling back to the
// Endpoint process working directory would run the operator's command somewhere
// the operator never selected, which is a silent wrong-place execution instead of
// a visible failure.
func (a *Adapter) executeCommand(ctx context.Context, intent protocol.ImmutableIntent) (adapter.ExecuteResult, error) {
	var payload protocol.CommandExecRequest
	if err := json.Unmarshal(intent.Payload, &payload); err != nil {
		return adapter.ExecuteResult{Receipt: commandexec.FailedReceipt(intent, "invalid_payload")}, fmt.Errorf("decode command.exec payload: %w", err)
	}
	if err := payload.Validate(); err != nil {
		return adapter.ExecuteResult{Receipt: commandexec.FailedReceipt(intent, "invalid_payload")}, err
	}
	if err := commandexec.ConfineArguments(payload.Argv); err != nil {
		return adapter.ExecuteResult{Receipt: commandexec.FailedReceipt(intent, "argument_not_confined")}, err
	}
	if intent.Target == nil {
		return adapter.ExecuteResult{Receipt: commandexec.FailedReceipt(intent, "unknown_target")}, errors.New("command.exec requires a target")
	}
	if _, err := a.providerTarget(ctx, *intent.Target, false); err != nil {
		return adapter.ExecuteResult{Receipt: commandexec.FailedReceipt(intent, "unknown_target")}, err
	}
	inspection, err := a.Inspect(ctx, adapter.InspectRequest{Target: *intent.Target})
	if err != nil {
		return adapter.ExecuteResult{Receipt: commandexec.FailedReceipt(intent, "session_directory_unavailable")}, err
	}
	directory, err := commandexec.SessionDirectory(inspection.ProviderProjectWorkspace)
	if err != nil {
		return adapter.ExecuteResult{Receipt: commandexec.FailedReceipt(intent, "session_directory_unavailable")}, err
	}
	executable, err := commandexec.ResolveExecutable(payload.Argv[0])
	if err != nil {
		return adapter.ExecuteResult{Receipt: commandexec.FailedReceipt(intent, "command_not_found")}, err
	}
	outcome, runErr := a.commands.Run(ctx, executable, payload.Argv, directory)
	result := protocol.CommandExecResult{
		Argv:         payload.Argv,
		ExitCode:     outcome.ExitCode,
		Stdout:       string(outcome.Stdout),
		Stderr:       string(outcome.Stderr),
		Truncated:    outcome.Truncated,
		ObservedAtMS: time.Now().UnixMilli(),
	}
	return adapter.ExecuteResult{Receipt: commandexec.Receipt(intent, result, runErr)}, runErr
}
