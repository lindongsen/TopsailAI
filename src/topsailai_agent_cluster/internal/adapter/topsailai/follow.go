package topsailai

import (
	"bufio"
	"context"
	"errors"
	"fmt"
	"os"
	"os/exec"
	"strings"
	"time"

	"topsailai_agent_cluster/internal/adapter"
)

// followMaxLineBytes bounds one followed record. A provider that writes a longer
// line is truncated and labelled rather than buffered without limit, because an
// unbounded line would let one provider record exhaust Endpoint memory.
const followMaxLineBytes = 64 << 10

// followWaitDelay bounds how long Wait blocks after cancellation, so a
// grandchild that inherited the pipe cannot keep the Endpoint waiting forever.
const followWaitDelay = 5 * time.Second

// followRunner streams provider output records as they are written.
type followRunner interface {
	Follow(context.Context, string, []string, func(string) error) error
}

// execFollowRunner runs one provider follow command and delivers complete lines.
type execFollowRunner struct {
	timeout time.Duration
}

// Follow starts the provider follow command and calls emit once per complete
// record.
//
// The child environment sets PYTHONUNBUFFERED so records arrive as they are
// written. Without it the provider buffers stdout when it is not attached to a
// terminal, so a follow would deliver nothing until the process exited and the
// operator would see an empty screen instead of a live stream. The provider CLI
// is launched through "uv run", which does not add the variable itself.
//
// The provider rejects --json together with --follow, so the caller passes plain
// text arguments and this runner never parses a document.
func (r execFollowRunner) Follow(parent context.Context, executable string, args []string, emit func(string) error) error {
	timeout := r.timeout
	if timeout <= 0 {
		timeout = defaultTimeout
	}
	ctx, cancel := context.WithTimeout(parent, timeout)
	defer cancel()
	cmd := exec.CommandContext(ctx, executable, args...)
	cmd.Env = followEnvironment(executable, os.Environ())
	configureProcessGroup(cmd)
	cmd.Cancel = func() error { return killProcessGroup(cmd) }
	cmd.WaitDelay = followWaitDelay
	stdout, err := cmd.StdoutPipe()
	if err != nil {
		return fmt.Errorf("prepare follow stdout: %w", err)
	}
	if err := cmd.Start(); err != nil {
		return fmt.Errorf("start follow command: %w", err)
	}
	readErr := scanFollowLines(stdout, emit)
	if readErr != nil && !errors.Is(readErr, adapter.ErrFollowStopped) {
		// A consumer that stopped on purpose still needs the child reaped, so
		// termination is requested and the wait below still runs.
		_ = killProcessGroup(cmd)
	}
	waitErr := cmd.Wait()
	if readErr != nil {
		return readErr
	}
	if waitErr != nil {
		if ctx.Err() != nil {
			return ctx.Err()
		}
		return fmt.Errorf("follow command failed: %w", waitErr)
	}
	return nil
}

// scanFollowLines delivers complete newline-terminated records and holds the
// unterminated remainder until the stream ends, so a consumer never receives a
// partial line as if it were complete.
func scanFollowLines(reader interface{ Read([]byte) (int, error) }, emit func(string) error) error {
	scanner := bufio.NewScanner(reader)
	scanner.Buffer(make([]byte, 0, 64<<10), followMaxLineBytes)
	for scanner.Scan() {
		if err := emit(scanner.Text()); err != nil {
			return err
		}
	}
	if err := scanner.Err(); err != nil {
		return fmt.Errorf("read follow output: %w", err)
	}
	return nil
}

// followEnvironment returns base with PYTHONUNBUFFERED set and the provider
// executable's own directory first on PATH.
//
// PYTHONUNBUFFERED is set unconditionally rather than only when absent: an
// inherited empty or "0" value would silently restore buffering and turn a live
// follow into a stream that only appears at exit.
func followEnvironment(executable string, base []string) []string {
	environment := make([]string, 0, len(base)+2)
	for _, entry := range base {
		if strings.HasPrefix(entry, "PYTHONUNBUFFERED=") {
			continue
		}
		environment = append(environment, entry)
	}
	environment = append(environment, "PYTHONUNBUFFERED=1")
	return providerEnvironment(executable, environment)
}
