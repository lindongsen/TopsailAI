// Package providerconformance validates a Provider CLI executable without
// starting an Endpoint, Server, channel or Cluster database.
package providerconformance

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"os/exec"
	"sync"
	"time"

	"topsailai_agent_cluster/internal/providercli"
)

const cleanupWait = 2 * time.Second

// Config contains local-only invocation configuration for one Provider CLI.
type Config struct {
	Executable     string
	Environment    []string
	Timeout        time.Duration
	MaxStdinBytes  int64
	MaxStdoutBytes int64
	MaxStderrBytes int64
	MaxRecords     int64
}

// Invocation captures one bounded Provider CLI process result.
type Invocation struct {
	Stdout          []byte
	Stderr          []byte
	StderrTruncated bool
	ExitCode        int
}

// Runner directly invokes one locally configured Provider CLI executable.
type Runner struct {
	config Config
}

// NewRunner validates local conformance invocation configuration.
func NewRunner(config Config) (*Runner, error) {
	if config.Executable == "" {
		return nil, errors.New("provider executable is required")
	}
	if config.Timeout <= 0 {
		return nil, errors.New("provider timeout must be positive")
	}
	if config.MaxStdinBytes < 1 || config.MaxStdoutBytes < 1 || config.MaxStderrBytes < 1 || config.MaxRecords < 1 {
		return nil, errors.New("provider input, output and record limits must be positive")
	}
	return &Runner{config: config}, nil
}

// Invoke executes one unary Provider CLI request and validates its response.
func (r *Runner) Invoke(parent context.Context, request providercli.Request) (providercli.Response, Invocation, error) {
	if err := request.Validate(); err != nil {
		return providercli.Response{}, Invocation{}, fmt.Errorf("validate request: %w", err)
	}
	invocation, err := r.invoke(parent, request)
	if err != nil {
		return providercli.Response{}, invocation, err
	}
	response, err := providercli.DecodeResponse(invocation.Stdout)
	if err != nil {
		return providercli.Response{}, invocation, fmt.Errorf("provider protocol response: %w", err)
	}
	if err := providercli.ValidateResponseCorrelation(request, response); err != nil {
		return providercli.Response{}, invocation, err
	}
	if invocation.ExitCode != 0 {
		return providercli.Response{}, invocation, fmt.Errorf("provider exit/result conflict: exit code %d with valid response", invocation.ExitCode)
	}
	return response, invocation, nil
}

// InvokeStream executes one streaming Provider CLI request and validates every frame.
func (r *Runner) InvokeStream(parent context.Context, request providercli.Request) ([]providercli.StreamFrame, Invocation, error) {
	if err := request.Validate(); err != nil {
		return nil, Invocation{}, fmt.Errorf("validate request: %w", err)
	}
	invocation, err := r.invoke(parent, request)
	if err != nil {
		return nil, invocation, err
	}
	if invocation.ExitCode != 0 {
		return nil, invocation, fmt.Errorf("provider stream exited with code %d", invocation.ExitCode)
	}
	validator, err := providercli.NewStreamValidator(request.RequestID)
	if err != nil {
		return nil, invocation, err
	}
	lines := bytes.Split(bytes.TrimSpace(invocation.Stdout), []byte("\n"))
	if len(lines) == 1 && len(lines[0]) == 0 {
		return nil, invocation, errors.New("provider stream returned no frames")
	}
	if int64(len(lines)) > r.config.MaxRecords {
		return nil, invocation, fmt.Errorf("provider stream record limit exceeded: %d > %d", len(lines), r.config.MaxRecords)
	}
	frames := make([]providercli.StreamFrame, 0, len(lines))
	for _, line := range lines {
		frame, decodeErr := providercli.DecodeStreamFrame(line)
		if decodeErr != nil {
			return nil, invocation, fmt.Errorf("provider stream frame: %w", decodeErr)
		}
		if acceptErr := validator.Accept(frame); acceptErr != nil {
			return nil, invocation, acceptErr
		}
		frames = append(frames, frame)
	}
	if err := validator.Finish(); err != nil {
		return nil, invocation, err
	}
	return frames, invocation, nil
}

// invoke encodes one validated request before entering the bounded process path.
func (r *Runner) invoke(parent context.Context, request providercli.Request) (Invocation, error) {
	encoded, err := json.Marshal(request)
	if err != nil {
		return Invocation{}, fmt.Errorf("encode provider request: %w", err)
	}
	return r.invokeDocument(parent, encoded)
}

