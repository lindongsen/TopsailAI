package tui

import (
	"context"
	"io"
	"os"
	"runtime"
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
	watcherStarted := make(chan struct{})
	releaseWatcher := make(chan struct{})
	watcherReadyToFinish := make(chan struct{})
	finishWatcher := make(chan struct{})
	watcherExitCalled := make(chan bool, 1)
	var output, diagnostics strings.Builder
	done := make(chan error, 1)
	go func() {
		done <- RunInteractive(context.Background(), &interactiveStub{}, input, &output, &diagnostics, InteractiveOptions{
			Interrupt:  signals,
			CloseInput: true,
			watcherBeforeDone: func() {
				close(watcherStarted)
				<-releaseWatcher
				close(watcherReadyToFinish)
				<-finishWatcher
			},
			watcherExit: func(wasJoined bool) { watcherExitCalled <- wasJoined },
		})
	}()
	signals <- os.Interrupt
	select {
	case <-watcherStarted:
	case <-time.After(time.Second):
		t.Fatal("watcher did not reach completion barrier")
	}
	close(releaseWatcher)
	select {
	case <-watcherReadyToFinish:
	case <-time.After(time.Second):
		t.Fatal("watcher did not reach final barrier")
	}
	select {
	case wasJoined := <-watcherExitCalled:
		t.Fatalf("RunInteractive reported watcher joined=%v before watcher completion", wasJoined)
	case <-time.After(20 * time.Millisecond):
	}
	close(finishWatcher)
	defer inputWriter.Close()
	select {
	case err := <-done:
		if err != ErrInteractiveInterrupt {
			t.Fatalf("error=%v want=%v", err, ErrInteractiveInterrupt)
		}
	case <-time.After(time.Second):
		t.Fatal("prompt interrupt did not return")
	}
	select {
	case wasJoined := <-watcherExitCalled:
		if !wasJoined {
			t.Fatal("watcher was not joined before exit")
		}
	case <-time.After(time.Second):
		t.Fatal("watcher completion was not reported")
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

func TestInteractiveRepeatedPromptsUseBoundedReaderGoroutines(t *testing.T) {
	baseline := runtime.NumGoroutine()
	for i := 0; i < 32; i++ {
		input := strings.NewReader("help\nquit\n")
		var output, diagnostics strings.Builder
		if err := RunInteractive(context.Background(), &interactiveStub{}, input, &output, &diagnostics, InteractiveOptions{}); err != nil {
			t.Fatalf("RunInteractive iteration %d: %v", i, err)
		}
	}
	runtime.GC()
	deadline := time.Now().Add(time.Second)
	for runtime.NumGoroutine() > baseline+2 && time.Now().Before(deadline) {
		time.Sleep(time.Millisecond)
	}
	if got := runtime.NumGoroutine(); got > baseline+2 {
		t.Fatalf("goroutines grew across repeated prompts: baseline=%d got=%d", baseline, got)
	}
}
