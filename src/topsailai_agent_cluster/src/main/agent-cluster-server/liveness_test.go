package main

import (
	"context"
	"io"
	"log/slog"
	"sync"
	"testing"
	"time"

	"topsailai_agent_cluster/internal/channel"
)

type livenessServerStub struct {
	mu    sync.Mutex
	calls int
	times []time.Time
	peers []channel.Peer
}

func (s *livenessServerStub) ExpireStalePeers(now time.Time) []channel.Peer {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.calls++
	s.times = append(s.times, now)
	return s.peers
}

func (s *livenessServerStub) callCount() int {
	s.mu.Lock()
	defer s.mu.Unlock()
	return s.calls
}

// TestRunEndpointLivenessRunsImmediatelyAndStops verifies the Server does not
// wait one interval before detecting an already-stale connection.
func TestRunEndpointLivenessRunsImmediatelyAndStops(t *testing.T) {
	ctx, cancel := context.WithCancel(context.Background())
	stub := &livenessServerStub{}
	done := make(chan struct{})
	go func() {
		defer close(done)
		runEndpointLivenessAtInterval(ctx, slog.New(slog.NewTextHandler(io.Discard, nil)), stub, time.Hour)
	}()
	deadline := time.Now().Add(time.Second)
	for stub.callCount() == 0 && time.Now().Before(deadline) {
		time.Sleep(time.Millisecond)
	}
	if got := stub.callCount(); got != 1 {
		cancel()
		<-done
		t.Fatalf("liveness calls=%d, want 1 immediate call", got)
	}
	cancel()
	select {
	case <-done:
	case <-time.After(time.Second):
		t.Fatal("liveness loop did not stop after cancellation")
	}
}

// TestRunEndpointLivenessRepeats verifies the ticker triggers later sweeps.
func TestRunEndpointLivenessRepeats(t *testing.T) {
	ctx, cancel := context.WithCancel(context.Background())
	stub := &livenessServerStub{}
	done := make(chan struct{})
	go func() {
		defer close(done)
		runEndpointLivenessAtInterval(ctx, slog.New(slog.NewTextHandler(io.Discard, nil)), stub, time.Millisecond)
	}()
	deadline := time.Now().Add(time.Second)
	for stub.callCount() < 2 && time.Now().Before(deadline) {
		time.Sleep(time.Millisecond)
	}
	cancel()
	<-done
	if got := stub.callCount(); got < 2 {
		t.Fatalf("liveness calls=%d, want at least 2", got)
	}
}

// TestEndpointLivenessIntervalBounds verifies scan cadence remains bounded.
func TestEndpointLivenessIntervalBounds(t *testing.T) {
	cases := []struct {
		name    string
		timeout time.Duration
		want    time.Duration
	}{
		{name: "small", timeout: time.Second, want: time.Second},
		{name: "proportional", timeout: 6 * time.Second, want: 3 * time.Second},
		{name: "default", timeout: 30 * time.Second, want: 5 * time.Second},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			if got := endpointLivenessInterval(tc.timeout); got != tc.want {
				t.Fatalf("interval=%s, want %s", got, tc.want)
			}
		})
	}
}
