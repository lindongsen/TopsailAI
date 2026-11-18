package main

import (
	"context"
	"errors"
	"log/slog"
	"strings"
	"testing"

	"topsailai_agent_cluster/internal/channel"
	"topsailai_agent_cluster/internal/protocol"
)

// admissionIntent is the minimal intent the notifier reads.
func admissionIntent(commandID string) protocol.ImmutableIntent {
	return protocol.ImmutableIntent{CommandID: commandID, EndpointID: "endpoint-1", Operation: "message.send"}
}

// TestAdmissionHookTransportFailureDoesNotAbortExecution proves the defect this
// change fixes: a command dispatched while the channel is detached must still
// reach the provider.
//
// The assertion is on the returned error, because that error is what the executor
// turns into an empty receipt. An empty receipt has no command ID, so executeFrame
// drops it and the Server never learns the outcome; the command then converges to
// unconfirmed/unknown although it provably never ran.
func TestAdmissionHookTransportFailureDoesNotAbortExecution(t *testing.T) {
	var logged []string
	logger := slog.New(slog.NewTextHandler(&lineWriter{lines: &logged}, &slog.HandlerOptions{Level: slog.LevelDebug}))
	notifier := admissionNotifier{
		send:   func(context.Context, channel.Frame) error { return channel.ErrOffline },
		hold:   func(string) error { return nil },
		wait:   func(*slog.Logger, string) error { return nil },
		logger: logger,
	}
	if err := notifier.notify(context.Background(), admissionIntent("cmd-offline"), "hash"); err != nil {
		t.Fatalf("an offline channel must not abort the command, got error %v", err)
	}
	joined := strings.Join(logged, "\n")
	if !strings.Contains(joined, "publish endpoint admission") {
		t.Fatalf("the lost admission frame must be logged, got %q", joined)
	}
	if !strings.Contains(joined, "level=WARN") {
		t.Fatalf("an offline channel is a connectivity state, so the line must be WARN, got %q", joined)
	}
}

// TestAdmissionHookTestHookFailureStillAborts proves the fix is scoped to
// transport failures. A hold that cannot be reached means the test's premise is
// broken, so the command must not proceed as if it had been observed.
func TestAdmissionHookTestHookFailureStillAborts(t *testing.T) {
	holdErr := errors.New("test phase hold timed out: endpoint_admitted")
	notifier := admissionNotifier{
		send: func(context.Context, channel.Frame) error { return nil },
		hold: func(string) error { return holdErr },
		wait: func(*slog.Logger, string) error { return nil },
	}
	err := notifier.notify(context.Background(), admissionIntent("cmd-hold"), "hash")
	if !errors.Is(err, holdErr) {
		t.Fatalf("a hold failure must abort the command, got error %v", err)
	}
}

// TestAdmissionHookSuccessStillSendsTheFrame is the positive case. Without it,
// deleting the admission frame entirely would pass both negative tests, because
// neither of them asserts that a healthy channel publishes anything.
func TestAdmissionHookSuccessStillSendsTheFrame(t *testing.T) {
	var frames []channel.Frame
	notifier := admissionNotifier{
		send: func(_ context.Context, frame channel.Frame) error {
			frames = append(frames, frame)
			return nil
		},
		hold: func(string) error { return nil },
		wait: func(*slog.Logger, string) error { return nil },
	}
	if err := notifier.notify(context.Background(), admissionIntent("cmd-healthy"), "hash"); err != nil {
		t.Fatalf("a healthy admission must succeed, got error %v", err)
	}
	if len(frames) != 1 {
		t.Fatalf("admission frames sent = %d, want 1", len(frames))
	}
	frame := frames[0]
	if frame.Type != channel.FrameReceipt {
		t.Fatalf("frame type = %q, want %q", frame.Type, channel.FrameReceipt)
	}
	if frame.Receipt == nil {
		t.Fatal("the admission frame must carry a receipt")
	}
	if frame.Receipt.Outcome != "endpoint_admitted" {
		t.Fatalf("receipt outcome = %q, want %q", frame.Receipt.Outcome, "endpoint_admitted")
	}
	if frame.Receipt.CommandID != "cmd-healthy" {
		t.Fatalf("receipt command ID = %q, want %q", frame.Receipt.CommandID, "cmd-healthy")
	}
}

// TestAdmissionHookRunsTheHoldAfterTheFrame proves the ordering the test hooks
// depend on: the Server learns admission before the Endpoint parks on a hold.
func TestAdmissionHookRunsTheHoldAfterTheFrame(t *testing.T) {
	var order []string
	notifier := admissionNotifier{
		send: func(context.Context, channel.Frame) error {
			order = append(order, "send")
			return nil
		},
		hold: func(string) error {
			order = append(order, "hold")
			return nil
		},
		wait: func(*slog.Logger, string) error {
			order = append(order, "wait")
			return nil
		},
	}
	if err := notifier.notify(context.Background(), admissionIntent("cmd-order"), "hash"); err != nil {
		t.Fatalf("notify failed: %v", err)
	}
	want := []string{"send", "hold", "wait"}
	if len(order) != len(want) {
		t.Fatalf("call order = %v, want %v", order, want)
	}
	for i := range want {
		if order[i] != want[i] {
			t.Fatalf("call order = %v, want %v", order, want)
		}
	}
}

// lineWriter collects log lines so a test can assert on the emitted level.
type lineWriter struct{ lines *[]string }

func (w *lineWriter) Write(p []byte) (int, error) {
	*w.lines = append(*w.lines, strings.TrimSpace(string(p)))
	return len(p), nil
}