// invokeDocument sends one already encoded document through the bounded process path.
func (r *Runner) invokeDocument(parent context.Context, document []byte) (Invocation, error) {
	if int64(len(document)) > r.config.MaxStdinBytes {
		return Invocation{}, fmt.Errorf("provider stdin byte limit exceeded: %d > %d", len(document), r.config.MaxStdinBytes)
	}
	ctx, cancel := context.WithTimeout(parent, r.config.Timeout)
	defer cancel()

	command := exec.Command(r.config.Executable)
	command.Env = append([]string(nil), r.config.Environment...)
	command.Stdin = bytes.NewReader(document)
	configureProcessGroup(command)
	stdout := newBoundedBuffer(r.config.MaxStdoutBytes)
	stderr := newBoundedBuffer(r.config.MaxStderrBytes)
	command.Stdout = stdout
	command.Stderr = stderr
	if err := command.Start(); err != nil {
		return Invocation{}, fmt.Errorf("start provider executable: %w", err)
	}

	waited := make(chan error, 1)
	go func() { waited <- command.Wait() }()
	var waitErr error
	select {
	case waitErr = <-waited:
	case <-ctx.Done():
		_ = killProcessGroup(command)
		select {
		case waitErr = <-waited:
		case <-time.After(cleanupWait):
			return invocationFrom(command, stdout, stderr), fmt.Errorf("provider process did not exit after cancellation: %w", ctx.Err())
		}
		if err := waitForProcessGroupExit(command, cleanupWait); err != nil {
			return invocationFrom(command, stdout, stderr), fmt.Errorf("provider process group cleanup: %w", err)
		}
		return invocationFrom(command, stdout, stderr), fmt.Errorf("provider invocation deadline: %w", ctx.Err())
	}

	invocation := invocationFrom(command, stdout, stderr)
	if stdout.Exceeded() {
		_ = killProcessGroup(command)
		if err := waitForProcessGroupExit(command, cleanupWait); err != nil {
			return invocation, fmt.Errorf("provider stdout overflow cleanup: %w", err)
		}
		return invocation, fmt.Errorf("provider stdout byte limit exceeded: %d", r.config.MaxStdoutBytes)
	}
	if processGroupAlive(command) {
		_ = killProcessGroup(command)
		if err := waitForProcessGroupExit(command, cleanupWait); err != nil {
			return invocation, fmt.Errorf("provider invocation helper cleanup: %w", err)
		}
		return invocation, errors.New("provider invocation helper leaked after completion")
	}
	if waitErr != nil {
		var exitError *exec.ExitError
		if !errors.As(waitErr, &exitError) {
			return invocation, fmt.Errorf("wait for provider executable: %w", waitErr)
		}
	}
	return invocation, nil
}

// invocationFrom snapshots the bounded process result after wait or cleanup.
func invocationFrom(command *exec.Cmd, stdout, stderr *boundedBuffer) Invocation {
	exitCode := 0
	if command.ProcessState != nil {
		exitCode = command.ProcessState.ExitCode()
	}
	return Invocation{
		Stdout:          stdout.Bytes(),
		Stderr:          stderr.Bytes(),
		StderrTruncated: stderr.Exceeded(),
		ExitCode:        exitCode,
	}
}

type boundedBuffer struct {
	mu       sync.Mutex
	limit    int64
	data     bytes.Buffer
	exceeded bool
}

// newBoundedBuffer creates a prefix-preserving bounded writer.
func newBoundedBuffer(limit int64) *boundedBuffer {
	return &boundedBuffer{limit: limit}
}

// Write keeps the bounded prefix while reporting the full input as consumed.
func (b *boundedBuffer) Write(value []byte) (int, error) {
	b.mu.Lock()
	defer b.mu.Unlock()
	remaining := b.limit - int64(b.data.Len())
	if remaining <= 0 {
		b.exceeded = true
		return len(value), nil
	}
	kept := value
	if int64(len(kept)) > remaining {
		kept = kept[:remaining]
		b.exceeded = true
	}
	_, _ = b.data.Write(kept)
	return len(value), nil
}

// Bytes returns a detached copy of the retained prefix.
func (b *boundedBuffer) Bytes() []byte {
	b.mu.Lock()
	defer b.mu.Unlock()
	return append([]byte(nil), b.data.Bytes()...)
}

// Exceeded reports whether input was discarded after reaching the limit.
func (b *boundedBuffer) Exceeded() bool {
	b.mu.Lock()
	defer b.mu.Unlock()
	return b.exceeded
}
