package provider

import (
	"context"
	"encoding/json"
	"fmt"
	"os"
	"strings"
	"time"

	"topsailai_scheduler/runner"
)

// Operation names passed to a provider CLI as its first argument.
const (
	// OperationStart begins one run.
	OperationStart = "start"
	// OperationPoll reports the state of one run.
	OperationPoll = "poll"
	// OperationStop asks one run to end.
	OperationStop = "stop"
)

// CLI adapts an executable that speaks the provider protocol.
//
// The executable is an independent program, so a provider can be written in any
// language, released on its own schedule, and replaced without rebuilding the
// scheduler. The scheduler only ever runs three short commands:
//
//	<command> start   request JSON on stdin, receipt JSON on stdout
//	<command> poll    handle JSON on stdin, observation JSON on stdout
//	<command> stop    handle JSON on stdin, no output required
//
// Each command must exit promptly. A provider that needs to run work in the
// background detaches it itself and returns a handle; the scheduler supervises
// through Poll rather than by waiting for the start command to finish.
type CLI struct {
	// name is the provider name used in a task's YAML.
	name string
	// command is the executable to run.
	command string
	// args are arguments placed before the operation name.
	args []string
	// timeout bounds each protocol call. Zero means the default.
	timeout time.Duration
	// maxOutputBytes caps retained output from a protocol call.
	maxOutputBytes int
}

// CLIOptions configures a CLI adapter.
type CLIOptions struct {
	// Name is the provider name used in a task's YAML.
	Name string
	// Command is the executable to run.
	Command string
	// Args are arguments placed before the operation name.
	Args []string
	// Timeout bounds each protocol call. Zero means DefaultCallTimeout.
	Timeout time.Duration
	// MaxOutputBytes caps retained output. Zero means the runner default.
	MaxOutputBytes int
}

// DefaultCallTimeout bounds one protocol call when none is configured.
//
// A protocol call is a short exchange, not the work itself, so a provider that
// does not answer within this window is treated as broken rather than slow.
const DefaultCallTimeout = 30 * time.Second

// NewCLI returns a CLI adapter for an executable.
func NewCLI(options CLIOptions) (*CLI, error) {
	name := strings.TrimSpace(options.Name)
	if name == "" {
		return nil, fmt.Errorf("provider name must not be empty")
	}
	command := strings.TrimSpace(options.Command)
	if command == "" {
		return nil, fmt.Errorf("provider %q requires a command", name)
	}
	return &CLI{
		name:           name,
		command:        command,
		args:           options.Args,
		timeout:        options.Timeout,
		maxOutputBytes: options.MaxOutputBytes,
	}, nil
}

// Name returns the provider name used in a task's YAML.
func (c *CLI) Name() string { return c.name }

// startRequest is the JSON document written to a provider's stdin for start.
type startRequest struct {
	// ProtocolVersion is the protocol revision the scheduler speaks.
	ProtocolVersion int `json:"protocol_version"`
	// TaskID is the task identity.
	TaskID string `json:"task_id"`
	// TaskPath is the absolute task Markdown path.
	TaskPath string `json:"task_path"`
	// TaskDir is the absolute folder holding the task files.
	TaskDir string `json:"task_dir"`
	// Workspace is the working directory the run should use.
	Workspace string `json:"workspace"`
	// Command is the executable the task asks to run. Empty means the provider
	// decides for itself.
	Command string `json:"command"`
	// Args are the arguments for Command, with placeholders already expanded.
	Args []string `json:"args"`
	// Env holds extra environment variables for this run only.
	Env map[string]string `json:"env"`
	// TimeoutMS bounds the run in milliseconds. Zero means no timeout.
	TimeoutMS int64 `json:"timeout_ms"`
}

// startReceipt is the JSON document a provider writes for start.
type startReceipt struct {
	// ProtocolVersion is the protocol revision the provider implements.
	ProtocolVersion int `json:"protocol_version"`
	// RunID is the provider-defined run identity. It is required.
	RunID string `json:"run_id"`
	// PID is the run's process id, when the provider knows it.
	PID int `json:"pid"`
	// Detail is free-form provider text for logs.
	Detail string `json:"detail"`
}

