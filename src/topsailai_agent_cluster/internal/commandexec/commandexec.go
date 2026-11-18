// Package commandexec runs one allowlisted argv array on the Endpoint itself.
//
// The public standard operation command.exec is deliberately not forwarded to a
// Provider CLI. The Endpoint owns the allowlist, the working-directory
// resolution, the confinement decision, the minimal environment, the timeout,
// the output bounds and the exact-process cleanup, so the command runs where
// those decisions were made. Forwarding it to a provider would move the
// execution to a process that never saw the allowlist and cannot report the
// real exit status of the operator's own program.
package commandexec

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"time"

	"topsailai_agent_cluster/internal/adapter"
	"topsailai_agent_cluster/internal/protocol"
)

// DefaultTimeout bounds one allowlisted command when the caller supplies none.
const DefaultTimeout = 30 * time.Second

// ErrTimeout reports that the command exceeded its bounded lifetime. The effect
// is unknown because the process may have acted before it was terminated.
var ErrTimeout = errors.New("command exceeded its bounded lifetime")

// ErrDirectoryUnresolved reports that no session working directory could be
// established. It is a definite failure, not an unknown effect: nothing ran.
var ErrDirectoryUnresolved = errors.New("session working directory is unresolved")

// ErrArgumentNotConfined reports that an argument would leave the session
// working directory. It is a definite failure, not an unknown effect.
var ErrArgumentNotConfined = errors.New("argument is not confined to the session working directory")

// Outcome is one completed local command observation.
type Outcome struct {
	Stdout    []byte
	Stderr    []byte
	ExitCode  int
	Truncated bool
}

// Runner executes one allowlisted argv array in a fixed directory.
type Runner interface {
	Run(ctx context.Context, executable string, argv []string, dir string) (Outcome, error)
}

// SessionDirectory resolves the working directory for one session.
//
// The provider records two candidate directories. project_workspace is the project
// the session belongs to, and pwd is the directory the session was started from;
// the project workspace wins because it is the stable location the operator means
// by "the session's folder". A session started from a subdirectory of its project
// still reports the project, while a session whose project workspace is absent on
// this host still reports the directory it was started from, so the fallback keeps
// a command runnable instead of refusing it.
//
// When neither candidate resolves to an existing directory the call fails closed:
// falling back to the Endpoint process working directory would run the command
// somewhere the operator never selected.
func SessionDirectory(projectWorkspace, pwd string) (string, error) {
	for _, candidate := range []string{projectWorkspace, pwd} {
		trimmed := strings.TrimSpace(candidate)
		if trimmed == "" || !filepath.IsAbs(trimmed) {
			continue
		}
		// Resolve symlinks before the directory check so the confinement decision
		// is made on the real location rather than on a link that points elsewhere.
		resolved, err := filepath.EvalSymlinks(trimmed)
		if err != nil {
			continue
		}
		info, err := os.Stat(resolved)
		if err != nil || !info.IsDir() {
			continue
		}
		return resolved, nil
	}
	return "", ErrDirectoryUnresolved
}

// ConfineArguments rejects arguments that would address a location outside the
// session working directory.
//
// The program name is excluded because it is administrative configuration
// governed by the allowlist, while the remaining tokens are operator input. An
// absolute argument addresses a fixed location the operator did not select, and a
// parent-traversal element walks out of the directory.
func ConfineArguments(argv []string) error {
	if len(argv) == 0 {
		return errors.New("argv is required")
	}
	for index, token := range argv[1:] {
		if filepath.IsAbs(token) {
			return fmt.Errorf("%w: argument %d is an absolute path", ErrArgumentNotConfined, index+1)
		}
		for _, element := range strings.Split(token, "/") {
			if element == ".." {
				return fmt.Errorf("%w: argument %d traverses a parent directory", ErrArgumentNotConfined, index+1)
			}
		}
	}
	return nil
}

