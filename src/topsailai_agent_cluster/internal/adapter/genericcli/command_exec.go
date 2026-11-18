package genericcli

import (
	"context"

	"topsailai_agent_cluster/internal/adapter"
	"topsailai_agent_cluster/internal/commandexec"
	"topsailai_agent_cluster/internal/protocol"
)

// executeCommand runs one allowlisted argv array and returns a bounded snapshot
// receipt.
//
// The allowlist decision is made by the Endpoint policy hook before this method
// runs, so this method only establishes the directory, confines the arguments and
// executes. It never re-decides policy, because a second decision point would let
// the two disagree.
//
// The working directory has two sources and the target decides which one applies.
// A targeted request addresses one session, so the provider is asked where that
// session lives and the command is refused when the provider reports no usable
// directory. An untargeted request addresses the Endpoint itself, so the
// Endpoint's own configured directory applies. Neither source falls back to the
// Endpoint process working directory: that would run the operator's command
// somewhere the operator never selected, which is a silent wrong-place execution
// instead of a visible failure.
func (a *Adapter) executeCommand(ctx context.Context, intent protocol.ImmutableIntent) (adapter.ExecuteResult, error) {
	payload, code, err := commandexec.DecodeRequest(intent)
	if err != nil {
		return adapter.ExecuteResult{Receipt: commandexec.FailedReceipt(intent, code)}, err
	}
	var directory string
	if intent.Target == nil {
		directory, err = commandexec.ConfiguredDirectory(a.config.CommandDir)
	} else {
		directory, err = a.sessionCommandDirectory(ctx, *intent.Target)
	}
	if err != nil {
		return adapter.ExecuteResult{Receipt: commandexec.FailedReceipt(intent, "session_directory_unavailable")}, err
	}
	return commandexec.Execute(ctx, a.commands, intent, payload, directory)
}

// sessionCommandDirectory resolves the working directory of one targeted
// command.exec request from provider evidence.
//
// The target is proven to belong to this adapter before the provider is asked,
// so a resource owned by another adapter is refused instead of being inspected
// through the wrong provider. The directory itself still comes from the provider,
// because only the provider knows where the session lives; the Endpoint never
// guesses a path from a resource ID.
func (a *Adapter) sessionCommandDirectory(ctx context.Context, target protocol.CommandTarget) (string, error) {
	if _, err := a.providerTarget(ctx, target, false); err != nil {
		return "", err
	}
	inspection, err := a.Inspect(ctx, adapter.InspectRequest{Target: target})
	if err != nil {
		return "", err
	}
	return commandexec.SessionDirectory(inspection.ProviderProjectWorkspace, inspection.ProviderPwd)
}