// handleDocument is the JSON document written to a provider's stdin for poll
// and stop.
type handleDocument struct {
	// ProtocolVersion is the protocol revision the scheduler speaks.
	ProtocolVersion int `json:"protocol_version"`
	// RunID is the provider-defined run identity.
	RunID string `json:"run_id"`
	// PID is the run's process id, when known.
	PID int `json:"pid"`
}

// observationDocument is the JSON document a provider writes for poll.
type observationDocument struct {
	// State is the run state: running, finished or unknown.
	State string `json:"state"`
	// ExitCode is the run's exit status when known.
	ExitCode int `json:"exit_code"`
	// Detail is free-form provider text for logs.
	Detail string `json:"detail"`
	// Reason is a machine-readable fact about the state, empty when the
	// provider has nothing extra to say.
	Reason string `json:"reason"`
}

// Start begins one run and returns its handle.
func (c *CLI) Start(ctx context.Context, request Request) (Handle, error) {
	// The workspace becomes the provider process's working directory, so a
	// missing one would surface as a confusing "no such file or directory" on
	// the provider executable. Checking it here names the real cause.
	workspace, err := c.workspaceDir(request.Workspace)
	if err != nil {
		return Handle{}, err
	}

	document := startRequest{
		ProtocolVersion: ProtocolVersion,
		TaskID:          request.TaskID,
		TaskPath:        request.TaskPath,
		TaskDir:         request.TaskDir,
		Workspace:       request.Workspace,
		Command:         request.Command,
		Args:            request.Args,
		Env:             request.Env,
		TimeoutMS:       request.Timeout.Milliseconds(),
	}

	output, err := c.call(ctx, OperationStart, document, workspace)
	if err != nil {
		return Handle{}, err
	}

	var receipt startReceipt
	if err := decodeReceipt(output, &receipt); err != nil {
		return Handle{}, fmt.Errorf("provider %q start: %w", c.name, err)
	}
	if receipt.ProtocolVersion != 0 && receipt.ProtocolVersion != ProtocolVersion {
		return Handle{}, fmt.Errorf("provider %q speaks protocol version %d, this scheduler speaks %d",
			c.name, receipt.ProtocolVersion, ProtocolVersion)
	}
	runID := strings.TrimSpace(receipt.RunID)
	if runID == "" {
		return Handle{}, fmt.Errorf("provider %q start returned no run_id", c.name)
	}

	return Handle{
		Provider:  c.name,
		ID:        runID,
		PID:       receipt.PID,
		StartedAt: time.Now(),
	}, nil
}

// Poll reports the state of a run previously started.
func (c *CLI) Poll(ctx context.Context, handle Handle) (Observation, error) {
	if strings.TrimSpace(handle.ID) == "" {
		return Observation{}, fmt.Errorf("provider %q poll: handle has no run id", c.name)
	}

	output, err := c.call(ctx, OperationPoll, handleDocument{
		ProtocolVersion: ProtocolVersion,
		RunID:           handle.ID,
		PID:             handle.PID,
	}, "")
	if err != nil {
		return Observation{}, err
	}

	var document observationDocument
	if err := decodeReceipt(output, &document); err != nil {
		return Observation{}, fmt.Errorf("provider %q poll: %w", c.name, err)
	}
	state, err := ParseState(document.State)
	if err != nil {
		return Observation{}, fmt.Errorf("provider %q poll: %w", c.name, err)
	}

	return Observation{
		State:    state,
		ExitCode: document.ExitCode,
		Detail:   document.Detail,
		Reason:   document.Reason,
	}, nil
}

