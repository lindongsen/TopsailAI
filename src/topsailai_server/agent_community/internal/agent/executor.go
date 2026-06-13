// Package agent provides agent command execution and interface parsing.
package agent

import (
	"bytes"
	"context"
	"fmt"
	"os/exec"
	"time"

	"github.com/topsailai/agent-community/pkg/logger"
)

const executorModule = "executor"

// ExecutionResult holds the result of an agent command execution.
type ExecutionResult struct {
	ExitCode int    `json:"exit_code"`
	Stdout   string `json:"stdout"`
	Stderr   string `json:"stderr"`
	Duration int64  `json:"duration_ms"`
}

// Executor executes agent commands.
type Executor struct{}

// NewExecutor creates a new agent executor.
func NewExecutor() *Executor {
	return &Executor{}
}

// CheckHealth checks if the agent is healthy by executing the health check command.
func (e *Executor) CheckHealth(ctx context.Context, iface *Interface, env map[string]string, traceID string) (*ExecutionResult, error) {
	return e.execute(ctx, iface.CmdCheckHealth, env, iface.TimeoutCheckHealth, traceID)
}

// CheckStatus checks the agent's current status.
func (e *Executor) CheckStatus(ctx context.Context, iface *Interface, env map[string]string, traceID string) (*ExecutionResult, error) {
	return e.execute(ctx, iface.CmdCheckStatus, env, iface.TimeoutCheckStatus, traceID)
}

// Chat sends a message to the agent and returns the response.
func (e *Executor) Chat(ctx context.Context, iface *Interface, env map[string]string, traceID string) (*ExecutionResult, error) {
	return e.execute(ctx, iface.CmdChat, env, iface.TimeoutChat, traceID)
}

// execute runs a command with the given environment variables and timeout.
func (e *Executor) execute(
	ctx context.Context,
	cmd string,
	env map[string]string,
	timeout time.Duration,
	traceID string,
) (*ExecutionResult, error) {
	if cmd == "" {
		return nil, fmt.Errorf("command is empty")
	}

	start := time.Now()

	// Create context with timeout
	execCtx, cancel := context.WithTimeout(ctx, timeout)
	defer cancel()

	// Build command
	command := exec.CommandContext(execCtx, "sh", "-c", cmd)

	// Set environment variables
	command.Env = append(command.Environ(), ToEnvSlice(env)...)

	// Capture stdout and stderr
	var stdoutBuf, stderrBuf bytes.Buffer
	command.Stdout = &stdoutBuf
	command.Stderr = &stderrBuf

	logger.InfoM(executorModule, traceID, "executing agent command",
		"cmd", cmd,
		"timeout", timeout.String(),
	)

	// Run command
	err := command.Run()

	duration := time.Since(start).Milliseconds()
	result := &ExecutionResult{
		Stdout:   stdoutBuf.String(),
		Stderr:   stderrBuf.String(),
		Duration: duration,
	}

	if err != nil {
		if exitErr, ok := err.(*exec.ExitError); ok {
			result.ExitCode = exitErr.ExitCode()
		} else if execCtx.Err() == context.DeadlineExceeded {
			result.ExitCode = -1
			logger.ErrorM(executorModule, traceID, "agent command timed out",
				"cmd", cmd,
				"timeout", timeout.String(),
			)
			return result, fmt.Errorf("command timed out after %v: %w", timeout, err)
		} else {
			result.ExitCode = -1
		}
		logger.ErrorM(executorModule, traceID, "agent command failed",
			"cmd", cmd,
			"exit_code", result.ExitCode,
			"stderr", result.Stderr,
		)
		return result, fmt.Errorf("command failed with exit code %d: %w", result.ExitCode, err)
	}

	result.ExitCode = 0
	logger.InfoM(executorModule, traceID, "agent command completed",
		"cmd", cmd,
		"duration_ms", duration,
		"stdout_len", len(result.Stdout),
		"stderr_len", len(result.Stderr),
	)

	return result, nil
}

// IsHealthy checks if the execution result indicates a healthy agent.
func (r *ExecutionResult) IsHealthy() bool {
	return r.ExitCode == 0
}

// GetStatus parses the status from a check_status command result.
// Returns the status string and any error.
func (r *ExecutionResult) GetStatus() (string, error) {
	if r.ExitCode != 0 {
		return "", fmt.Errorf("status check failed with exit code %d", r.ExitCode)
	}
	// Trim whitespace from stdout to get status
	status := bytes.TrimSpace([]byte(r.Stdout))
	return string(status), nil
}
