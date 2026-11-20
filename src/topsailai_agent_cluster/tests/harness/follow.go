package harness

import (
	"bytes"
	"context"
	"errors"
	"fmt"
	"io"
	"os"
	"os/exec"
	"strings"
	"sync"
	"syscall"
	"time"
)

// syncBuffer is a writer that a test goroutine can read while the child process
// is still writing. A plain bytes.Buffer would race with the copy goroutine that
// exec starts for a non-file stdout.
type syncBuffer struct {
	mu     sync.Mutex
	buffer bytes.Buffer
}

// Write appends one chunk under the lock.
func (s *syncBuffer) Write(payload []byte) (int, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	return s.buffer.Write(payload)
}

// String returns everything written so far under the lock.
func (s *syncBuffer) String() string {
	s.mu.Lock()
	defer s.mu.Unlock()
	return s.buffer.String()
}

// pacedReader delivers scripted terminal input in chunks separated by a pause.
//
// A follow stream only produces records while the editor is polling, so a script
// that arrives in one burst would be stopped before the first record is written.
// Pacing the input lets the stream run for a bounded time before the keypress
// that stops it, which is what an operator does.
type pacedReader struct {
	chunks []string
	pause  time.Duration
	index  int
	buffer []byte
}

// Read returns the next chunk, pausing before every chunk after the first.
func (r *pacedReader) Read(payload []byte) (int, error) {
	if len(r.buffer) == 0 {
		if r.index >= len(r.chunks) {
			return 0, io.EOF
		}
		if r.index > 0 {
			time.Sleep(r.pause)
		}
		r.buffer = []byte(r.chunks[r.index])
		r.index++
	}
	written := copy(payload, r.buffer)
	r.buffer = r.buffer[written:]
	return written, nil
}

// RunTUIInteractiveEditorPaced drives the REPL through a PTY with a real TERM,
// delivering the scripted input in chunks separated by a pause. The raw-mode
// editor is active, so a keypress stops an armed follow stream.
func (c *Cluster) RunTUIInteractiveEditorPaced(chunks []string, pause time.Duration, args ...string) (stdout string, stderr string, exitCode int, err error) {
	return c.runTUIInteractiveWithReader(&pacedReader{chunks: chunks, pause: pause}, "xterm-256color", args...)
}

// RunTUIFollow runs one CLI command that is expected to stream, waits until the
// marker appears on stdout, then sends an interrupt so the command ends the way
// an operator ends it.
//
// The standalone surface has no terminal to observe a keypress, so an interrupt
// is its only stop signal. Waiting for the marker first proves the stream was
// live before the stop, instead of asserting on a command that never started.
func (c *Cluster) RunTUIFollow(marker string, wait time.Duration, args ...string) (stdout string, stderr string, exitCode int, err error) {
	if c.TUIPath == "" {
		return "", "", -1, fmt.Errorf("TUI binary has not been built; call BuildTUI first")
	}
	ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
	defer cancel()
	cmd := exec.CommandContext(ctx, c.TUIPath, args...)
	cmd.Dir = ModuleRootForRun()
	cmd.Env = c.cliEnvironment()
	var out, stderrBuffer syncBuffer
	cmd.Stdout = &out
	cmd.Stderr = &stderrBuffer
	if err := cmd.Start(); err != nil {
		return "", "", -1, err
	}
	if err := waitForMarker(&out, marker, wait); err != nil {
		// The stream never reached the marker, so the process is killed rather
		// than left running: a follow that never started would otherwise hold the
		// test until its own deadline.
		_ = cmd.Process.Kill()
		_ = cmd.Wait()
		return out.String(), stderrBuffer.String(), -1, err
	}
	if err := cmd.Process.Signal(os.Interrupt); err != nil {
		_ = cmd.Process.Kill()
		_ = cmd.Wait()
		return out.String(), stderrBuffer.String(), -1, fmt.Errorf("interrupt follow: %w", err)
	}
	runErr := cmd.Wait()
	if ctx.Err() != nil {
		return out.String(), stderrBuffer.String(), -1, ctx.Err()
	}
	exitCode = 0
	if runErr != nil {
		exitCode = 1
		var exitErr *exec.ExitError
		if errors.As(runErr, &exitErr) {
			exitCode = exitErr.ExitCode()
		}
	}
	return out.String(), stderrBuffer.String(), exitCode, runErr
}