// Stop asks a run to end.
//
// A provider that has already lost the run may report success: the desired state
// is reached, and failing here would make a stop impossible to complete.
func (c *CLI) Stop(ctx context.Context, handle Handle) error {
	if strings.TrimSpace(handle.ID) == "" {
		return fmt.Errorf("provider %q stop: handle has no run id", c.name)
	}

	if _, err := c.call(ctx, OperationStop, handleDocument{
		ProtocolVersion: ProtocolVersion,
		RunID:           handle.ID,
		PID:             handle.PID,
	}, ""); err != nil {
		return err
	}
	return nil
}

// call runs one protocol operation and returns its stdout.
//
// The request is written to stdin rather than passed as arguments so a task path
// containing spaces or shell metacharacters needs no quoting, and so a large
// environment map does not hit an argument length limit.
//
// dir is the working directory for the provider process. The scheduler owns the
// workspace, so a provider inherits it rather than resolving one for itself: a
// provider-specific environment variable would only work for that one provider,
// and a provider that guessed would disagree with the task's YAML. An empty dir
// keeps the scheduler's own directory, which is what poll and stop want because
// they only read the provider's own state and never touch the workspace.
func (c *CLI) call(ctx context.Context, operation string, document any, dir string) (string, error) {
	payload, err := json.Marshal(document)
	if err != nil {
		return "", fmt.Errorf("provider %q %s: encode request: %w", c.name, operation, err)
	}

	arguments := make([]string, 0, len(c.args)+1)
	arguments = append(arguments, c.args...)
	arguments = append(arguments, operation)

	result := runner.Run(ctx, runner.Request{
		Command:        c.command,
		Args:           arguments,
		Dir:            dir,
		Stdin:          string(payload),
		Timeout:        c.timeout,
		MaxOutputBytes: c.maxOutputBytes,
		// The reply is parsed from stdout, so a provider's diagnostics on stderr
		// must not be interleaved into it.
		SeparateStreams: true,
	})

	if result.TimedOut {
		return "", fmt.Errorf("provider %q %s did not answer within %s",
			c.name, operation, c.effectiveTimeout())
	}
	if result.Canceled {
		return "", fmt.Errorf("provider %q %s canceled", c.name, operation)
	}
	if result.Err != nil {
		return "", fmt.Errorf("provider %q %s: %w", c.name, operation, result.Err)
	}
	if result.ExitCode != 0 {
		return "", fmt.Errorf("provider %q %s exited %d: %s",
			c.name, operation, result.ExitCode, strings.TrimSpace(result.Stderr))
	}
	return result.Stdout, nil
}

// workspaceDir validates the workspace and returns the directory to run in.
//
// An empty workspace means the scheduler's own directory, which is a valid
// choice for a task that does not care where it runs. A named workspace must be
// an existing directory: the provider process cannot start in a folder that is
// not there, and reporting that as a provider launch failure would send an
// operator looking at the wrong thing.
func (c *CLI) workspaceDir(workspace string) (string, error) {
	trimmed := strings.TrimSpace(workspace)
	if trimmed == "" {
		return "", nil
	}
	info, err := os.Stat(trimmed)
	if err != nil {
		return "", fmt.Errorf("provider %q workspace %q: %w", c.name, trimmed, err)
	}
	if !info.IsDir() {
		return "", fmt.Errorf("provider %q workspace %q is not a directory", c.name, trimmed)
	}
	return trimmed, nil
}

// effectiveTimeout returns the configured call timeout or the default.
func (c *CLI) effectiveTimeout() time.Duration {
	if c.timeout > 0 {
		return c.timeout
	}
	return DefaultCallTimeout
}

// decodeReceipt decodes a provider's JSON reply.
//
// The reply must be exactly one JSON document. A provider that prints a log line
// before its JSON would otherwise be read as a malformed receipt, so the error
// names the actual output instead of only reporting a syntax failure.
func decodeReceipt(output string, target any) error {
	trimmed := strings.TrimSpace(output)
	if trimmed == "" {
		return fmt.Errorf("no output: the provider must write one JSON document to stdout")
	}
	if err := json.Unmarshal([]byte(trimmed), target); err != nil {
		return fmt.Errorf("invalid JSON reply %q: %w", trimmed, err)
	}
	return nil
}