// ResolveExecutable resolves the program name to an absolute path.
//
// The allowlist matches a program name, so the name must be resolved through PATH
// exactly once, here, and the resolved path must be executed. Passing the bare
// name to the runner would let the operating system resolve it a second time,
// after the allowlist decision, against a PATH the caller could have influenced.
func ResolveExecutable(name string) (string, error) {
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

// ConfiguredDirectory resolves the Endpoint-configured working directory for a
// command.exec request that carries no session target.
//
// Endpoint scope has no session, so there is no provider evidence to ask for a
// directory. The directory is therefore Endpoint configuration, and it is
// validated with the same sequence SessionDirectory uses: an absolute path, then
// symlink resolution, then a directory check. Sharing the sequence is what keeps
// the configured directory and a session directory the same kind of fact, so the
// confinement decision is made on the real location in both cases.
//
// An empty value is a refusal rather than a fallback. Falling back to the
// Endpoint process working directory would run the operator's command somewhere
// the operator never selected, which is a silent wrong-place execution instead of
// a visible failure. The message names the setting, because the operator cannot
// fix a refusal that does not say what to configure.
func ConfiguredDirectory(directory string) (string, error) {
	trimmed := strings.TrimSpace(directory)
	if trimmed == "" {
		return "", fmt.Errorf("%w: AGENT_CLUSTER_ENDPOINT_COMMAND_DIR is not configured, so endpoint scope has no working directory", ErrDirectoryUnresolved)
	}
	if !filepath.IsAbs(trimmed) {
		return "", fmt.Errorf("%w: AGENT_CLUSTER_ENDPOINT_COMMAND_DIR %q is not an absolute path", ErrDirectoryUnresolved, trimmed)
	}
	resolved, err := filepath.EvalSymlinks(trimmed)
	if err != nil {
		return "", fmt.Errorf("%w: AGENT_CLUSTER_ENDPOINT_COMMAND_DIR %q cannot be resolved: %v", ErrDirectoryUnresolved, trimmed, err)
	}
	info, err := os.Stat(resolved)
	if err != nil || !info.IsDir() {
		return "", fmt.Errorf("%w: AGENT_CLUSTER_ENDPOINT_COMMAND_DIR %q is not a directory", ErrDirectoryUnresolved, trimmed)
	}
	return resolved, nil
}

// DecodeRequest decodes, validates and confines one command.exec payload.
//
// It returns the standard error code for a refusal together with the error, so
// both call sites record the same code for the same defect. Two call sites exist
// because the directory has two sources, and a second copy of this sequence would
// let one of them accept a payload the other refuses.
func DecodeRequest(intent protocol.ImmutableIntent) (protocol.CommandExecRequest, string, error) {
	var payload protocol.CommandExecRequest
	if err := json.Unmarshal(intent.Payload, &payload); err != nil {
		return payload, "invalid_payload", fmt.Errorf("decode command.exec payload: %w", err)
	}
	if err := payload.Validate(); err != nil {
		return payload, "invalid_payload", err
	}
	if err := ConfineArguments(payload.Argv); err != nil {
		return payload, "argument_not_confined", err
	}
	return payload, "", nil
}

// Execute runs one decoded command.exec payload in an already resolved directory.
//
// The directory is a parameter rather than something this function resolves,
// because the two call sites resolve it from different authorities: a targeted
// request asks the provider where its session lives, while an untargeted request
// uses the Endpoint's own configured directory. Everything after that decision is
// identical, so it lives here once.
func Execute(ctx context.Context, runner Runner, intent protocol.ImmutableIntent, payload protocol.CommandExecRequest, directory string) (adapter.ExecuteResult, error) {
	executable, err := ResolveExecutable(payload.Argv[0])
	if err != nil {
		return adapter.ExecuteResult{Receipt: FailedReceipt(intent, "command_not_found")}, err
	}
	outcome, runErr := runner.Run(ctx, executable, payload.Argv, directory)
	result := protocol.CommandExecResult{
		Argv:         payload.Argv,
		ExitCode:     outcome.ExitCode,
		Stdout:       string(outcome.Stdout),
		Stderr:       string(outcome.Stderr),
		Truncated:    outcome.Truncated,
		ObservedAtMS: time.Now().UnixMilli(),
	}
	return adapter.ExecuteResult{Receipt: Receipt(intent, result, runErr)}, runErr
}

// Receipt converts one command outcome into a standard receipt.
//
// A completed command is an acknowledged effect: the process ran and its exit
// status is known. A timeout is unknown, because the process may have acted
// before it was terminated. A start failure is not applied, because nothing ran.
func Receipt(intent protocol.ImmutableIntent, result protocol.CommandExecResult, runErr error) protocol.ExecutionReceipt {
	receipt := protocol.ExecutionReceipt{CommandID: intent.CommandID, Phase: protocol.PhaseReceiptRecorded}
	if document, err := json.Marshal(result); err == nil {
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
	case errors.Is(runErr, ErrTimeout):
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
	if runErr != nil {
		receipt.ErrorMessage = strings.TrimSpace(runErr.Error())
	}
	return receipt
}

// FailedReceipt builds the receipt for a command that was refused before it ran.
func FailedReceipt(intent protocol.ImmutableIntent, code string) protocol.ExecutionReceipt {
	return protocol.ExecutionReceipt{CommandID: intent.CommandID, Phase: protocol.PhaseReceiptRecorded, EffectCertainty: protocol.EffectNotApplied, Outcome: "failed", ErrorCode: code}
}