// RunTUIFollowUntilEnd runs one CLI follow and waits for it to end on its own,
// without signalling it.
//
// RunTUIFollow interrupts the command once the marker appears, which is the
// operator-stop path. A scenario that must observe the stream's own terminal code
// needs the opposite: the command has to reach its bound and report it. Sending an
// interrupt there would produce the stop message and the scenario would assert on
// a code the stop path never emits.
//
// The wait budget is the caller's, because the bound under test is configuration
// and a fixed harness budget would silently cap it.
func (c *Cluster) RunTUIFollowUntilEnd(wait time.Duration, args ...string) (stdout string, stderr string, exitCode int, err error) {
	if c.TUIPath == "" {
		return "", "", -1, fmt.Errorf("TUI binary has not been built; call BuildTUI first")
	}
	ctx, cancel := context.WithTimeout(context.Background(), wait)
	defer cancel()
	cmd := exec.CommandContext(ctx, c.TUIPath, args...)
	cmd.Dir = ModuleRootForRun()
	cmd.Env = c.cliEnvironment()
	var out, stderrBuffer syncBuffer
	cmd.Stdout = &out
	cmd.Stderr = &stderrBuffer
	if err := cmd.Start(); err != nil {
		return "", "", -1, err
	}
	runErr := cmd.Wait()
	if ctx.Err() != nil {
		// The harness budget expired before the command ended, so the stream never
		// reached its own bound. Reporting the timeout as the command's result
		// would let a scenario assert on a truncated stream.
		return out.String(), stderrBuffer.String(), -1, fmt.Errorf("follow did not end within %s: %w; output=%s", wait, ctx.Err(), out.String())
	}
	exitCode = 0
	if runErr != nil {
		exitCode = 1
		var exitErr *exec.ExitError
		if errors.As(runErr, &exitErr) {
			exitCode = exitErr.ExitCode()
		}
	}
	return out.String(), stderrBuffer.String(), exitCode, runErr
}

// ProcessAlive reports whether a pid still names a running process.
//
// Signal 0 performs the permission and existence checks without delivering
// anything, so it answers "does this pid exist" without disturbing the process.
// EPERM means the process exists but belongs to another user, which is still
// alive for the purpose of a leak assertion.
func ProcessAlive(pid int) bool {
	if pid <= 0 {
		return false
	}
	err := syscall.Kill(pid, 0)
	return err == nil || errors.Is(err, syscall.EPERM)
}

// WaitProcessGone polls until the pid no longer names a running process, or the
// budget expires.
//
// A single read races the release: the Cluster kills the process group and the
// kernel reaps it asynchronously, so an immediate check can still observe the
// zombie. Polling with a deadline is the only form that distinguishes "released"
// from "not yet reaped".
func WaitProcessGone(pid int, wait time.Duration) error {
	deadline := time.Now().Add(wait)
	for time.Now().Before(deadline) {
		if !ProcessAlive(pid) {
			return nil
		}
		time.Sleep(20 * time.Millisecond)
	}
	return fmt.Errorf("provider follow process %d is still alive after %s", pid, wait)
}

// waitForMarker polls the child output until the marker appears or the budget
// expires.
func waitForMarker(out *syncBuffer, marker string, wait time.Duration) error {
	deadline := time.Now().Add(wait)
	for time.Now().Before(deadline) {
		if strings.Contains(out.String(), marker) {
			return nil
		}
		time.Sleep(20 * time.Millisecond)
	}
	return fmt.Errorf("stream marker %q was not observed before the deadline; output=%s", marker, out.String())
}

