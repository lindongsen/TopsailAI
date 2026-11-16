package genericcli

import (
	"bufio"
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"os/exec"
	"sync"
	"time"

	"topsailai_agent_cluster/internal/providercli"
)

const processCleanupWait = 2 * time.Second

// runnerConfig is local Endpoint configuration and is never populated from a request.
type runnerConfig struct {
	executable     string
	args           []string
	environment    []string
	timeout        time.Duration
	maxStdinBytes  int64
	maxStdoutBytes int64
	maxStderrBytes int64
	maxRecords     int64
}

// processRunner invokes one locally configured Provider CLI executable.
type processRunner struct {
	config runnerConfig
}

// newProcessRunner validates bounded local process configuration.
func newProcessRunner(config runnerConfig) (*processRunner, error) {
	if config.executable == "" {
		return nil, errors.New("provider executable is required")
	}
	if config.timeout <= 0 {
		return nil, errors.New("provider timeout must be positive")
	}
	if config.maxStdinBytes < 1 || config.maxStdoutBytes < 1 || config.maxStderrBytes < 1 || config.maxRecords < 1 {
		return nil, errors.New("provider input, output and record limits must be positive")
	}
	return &processRunner{config: config}, nil
}

// invoke executes one unary Provider CLI request and validates its response.
func (r *processRunner) invoke(parent context.Context, request providercli.Request) (providercli.Response, error) {
	if err := request.Validate(); err != nil {
		return providercli.Response{}, fmt.Errorf("validate provider request: %w", err)
	}
	document, err := json.Marshal(request)
	if err != nil {
		return providercli.Response{}, fmt.Errorf("encode provider request: %w", err)
	}
	if int64(len(document)) > r.config.maxStdinBytes {
		return providercli.Response{}, fmt.Errorf("provider stdin byte limit exceeded: %d > %d", len(document), r.config.maxStdinBytes)
	}
	ctx, cancel := invocationContext(parent, r.config.timeout, request.DeadlineAtMS)
	defer cancel()
	command := r.command(ctx)
	command.Stdin = bytes.NewReader(document)
	stdout := newBoundedBuffer(r.config.maxStdoutBytes)
	stderr := newBoundedBuffer(r.config.maxStderrBytes)
	command.Stdout = stdout
	command.Stderr = stderr
	waitErr, runErr := runOwnedProcess(ctx, command)
	if runErr != nil {
		return providercli.Response{}, runErr
	}
	if stdout.exceededLimit() {
		return providercli.Response{}, fmt.Errorf("provider stdout byte limit exceeded: %d", r.config.maxStdoutBytes)
	}
	response, decodeErr := providercli.DecodeResponse(stdout.bytes())
	if decodeErr != nil {
		return providercli.Response{}, providerFailure("decode provider response", decodeErr, stderr)
	}
	if correlationErr := providercli.ValidateResponseCorrelation(request, response); correlationErr != nil {
		return providercli.Response{}, correlationErr
	}
	if waitErr == nil {
		return response, nil
	}
	failure := providerFailure("wait for provider executable", waitErr, stderr)
	var exitError *exec.ExitError
	if errors.As(waitErr, &exitError) {
		failure = providerFailure(fmt.Sprintf("provider exit code %d", exitError.ExitCode()), waitErr, stderr)
	}
	if !response.OK {
		return response, &invocationError{response: response, cause: failure}
	}
	return providercli.Response{}, fmt.Errorf("provider process/result conflict with unknown effect: %w", failure)
}

// invokeStream executes a streaming request and forwards validated record frames as they arrive.
func (r *processRunner) invokeStream(parent context.Context, request providercli.Request, accept func(providercli.StreamFrame) error) error {
	if err := request.Validate(); err != nil {
		return fmt.Errorf("validate provider request: %w", err)
	}
	if accept == nil {
		return errors.New("provider stream callback is required")
	}
	document, err := json.Marshal(request)
	if err != nil {
		return fmt.Errorf("encode provider request: %w", err)
	}
	if int64(len(document)) > r.config.maxStdinBytes {
		return fmt.Errorf("provider stdin byte limit exceeded: %d > %d", len(document), r.config.maxStdinBytes)
	}
	ctx, cancel := invocationContext(parent, r.config.timeout, request.DeadlineAtMS)
	defer cancel()
	command := r.command(ctx)
	command.Stdin = bytes.NewReader(document)
	stdout, err := command.StdoutPipe()
	if err != nil {
		return fmt.Errorf("prepare provider stdout: %w", err)
	}
	stderrPipe, err := command.StderrPipe()
	if err != nil {
		return fmt.Errorf("prepare provider stderr: %w", err)
	}
	stderr := newBoundedBuffer(r.config.maxStderrBytes)
	if err := command.Start(); err != nil {
		return fmt.Errorf("start provider executable: %w", err)
	}
	stderrDone := make(chan struct{})
	go func() {
		_, _ = io.Copy(stderr, stderrPipe)
		close(stderrDone)
	}()
	validator, err := providercli.NewStreamValidator(request.RequestID)
	if err != nil {
		_ = killProcessGroup(command)
		_ = command.Wait()
		<-stderrDone
		return err
	}
	scanErr := r.scanStream(stdout, validator, accept)
	if scanErr != nil {
		_ = killProcessGroup(command)
	}
	waitErr := waitOwnedProcess(ctx, command)
	<-stderrDone
	if scanErr != nil {
		var callback *callbackError
		if errors.As(scanErr, &callback) {
			return callback.cause
		}
		return providerFailure("provider stream", scanErr, stderr)
	}
	// A deadline or cancellation kills the process group, so the stream ends at
	// EOF without a terminal frame and Finish reports a truncated stream. That
	// truncation is the consequence of the stop, not a provider fault, so the
	// context error is returned instead: the caller classifies a stopped stream
	// as cancelled and only a stream that ended on its own as a provider failure.
	// Checking Finish first reported every timeout as provider_error, which made a
	// follow held past the configured timeout look like a broken provider.
	if ctxErr := ctx.Err(); ctxErr != nil {
		return providerFailure("provider stream", ctxErr, stderr)
	}
	if finishErr := validator.Finish(); finishErr != nil {
		return providerFailure("provider stream", finishErr, stderr)
	}
	if waitErr != nil {
		return providerFailure("provider stream process", waitErr, stderr)
	}
	return nil
}

