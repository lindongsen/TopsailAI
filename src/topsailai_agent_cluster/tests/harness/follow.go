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
	cmd.Env = append(os.Environ(),
		"AGENT_CLUSTER_SERVER_URL="+c.URL(""),
		"AGENT_CLUSTER_TOKEN=secret",
		"AGENT_CLUSTER_TLS_CA_FILE="+c.Certs.CA,
		"AGENT_CLUSTER_TLS_CERTIFICATE_FILE="+c.Certs.ClientCert,
		"AGENT_CLUSTER_TLS_KEY_FILE="+c.Certs.ClientKey,
	)
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
	cmd.Env = append(os.Environ(),
		"AGENT_CLUSTER_SERVER_URL="+c.URL(""),
		"AGENT_CLUSTER_TOKEN=secret",
		"AGENT_CLUSTER_TLS_CA_FILE="+c.Certs.CA,
		"AGENT_CLUSTER_TLS_CERTIFICATE_FILE="+c.Certs.ClientCert,
		"AGENT_CLUSTER_TLS_KEY_FILE="+c.Certs.ClientKey,
	)
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