// RunTUIFollowThenStopEndpoint runs one CLI follow, waits until the marker
// appears on stdout, then stops the Endpoint so the stream is interrupted by a
// disconnect rather than by the operator.
//
// This is the only way to prove the disconnect contract end to end: an in-process
// transport cannot drop a live stream, and a follow stopped by the operator takes
// the clean path instead. The Endpoint is stopped, never killed with a signal the
// Server cannot observe, so the Server sees a real disconnect and releases the
// pending follow itself.
func (c *Cluster) RunTUIFollowThenStopEndpoint(marker string, wait time.Duration, args ...string) (stdout string, stderr string, exitCode int, err error) {
	if c.TUIPath == "" {
		return "", "", -1, fmt.Errorf("TUI binary has not been built; call BuildTUI first")
	}
	ctx, cancel := context.WithTimeout(context.Background(), 60*time.Second)
	defer cancel()
	cmd := exec.CommandContext(ctx, c.TUIPath, args...)
	cmd.Dir = ModuleRootForRun()
	cmd.Env = c.cliEnvironment()
	var out, stderrBuffer syncBuffer
	cmd.Stdout = &out
	cmd.Stderr = &stderrBuffer
	if err := cmd.Start(); err != nil {
		return "", "", -1, err
	}
	if err := waitForMarker(&out, marker, wait); err != nil {
		_ = cmd.Process.Kill()
		_ = cmd.Wait()
		return out.String(), stderrBuffer.String(), -1, err
	}
	// Stop the Endpoint so the Server observes a disconnect while the follow is
	// still open. The CLI is left running: it must end on its own once the
	// Server releases the stream.
	if err := StopProcessE(c.Endpoint); err != nil {
		_ = cmd.Process.Kill()
		_ = cmd.Wait()
		return out.String(), stderrBuffer.String(), -1, fmt.Errorf("stop endpoint mid-follow: %w", err)
	}
	runErr := cmd.Wait()
	if ctx.Err() != nil {
		return out.String(), stderrBuffer.String(), -1, ctx.Err()
	}
	exitCode = 0
	if runErr != nil {
		exitCode = 1
		var exitErr *exec.ExitError
		if errors.As(runErr, &exitErr) {
			exitCode = exitErr.ExitCode()
		}
	}
	return out.String(), stderrBuffer.String(), exitCode, runErr
}

// holdingPacedReader delivers scripted chunks and then blocks instead of
// returning EOF, so the REPL stays alive after the scripted input is consumed.
//
// A reader that returns EOF ends the REPL, and a REPL that exits closes its HTTP
// connection, which releases the follow on the Server side regardless of what the
// keypress did. A scenario that must prove the keypress itself released the
// provider child therefore has to keep the REPL alive while it checks, and this
// reader is what makes that possible.
//
// Release delivers one final chunk before EOF rather than closing the stream
// directly. The REPL runs under `script -qec`, which does not forward stdin EOF
// to the PTY, so an EOF alone leaves the REPL waiting for input forever. The
// final chunk is the explicit quit command that actually ends it.
type holdingPacedReader struct {
	chunks       []string
	pause        time.Duration
	releaseChunk string
	index        int
	buffer       []byte
	released     bool
	release      chan struct{}
}

// Read returns the next chunk, pausing before every chunk after the first, and
// blocks once the chunks are exhausted until release is closed. After release it
// delivers the release chunk once and then returns EOF.
func (r *holdingPacedReader) Read(payload []byte) (int, error) {
	if len(r.buffer) == 0 {
		if r.index >= len(r.chunks) {
			if !r.released {
				<-r.release
				r.released = true
				r.buffer = []byte(r.releaseChunk)
				if len(r.buffer) == 0 {
					return 0, io.EOF
				}
			} else {
				return 0, io.EOF
			}
		} else {
			if r.index > 0 {
				time.Sleep(r.pause)
			}
			r.buffer = []byte(r.chunks[r.index])
			r.index++
		}
	}
	written := copy(payload, r.buffer)
	r.buffer = r.buffer[written:]
	return written, nil
}

// InteractiveFollowRun is one REPL process driven through a PTY whose input stays
// open after the scripted chunks.
//
// It exists so a scenario can observe live process state between the keypress and
// the REPL exit. A synchronous run cannot: by the time it returns, the CLI process
// is gone and everything it owned has been released by process exit, so an
// assertion about what the keypress released cannot distinguish the two causes.
type InteractiveFollowRun struct {
	out      *syncBuffer
	errOut   *syncBuffer
	cmd      *exec.Cmd
	reader   *holdingPacedReader
	done     chan struct{}
	exitCode int
	runErr   error
}

