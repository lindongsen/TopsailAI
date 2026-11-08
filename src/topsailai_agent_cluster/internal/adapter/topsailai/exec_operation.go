package topsailai

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"strings"
	"time"

	"topsailai_agent_cluster/internal/adapter"
	"topsailai_agent_cluster/internal/protocol"
)

// executeCommand runs one allowlisted argv array in the session working
// directory and returns a bounded snapshot receipt.
//
// The allowlist decision is made by the Endpoint policy hook before this method
// runs, so this method only establishes the directory, confines the arguments and
// executes. It never re-decides policy, because a second decision point would let
// the two disagree.
func (a *Adapter) executeCommand(ctx context.Context, intent protocol.ImmutableIntent) (adapter.ExecuteResult, error) {
	var payload protocol.CommandExecRequest
	if err := json.Unmarshal(intent.Payload, &payload); err != nil {
		return adapter.ExecuteResult{Receipt: failedReceipt(intent, "invalid_payload")}, fmt.Errorf("decode command.exec payload: %w", err)
	}
	if err := payload.Validate(); err != nil {
		return adapter.ExecuteResult{Receipt: failedReceipt(intent, "invalid_payload")}, err
	}
	if err := confineArguments(payload.Argv); err != nil {
		return adapter.ExecuteResult{Receipt: failedReceipt(intent, "argument_not_confined")}, err
	}
	providerKey, err := a.providerTarget(ctx, intent.Target)
	if err != nil {
		return adapter.ExecuteResult{Receipt: failedReceipt(intent, "unknown_target")}, err
	}
	info, err := a.readSessionInfo(ctx, providerKey)
	if err != nil {
		return adapter.ExecuteResult{Receipt: failedReceipt(intent, "session_directory_unavailable")}, err
	}
	directory, err := sessionDirectory(info.ProjectWorkspace, info.Pwd)
	if err != nil {
		return adapter.ExecuteResult{Receipt: failedReceipt(intent, "session_directory_unavailable")}, err
	}
	executable, err := resolveCommandExecutable(payload.Argv[0])
	if err != nil {
		return adapter.ExecuteResult{Receipt: failedReceipt(intent, "command_not_found")}, err
	}
	outcome, runErr := a.execRunner.RunCommand(ctx, executable, payload.Argv, directory)
	result := protocol.CommandExecResult{
		Argv:         payload.Argv,
		ExitCode:     outcome.ExitCode,
		Stdout:       string(outcome.Stdout),
		Stderr:       string(outcome.Stderr),
		Truncated:    outcome.Truncated,
		ObservedAtMS: time.Now().UnixMilli(),
	}
	receipt := commandExecReceipt(intent, result, runErr)
	return adapter.ExecuteResult{Receipt: receipt}, runErr
}

// resolveCommandExecutable resolves the program name to an absolute path.
//
// The allowlist matches a program name, so the name must be resolved through PATH
// exactly once, here, and the resolved path must be executed. Passing the bare
// name to the runner would let the operating system resolve it a second time,
// after the allowlist decision, against a PATH the caller could have influenced.
func resolveCommandExecutable(name string) (string, error) {
	if name == "" {
		return "", errors.New("program name is required")
	}
	if strings.ContainsRune(name, '/') {
		return "", fmt.Errorf("program name %q must not contain a path separator", name)
	}
	path, err := lookPath(name)
	if err != nil {
		return "", fmt.Errorf("resolve program %q: %w", name, err)
	}
	return path, nil
}

// commandExecReceipt converts one command outcome into a standard receipt.
//
// A completed command is an acknowledged effect: the process ran and its exit
// status is known. A timeout is unknown, because the process may have acted
// before it was terminated. A start failure is not applied, because nothing ran.
func commandExecReceipt(intent protocol.ImmutableIntent, result protocol.CommandExecResult, runErr error) protocol.ExecutionReceipt {
	receipt := protocol.ExecutionReceipt{CommandID: intent.CommandID, Phase: protocol.PhaseReceiptRecorded}
	document, err := json.Marshal(result)
	if err == nil {
		receipt.ProviderResponse, receipt.ProviderResponseTruncated = adapter.BoundedProviderResponse(string(document))
	}
	switch {
	case runErr == nil:
		receipt.DeliveryBoundary = protocol.DeliverySubmitted
		receipt.EffectCertainty = protocol.EffectAcknowledged
		receipt.ExitConfirmed = true
		receipt.Outcome = "succeeded"
		if result.ExitCode != 0 {
			// A non-zero exit is a completed command that reported failure, so the
			// effect is still acknowledged: the operator needs the exit status, not
			// a claim that nothing happened.
			receipt.Outcome = "failed"
			receipt.ErrorCode = "command_exit_nonzero"
		}
	case errors.Is(runErr, errCommandTimeout):
		receipt.DeliveryBoundary = protocol.DeliverySubmitted
		receipt.EffectCertainty = protocol.EffectUnknown
		receipt.Outcome = "unconfirmed"
		receipt.ErrorCode = "command_timeout"
	default:
		receipt.DeliveryBoundary = protocol.DeliveryNotStarted
		receipt.EffectCertainty = protocol.EffectNotApplied
		receipt.Outcome = "failed"
		receipt.ErrorCode = "command_not_started"
	}
	receipt.ErrorMessage = strings.TrimSpace(runErrText(runErr))
	return receipt
}

// runErrText returns the error text, or an empty string for a nil error.
func runErrText(err error) string {
	if err == nil {
		return ""
	}
	return err.Error()
}
