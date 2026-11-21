// Package runner executes one task run as a child process.
//
// A run is launched in its own process group so a timeout or a shutdown can
// terminate the whole tree. Killing only the direct child would leave any
// grandchildren running as orphans, and those orphans would keep the task's
// lock alive after the scheduler believed the run had ended.
package runner

import (
	"bytes"
	"context"
	"errors"
	"fmt"
	"os"
	"os/exec"
	"strings"
	"syscall"
	"time"
)

// Request describes one run to execute.
type Request struct {
	// Command is the executable to start.
	Command string
	// Args are the arguments passed to the command.
	Args []string
	// Dir is the working directory. Empty means the scheduler's own directory.
	Dir string
	// Env is the complete environment for the child. Nil means inherit.
	Env []string
	// Timeout bounds the run. Zero means no timeout.
	Timeout time.Duration
	// Stdin is written to the child's standard input. Empty means no input.
	// Passing a request document this way keeps a value containing spaces or
	// shell metacharacters out of the argument list.
	Stdin string
	// MaxOutputBytes caps how much combined output is retained. Zero means the
	// default cap. Output beyond the cap is dropped and flagged as truncated.
	MaxOutputBytes int
	// OnStart is called once the child has started, with its process id. It lets
	// a caller record the run and stop it later without knowing how the child
	// was launched. It must not block.
	OnStart func(pid int)
	// SeparateStreams keeps stdout and stderr in separate buffers instead of one
	// combined buffer. A caller that parses the child's stdout as a document
	// needs this: a diagnostic line on stderr would otherwise be interleaved
	// into the document and make it unreadable.
	SeparateStreams bool
}

// Result is the outcome of one run.
type Result struct {
	// ExitCode is the child's exit status. It is -1 when the child did not exit
	// normally, for example when it was killed by a signal.
	ExitCode int
	// TimedOut is true when the run was stopped because it exceeded its timeout.
	TimedOut bool
	// Canceled is true when the run was stopped because the context ended.
	Canceled bool
	// Output is the retained combined stdout and stderr.
	Output string
	// Stdout is the retained standard output when the request asked for separate
	// streams. It is empty otherwise.
	Stdout string
	// Stderr is the retained standard error when the request asked for separate
	// streams. It is empty otherwise.
	Stderr string
	// Truncated is true when output exceeded the cap and was cut.
	Truncated bool
	// Duration is the wall-clock time the run took.
	Duration time.Duration
	// Err is the launch or wait error, nil for a normal non-zero exit.
	Err error
}

// DefaultMaxOutputBytes is the retained output cap when a request sets none.
const DefaultMaxOutputBytes = 64 * 1024

// killGrace is how long a stopped run gets to exit after SIGTERM before the
// whole process group is killed outright.
const killGrace = 5 * time.Second

// Run executes the request and waits for it to finish.
//
// A non-zero exit status is reported through Result.ExitCode and is not an
// error: a task that fails is a normal outcome the scheduler records. Result.Err
// is reserved for a failure to launch or to wait for the child.
func Run(ctx context.Context, request Request) Result {
	started := time.Now()

	if strings.TrimSpace(request.Command) == "" {
		return Result{ExitCode: -1, Err: errors.New("command is empty")}
	}

	runCtx := ctx
	var cancel context.CancelFunc
	if request.Timeout > 0 {
		runCtx, cancel = context.WithTimeout(ctx, request.Timeout)
		defer cancel()
	}

	command := exec.Command(request.Command, request.Args...)
	command.Dir = request.Dir
	command.Env = request.Env
	// A dedicated process group lets the whole tree be signalled at once.
	command.SysProcAttr = &syscall.SysProcAttr{Setpgid: true}

	limit := positiveOr(request.MaxOutputBytes, DefaultMaxOutputBytes)
	output := &cappedBuffer{limit: limit}
	var stdout, stderr *cappedBuffer
	if request.SeparateStreams {
		stdout = &cappedBuffer{limit: limit}
		stderr = &cappedBuffer{limit: limit}
		command.Stdout = stdout
		command.Stderr = stderr
	} else {
		command.Stdout = output
		command.Stderr = output
	}
	if request.Stdin != "" {
		command.Stdin = strings.NewReader(request.Stdin)
	}

	if err := command.Start(); err != nil {
		return Result{
			ExitCode: -1,
			Duration: time.Since(started),
			Err:      fmt.Errorf("start %q: %w", request.Command, err),
		}
	}
	if request.OnStart != nil {
		request.OnStart(command.Process.Pid)
	}

	waited := make(chan error, 1)
	go func() { waited <- command.Wait() }()

	var waitErr error
	select {
	case waitErr = <-waited:
	case <-runCtx.Done():
		// Stop the whole group, then give it a short grace period to exit
		// cleanly before killing it.
		terminateGroup(command.Process.Pid)
		select {
		case waitErr = <-waited:
		case <-time.After(killGrace):
			killGroup(command.Process.Pid)
			waitErr = <-waited
		}
	}

	result := Result{
		ExitCode:  exitCode(command, waitErr),
		Output:    output.String(),
		Truncated: output.truncated,
		Duration:  time.Since(started),
	}
	if request.SeparateStreams {
		result.Stdout = stdout.String()
		result.Stderr = stderr.String()
		result.Truncated = stdout.truncated || stderr.truncated
	}
	if runCtx.Err() != nil {
		if errors.Is(runCtx.Err(), context.DeadlineExceeded) {
			result.TimedOut = true
		} else {
			result.Canceled = true
		}
	}
	if waitErr != nil && result.ExitCode == -1 && !result.TimedOut && !result.Canceled {
		result.Err = fmt.Errorf("wait for %q: %w", request.Command, waitErr)
	}
	return result
}