// StartTUIInteractivePaced starts the REPL under a PTY and returns before it
// exits, so the caller can inspect state while the process is still alive.
func (c *Cluster) StartTUIInteractivePaced(chunks []string, pause time.Duration) (*InteractiveFollowRun, error) {
	if c.TUIPath == "" {
		return nil, fmt.Errorf("TUI binary has not been built; call BuildTUI first")
	}
	command := "'" + c.TUIPath + "' -i"
	cmd := exec.Command("script", "-qec", command, "/dev/null")
	cmd.Dir = ModuleRootForRun()
	cmd.Env = append(c.cliEnvironment(), "TERM=xterm-256color")
	reader := &holdingPacedReader{
		chunks:       chunks,
		pause:        pause,
		releaseChunk: "quit\n",
		release:      make(chan struct{}),
	}
	cmd.Stdin = reader
	run := &InteractiveFollowRun{
		out:    &syncBuffer{},
		errOut: &syncBuffer{},
		cmd:    cmd,
		reader: reader,
		done:   make(chan struct{}),
	}
	cmd.Stdout = run.out
	cmd.Stderr = run.errOut
	if err := cmd.Start(); err != nil {
		return nil, err
	}
	go func() {
		defer close(run.done)
		runErr := cmd.Wait()
		run.exitCode = 0
		if runErr != nil {
			run.exitCode = 1
			var exitErr *exec.ExitError
			if errors.As(runErr, &exitErr) {
				run.exitCode = exitErr.ExitCode()
			}
		}
		run.runErr = runErr
	}()
	return run, nil
}

// Output returns everything the REPL has written so far.
func (r *InteractiveFollowRun) Output() string { return r.out.String() }

// Stderr returns everything the REPL has written to stderr so far.
func (r *InteractiveFollowRun) Stderr() string { return r.errOut.String() }

// WaitForOutput polls the REPL output until the needle appears or the budget
// expires.
//
// The comparison strips terminal control sequences first. A PTY run renders the
// prompt through the styled writer, so the raw bytes are
// "\x1b[1;32mlog.follow>\x1b[0m res_..." and a plain substring search for
// "log.follow> res_" can never match. The stream really armed in that case; only
// the assertion was blind to it.
func (r *InteractiveFollowRun) WaitForOutput(needle string, wait time.Duration) error {
	deadline := time.Now().Add(wait)
	for time.Now().Before(deadline) {
		if strings.Contains(stripTerminalSGR(r.out.String()), needle) {
			return nil
		}
		select {
		case <-r.done:
			return fmt.Errorf("the REPL exited before %q appeared; output=%s", needle, r.out.String())
		default:
		}
		time.Sleep(20 * time.Millisecond)
	}
	return fmt.Errorf("%q was not observed before the deadline; output=%s", needle, r.out.String())
}

// stripTerminalSGR removes ANSI control sequences so a plain-text needle can be
// matched against PTY output.
//
// It covers the CSI forms this REPL emits: colour, dim, reset, erase-line and
// cursor movement. Matching raw bytes instead would make every styled prompt
// invisible to an assertion, which is the failure mode this function exists to
// prevent.
func stripTerminalSGR(text string) string {
	var builder strings.Builder
	builder.Grow(len(text))
	for index := 0; index < len(text); index++ {
		if text[index] != 0x1b {
			builder.WriteByte(text[index])
			continue
		}
		index++
		if index >= len(text) || text[index] != '[' {
			continue
		}
		for index < len(text) {
			current := text[index]
			if (current >= 'A' && current <= 'Z') || (current >= 'a' && current <= 'z') {
				break
			}
			index++
		}
	}
	return builder.String()
}

// Done reports a channel that closes when the REPL process exits.
//
// A scenario needs it to prove the REPL was still alive at the moment the
// provider child disappeared. Without that check a dead REPL would release
// everything it owned through process exit, and an assertion about what the
// keypress released could not tell the two causes apart.
func (r *InteractiveFollowRun) Done() <-chan struct{} { return r.done }

// Release lets the input reader return EOF so the REPL can exit.
func (r *InteractiveFollowRun) Release() {
	select {
	case <-r.reader.release:
	default:
		close(r.reader.release)
	}
}

// Wait blocks until the REPL exits and returns its exit code.
func (r *InteractiveFollowRun) Wait(wait time.Duration) (int, error) {
	select {
	case <-r.done:
		return r.exitCode, r.runErr
	case <-time.After(wait):
		_ = r.cmd.Process.Kill()
		<-r.done
		return -1, fmt.Errorf("the REPL did not exit within %s", wait)
	}
}

// Kill terminates the REPL without waiting for a clean exit. It is the cleanup
// path for a scenario that failed before it could release the reader.
func (r *InteractiveFollowRun) Kill() {
	r.Release()
	if r.cmd.Process != nil {
		_ = r.cmd.Process.Kill()
	}
	<-r.done
}
