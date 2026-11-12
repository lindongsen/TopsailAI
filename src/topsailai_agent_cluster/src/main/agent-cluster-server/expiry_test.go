package main

import (
	"context"
	"io"
	"log/slog"
	"sync"
	"testing"
	"time"

	serverstorage "topsailai_agent_cluster/internal/storage/server"
)

// expiryStoreStub records cleanup cutoffs and cancels after the requested call.
type expiryStoreStub struct {
	mu         sync.Mutex
	cutoffs    []int64
	cancel     context.CancelFunc
	cancelCall int
}

// ExpireOfflineEndpoints records one cleanup invocation.
func (s *expiryStoreStub) ExpireOfflineEndpoints(_ context.Context, cutoffMS int64) (serverstorage.EndpointExpiryResult, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.cutoffs = append(s.cutoffs, cutoffMS)
	if len(s.cutoffs) == s.cancelCall && s.cancel != nil {
		s.cancel()
	}
	return serverstorage.EndpointExpiryResult{}, nil
}

// TestRunEndpointExpiryRunsImmediatelyAndStops verifies startup cleanup does not
// wait for the first ticker and cancellation stops the owned goroutine.
func TestRunEndpointExpiryRunsImmediatelyAndStops(t *testing.T) {
	ctx, cancel := context.WithCancel(context.Background())
	stub := &expiryStoreStub{cancel: cancel, cancelCall: 1}
	logger := slog.New(slog.NewTextHandler(io.Discard, nil))
	done := make(chan struct{})
	go func() {
		runEndpointExpiry(ctx, logger, stub, 5*time.Minute)
		close(done)
	}()
	select {
	case <-done:
	case <-time.After(time.Second):
		t.Fatal("expiry loop did not stop after cancellation")
	}
	stub.mu.Lock()
	defer stub.mu.Unlock()
	if len(stub.cutoffs) != 1 {
		t.Fatalf("expiry calls = %d, want 1", len(stub.cutoffs))
	}
}

// TestRunEndpointExpiryRepeats verifies the ticker executes a second sweep and
// cancellation still joins the loop after periodic work begins.
func TestRunEndpointExpiryRepeats(t *testing.T) {
	ctx, cancel := context.WithCancel(context.Background())
	stub := &expiryStoreStub{cancel: cancel, cancelCall: 2}
	logger := slog.New(slog.NewTextHandler(io.Discard, nil))
	done := make(chan struct{})
	go func() {
		runEndpointExpiryAtInterval(ctx, logger, stub, 5*time.Minute, time.Millisecond)
		close(done)
	}()
	select {
	case <-done:
	case <-time.After(time.Second):
		t.Fatal("expiry loop did not execute the periodic sweep")
	}
	stub.mu.Lock()
	defer stub.mu.Unlock()
	if len(stub.cutoffs) != 2 {
		t.Fatalf("expiry calls = %d, want 2", len(stub.cutoffs))
	}
}

// TestEndpointExpiryIntervalBounds verifies short and long retention settings do
// not create a busy loop or leave stale records indefinitely after expiry.
func TestEndpointExpiryIntervalBounds(t *testing.T) {
	cases := []struct {
		retention time.Duration
		want      time.Duration
	}{
		{retention: time.Second, want: time.Second},
		{retention: 10 * time.Second, want: 5 * time.Second},
		{retention: 5 * time.Minute, want: time.Minute},
	}
	for _, test := range cases {
		if got := endpointExpiryInterval(test.retention); got != test.want {
			t.Errorf("interval for %s = %s, want %s", test.retention, got, test.want)
		}
	}
}
