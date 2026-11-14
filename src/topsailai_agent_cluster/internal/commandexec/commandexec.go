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
// The provider records the project workspace the session belongs to, and that is
// the stable location the operator means by "the session's folder". When it does
// not resolve to an existing directory the call fails closed: falling back to the
// Endpoint process working directory would run the command somewhere the operator
// never selected.
func SessionDirectory(projectWorkspace string) (string, error) {
	trimmed := strings.TrimSpace(projectWorkspace)
	if trimmed == "" || !filepath.IsAbs(trimmed) {
		return "", ErrDirectoryUnresolved
	}
	// Resolve symlinks before the directory check so the confinement decision is
	// made on the real location rather than on a link that points elsewhere.
	resolved, err := filepath.EvalSymlinks(trimmed)
	if err != nil {
		return "", ErrDirectoryUnresolved
	}
	info, err := os.Stat(resolved)
	if err != nil || !info.IsDir() {
		return "", ErrDirectoryUnresolved
	}
	return resolved, nil
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
