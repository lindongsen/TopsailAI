package main

import (
	"context"
	"net"
	"os"
	"strings"
	"testing"
	"time"
)

// validServerEnvironment sets the minimum environment a Server needs to start.
//
// The listen address is supplied by the caller because the tests below differ in
// exactly that value: one binds a port that is already taken, the other binds a
// port that is free. Everything else is the same, so a failure names the address
// rather than an unrelated missing secret.
func validServerEnvironment(t *testing.T, listen string) {
	t.Helper()
	clearServerEnvironment(t)
	t.Setenv("CONNECTOR_SERVER_LISTEN", listen)
	t.Setenv("CONNECTOR_SERVER_TUNNEL_TOKEN", strings.Repeat("a", 32))
	t.Setenv("CONNECTOR_SERVER_CLIENT_CREDENTIALS_FILE", writeClientCredentialFile(t))
}

// TestRunServerReportsABoundPort checks that a listen failure is reported instead
// of being swallowed.
//
// The address passes validation, so the only way to fail is for the operating
// system to refuse the bind. A Server that ignored that error would exit zero
// while serving nothing, and the operator would read a clean exit as a clean
// shutdown.
func TestRunServerReportsABoundPort(t *testing.T) {
	taken, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatalf("reserve a port: %v", err)
	}
	defer func() { _ = taken.Close() }()

	validServerEnvironment(t, taken.Addr().String())

	err = runServer(nil)
	if err == nil {
		t.Fatal("runServer on a bound port = nil error, want a listen failure")
	}
	if !strings.Contains(err.Error(), "listen on") {
		t.Errorf("error = %q, want it to name the listen failure", err)
	}
}

// TestRunServerServesUntilTheContextEnds checks that a started Server serves and
// then returns when it is asked to stop.
//
// The stop is delivered as a signal rather than by cancelling a context, because
// the signal path is the one an operator uses. A Server that only stopped on a
// context cancellation would ignore Ctrl-C and SIGTERM, and the operator would
// reach for a kill that leaves the port bound.
func TestRunServerServesUntilTheContextEnds(t *testing.T) {
	free, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatalf("reserve a port: %v", err)
	}
	address := free.Addr().String()
	if err := free.Close(); err != nil {
		t.Fatalf("release the port: %v", err)
	}

	validServerEnvironment(t, address)

	done := make(chan error, 1)
	go func() { done <- runServer(nil) }()

	// Readiness is polled from the port rather than from the log, because the log
	// line is written before the bind and a test that trusted it would race the
	// listener.
	deadline := time.Now().Add(5 * time.Second)
	for {
		connection, dialErr := net.DialTimeout("tcp", address, 100*time.Millisecond)
		if dialErr == nil {
			_ = connection.Close()
			break
		}
		if time.Now().After(deadline) {
			t.Fatalf("the Server never accepted a connection on %s", address)
		}
		time.Sleep(20 * time.Millisecond)
	}

	if err := signalProcess(t); err != nil {
		t.Fatalf("send the stop signal: %v", err)
	}

	select {
	case err := <-done:
		if err != nil {
			t.Errorf("runServer after a stop signal = %v, want nil", err)
		}
	case <-time.After(10 * time.Second):
		t.Fatal("runServer did not return after a stop signal")
	}
}

// signalProcess sends the interrupt the Server listens for.
//
// It sends the signal to this process, which is what an operator's Ctrl-C does.
// The Server's handler is the only listener registered for it in this test, so the
// signal reaches the code under test rather than an unrelated handler.
func signalProcess(t *testing.T) error {
	t.Helper()
	process, err := os.FindProcess(os.Getpid())
	if err != nil {
		return err
	}
	return process.Signal(os.Interrupt)
}

// TestSignalContextCancelsOnASignal checks the cancellation itself, without a
// Server.
//
// The context is the contract: Serve closes the listener and every live channel
// when it ends. A context that never cancelled would leave the port bound until
// the operating system reclaimed it, which on Windows is long enough to make an
// immediate restart fail.
func TestSignalContextCancelsOnASignal(t *testing.T) {
	ctx, stop := signalContext()
	defer stop()

	if err := ctx.Err(); err != nil {
		t.Fatalf("a fresh context is already done: %v", err)
	}

	if err := signalProcess(t); err != nil {
		t.Fatalf("send the stop signal: %v", err)
	}

	select {
	case <-ctx.Done():
	case <-time.After(5 * time.Second):
		t.Fatal("the context was not cancelled by a signal")
	}
}

// TestSignalContextStopCancelsWithoutASignal checks the deferred stop.
//
// Every caller defers stop, so a stop that did nothing would leak the goroutine
// that waits for a signal on every run, including every test.
func TestSignalContextStopCancelsWithoutASignal(t *testing.T) {
	ctx, stop := signalContext()

	stop()

	select {
	case <-ctx.Done():
	case <-time.After(5 * time.Second):
		t.Fatal("stop() did not cancel the context")
	}
}

// TestSignalContextReturnsAContext checks the returned context is usable.
//
// A nil context would panic inside Serve rather than fail a test, so the value is
// asserted here where the failure names the cause.
func TestSignalContextReturnsAContext(t *testing.T) {
	ctx, stop := signalContext()
	defer stop()

	if ctx == nil {
		t.Fatal("signalContext() returned a nil context")
	}
	if ctx != context.Background() && ctx.Err() != nil {
		t.Errorf("ctx.Err() = %v, want nil on a fresh context", ctx.Err())
	}
}