// exitCode extracts the child's exit status from a wait error.
func exitCode(command *exec.Cmd, waitErr error) int {
	if command.ProcessState != nil {
		return command.ProcessState.ExitCode()
	}
	if waitErr == nil {
		return 0
	}
	var exitErr *exec.ExitError
	if errors.As(waitErr, &exitErr) {
		return exitErr.ExitCode()
	}
	return -1
}

// terminateGroup sends SIGTERM to the process group led by pid.
func terminateGroup(pid int) {
	if pid <= 0 {
		return
	}
	// A negative pid addresses the whole process group.
	_ = syscall.Kill(-pid, syscall.SIGTERM)
}

// killGroup sends SIGKILL to the process group led by pid.
func killGroup(pid int) {
	if pid <= 0 {
		return
	}
	_ = syscall.Kill(-pid, syscall.SIGKILL)
}

// Stop terminates the process group led by pid.
//
// It is the counterpart of Request.OnStart: a caller that recorded the pid can
// stop the run without knowing which launcher produced it. The whole group is
// signalled, so children of the run are terminated too and cannot survive as
// orphans holding the task lock.
//
// force sends SIGKILL immediately instead of SIGTERM. A graceful stop lets the
// child clean up; a forced stop is for a run that ignored the first signal.
func Stop(pid int, force bool) error {
	if pid <= 0 {
		return fmt.Errorf("invalid process id %d", pid)
	}
	if force {
		killGroup(pid)
		return nil
	}
	terminateGroup(pid)
	return nil
}

// positiveOr returns value when it is positive, otherwise fallback.
func positiveOr(value, fallback int) int {
	if value > 0 {
		return value
	}
	return fallback
}

// cappedBuffer keeps at most limit bytes and records whether it dropped any.
//
// It is written by the child's stdout and stderr through the same os/exec
// writer, which serialises writes, so no extra locking is needed.
type cappedBuffer struct {
	buffer    bytes.Buffer
	limit     int
	truncated bool
}

// Write appends as much of p as fits within the limit.
func (c *cappedBuffer) Write(p []byte) (int, error) {
	remaining := c.limit - c.buffer.Len()
	if remaining <= 0 {
		c.truncated = true
		return len(p), nil
	}
	if len(p) > remaining {
		c.truncated = true
		c.buffer.Write(p[:remaining])
		return len(p), nil
	}
	c.buffer.Write(p)
	return len(p), nil
}

// String returns the retained output.
func (c *cappedBuffer) String() string {
	return c.buffer.String()
}

// BuildEnv merges extra variables into a base environment.
//
// Later entries win in a child's environment, so extras are appended after the
// base. A key present in both is removed from the base first, which keeps the
// child's environment free of duplicates that make debugging confusing.
func BuildEnv(base []string, extras map[string]string) []string {
	if len(extras) == 0 {
		return base
	}
	merged := make([]string, 0, len(base)+len(extras))
	for _, entry := range base {
		key, _, found := strings.Cut(entry, "=")
		if found {
			if _, overridden := extras[key]; overridden {
				continue
			}
		}
		merged = append(merged, entry)
	}
	for key, value := range extras {
		merged = append(merged, key+"="+value)
	}
	return merged
}

// CurrentEnv returns the scheduler's own environment.
func CurrentEnv() []string {
	return os.Environ()
}