func (r *processRunner) scanStream(reader io.Reader, validator *providercli.StreamValidator, accept func(providercli.StreamFrame) error) error {
	scanner := bufio.NewScanner(reader)
	maxLine := r.config.maxStdoutBytes
	if maxLine > int64(maxInt()) {
		maxLine = int64(maxInt())
	}
	scanner.Buffer(make([]byte, 64<<10), int(maxLine)+1)
	var records int64
	var total int64
	for scanner.Scan() {
		line := append([]byte(nil), scanner.Bytes()...)
		total += int64(len(line)) + 1
		if total > r.config.maxStdoutBytes {
			return fmt.Errorf("provider stdout byte limit exceeded: %d", r.config.maxStdoutBytes)
		}
		frame, err := providercli.DecodeStreamFrame(line)
		if err != nil {
			return fmt.Errorf("decode stream frame: %w", err)
		}
		if err := validator.Accept(frame); err != nil {
			return err
		}
		if frame.Type == providercli.FrameRecord {
			records++
			if records > r.config.maxRecords {
				return fmt.Errorf("provider stream record limit exceeded: %d", r.config.maxRecords)
			}
		}
		if err := accept(frame); err != nil {
			return &callbackError{cause: err}
		}
	}
	if err := scanner.Err(); err != nil {
		return fmt.Errorf("read provider stream: %w", err)
	}
	return nil
}

func (r *processRunner) command(ctx context.Context) *exec.Cmd {
	command := exec.CommandContext(ctx, r.config.executable, r.config.args...)
	command.Env = append([]string(nil), r.config.environment...)
	configureProcessGroup(command)
	command.Cancel = func() error { return killProcessGroup(command) }
	command.WaitDelay = processCleanupWait
	return command
}

func invocationContext(parent context.Context, configured time.Duration, deadlineAtMS int64) (context.Context, context.CancelFunc) {
	budget := configured
	if deadlineAtMS > 0 {
		remaining := time.Until(time.UnixMilli(deadlineAtMS))
		if remaining < budget {
			budget = remaining
		}
	}
	if budget <= 0 {
		budget = time.Nanosecond
	}
	return context.WithTimeout(parent, budget)
}

func runOwnedProcess(ctx context.Context, command *exec.Cmd) (error, error) {
	if err := command.Start(); err != nil {
		return nil, fmt.Errorf("start provider executable: %w", err)
	}
	waitErr := waitOwnedProcess(ctx, command)
	if ctx.Err() != nil {
		return waitErr, fmt.Errorf("provider invocation deadline: %w", ctx.Err())
	}
	if processGroupAlive(command) {
		_ = killProcessGroup(command)
		if err := waitForProcessGroupExit(command, processCleanupWait); err != nil {
			return waitErr, fmt.Errorf("provider helper cleanup: %w", err)
		}
		return waitErr, errors.New("provider helper process leaked after completion")
	}
	return waitErr, nil
}

func waitOwnedProcess(ctx context.Context, command *exec.Cmd) error {
	waited := make(chan error, 1)
	go func() { waited <- command.Wait() }()
	select {
	case err := <-waited:
		return err
	case <-ctx.Done():
		_ = killProcessGroup(command)
		select {
		case err := <-waited:
			_ = waitForProcessGroupExit(command, processCleanupWait)
			return fmt.Errorf("provider invocation cancelled: %w: %v", ctx.Err(), err)
		case <-time.After(processCleanupWait):
			return fmt.Errorf("provider process did not exit after cancellation: %w", ctx.Err())
		}
	}
}

func providerFailure(label string, cause error, stderr *boundedBuffer) error {
	message := string(stderr.bytes())
	if stderr.exceededLimit() {
		message += " [truncated]"
	}
	if message == "" {
		return fmt.Errorf("%s: %w", label, cause)
	}
	return fmt.Errorf("%s: %w: stderr=%q", label, cause, message)
}

type boundedBuffer struct {
	mu       sync.Mutex
	limit    int64
	data     bytes.Buffer
	exceeded bool
}

func newBoundedBuffer(limit int64) *boundedBuffer {
	return &boundedBuffer{limit: limit}
}

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

func (b *boundedBuffer) bytes() []byte {
	b.mu.Lock()
	defer b.mu.Unlock()
	return append([]byte(nil), b.data.Bytes()...)
}

func (b *boundedBuffer) exceededLimit() bool {
	b.mu.Lock()
	defer b.mu.Unlock()
	return b.exceeded
}

func maxInt() int {
	return int(^uint(0) >> 1)
}
