package tui

import (
	"context"
	"io"
	"os"
	"strings"
	"testing"
	"time"

	"topsailai_agent_cluster/internal/protocol"
)

type interruptAPI struct {
	interactiveStub
	started chan struct{}
}

func (s *interruptAPI) ListEndpoints(ctx context.Context) ([]protocol.Endpoint, error) {
	select {
	case s.started <- struct{}{}:
	default:
	}
	<-ctx.Done()
	return nil, ctx.Err()
}

func TestInteractivePromptInterruptReturnsTypedErrorAndJoinsWatcher(t *testing.T) {
	signals := make(chan os.Signal, 1)
	input, inputWriter := io.Pipe()
	go func() {
		time.Sleep(10 * time.Millisecond)
		signals <- os.Interrupt
	}()
	defer inputWriter.Close()
	var output, diagnostics strings.Builder
	started := time.Now()
	err := RunInteractive(context.Background(), &interactiveStub{}, input, &output, &diagnostics, InteractiveOptions{Interrupt: signals, CloseInput: true})
	if err != ErrInteractiveInterrupt {
		t.Fatalf("error=%v want=%v", err, ErrInteractiveInterrupt)
	}
	if time.Since(started) >= time.Second {
		t.Fatalf("prompt interrupt did not return promptly")
	}
}

func TestInteractiveCommandInterruptCancelsOnlyCurrentCommand(t *testing.T) {
	signals := make(chan os.Signal, 1)
	api := &interruptAPI{started: make(chan struct{}, 1)}
	var output, diagnostics strings.Builder
	done := make(chan error, 1)
	go func() {
		done <- RunInteractive(context.Background(), api, strings.NewReader("list\nhelp\nquit\n"), &output, &diagnostics, InteractiveOptions{Interrupt: signals})
	}()
	select {
	case <-api.started:
	case <-time.After(time.Second):
		t.Fatal("list command did not start")
	}
	signals <- os.Interrupt
	select {
	case err := <-done:
		if err != nil {
			t.Fatalf("RunInteractive: %v", err)
		}
	case <-time.After(time.Second):
		t.Fatal("interrupted command did not return")
	}
	if !strings.Contains(diagnostics.String(), "interrupted\n") {
		t.Fatalf("diagnostics=%q", diagnostics.String())
	}
	if !strings.Contains(output.String(), "commands:") {
		t.Fatalf("subsequent command did not execute: %q", output.String())
	}
}
