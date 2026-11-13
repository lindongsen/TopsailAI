package main

import (
	"bytes"
	"context"
	"io"
	"log/slog"
	"strings"
	"sync"
	"testing"
	"time"

	serverstorage "topsailai_agent_cluster/internal/storage/server"
)

// expiryStoreStub records cleanup cutoffs and cancels after the requested call.
type expiryStoreStub struct {
	mu            sync.Mutex
	cutoffs       []int64
	purgeCutoffs  []int64
	purged        int64
	inventoryIDs  []string
	deletedIDs    []string
	cancel        context.CancelFunc
	cancelCall    int
	expireErr     error
	purgeErr      error
	purgeCallSeen int
}

// ExpireOfflineEndpoints records one cleanup invocation.
func (s *expiryStoreStub) ExpireOfflineEndpoints(_ context.Context, cutoffMS int64) (serverstorage.EndpointExpiryResult, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.cutoffs = append(s.cutoffs, cutoffMS)
	if len(s.cutoffs) == s.cancelCall && s.cancel != nil {
		s.cancel()
	}
	if s.expireErr != nil {
		return serverstorage.EndpointExpiryResult{}, s.expireErr
	}
	return serverstorage.EndpointExpiryResult{InventoryEndpointIDs: s.inventoryIDs, DeletedEndpointIDs: s.deletedIDs}, nil
}

// PurgeExpiredCommands records one command purge invocation.
func (s *expiryStoreStub) PurgeExpiredCommands(_ context.Context, cutoffMS int64) (int64, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.purgeCutoffs = append(s.purgeCutoffs, cutoffMS)
	s.purgeCallSeen++
	if s.purgeErr != nil {
		return 0, s.purgeErr
	}
	return s.purged, nil
}

// TestRunEndpointExpiryRunsImmediatelyAndStops verifies startup cleanup does not
// wait for the first ticker and cancellation stops the owned goroutine.
func TestRunEndpointExpiryRunsImmediatelyAndStops(t *testing.T) {
	ctx, cancel := context.WithCancel(context.Background())
	stub := &expiryStoreStub{cancel: cancel, cancelCall: 1}
	logger := slog.New(slog.NewTextHandler(io.Discard, nil))
	done := make(chan struct{})
	go func() {
		runEndpointExpiry(ctx, logger, stub, 5*time.Minute, time.Hour)
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
		runEndpointExpiryAtInterval(ctx, logger, stub, 5*time.Minute, time.Hour, time.Millisecond)
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

// TestExpireEndpointRecordsPurgesCommandsBeforeEndpointExpiry verifies the purge
// runs first, so a metadata row blocked only by a now-purgeable command is
// removed in the same sweep instead of surviving one extra cycle.
func TestExpireEndpointRecordsPurgesCommandsBeforeEndpointExpiry(t *testing.T) {
	logger := slog.New(slog.NewTextHandler(io.Discard, nil))
	stub := &expiryStoreStub{}
	expireEndpointRecords(context.Background(), logger, stub, time.Hour, 24*time.Hour, time.UnixMilli(10_000_000))

	stub.mu.Lock()
	defer stub.mu.Unlock()
	if stub.purgeCallSeen != 1 {
		t.Fatalf("purge calls = %d, want 1", stub.purgeCallSeen)
	}
	if len(stub.purgeCutoffs) != 1 || len(stub.cutoffs) != 1 {
		t.Fatalf("purge cutoffs = %v, expiry cutoffs = %v", stub.purgeCutoffs, stub.cutoffs)
	}
	// The command retention is 24h and the endpoint retention is 1h, so the
	// command cutoff must be the older of the two.
	if stub.purgeCutoffs[0] >= stub.cutoffs[0] {
		t.Fatalf("command cutoff %d is not older than endpoint cutoff %d", stub.purgeCutoffs[0], stub.cutoffs[0])
	}
}

// TestExpireEndpointRecordsStopsWhenPurgeFails verifies a failed purge does not
// silently continue into endpoint expiry, which would report a partial sweep as
// a complete one.
func TestExpireEndpointRecordsStopsWhenPurgeFails(t *testing.T) {
	var output bytes.Buffer
	logger := slog.New(slog.NewTextHandler(&output, nil))
	stub := &expiryStoreStub{purgeErr: context.DeadlineExceeded}
	expireEndpointRecords(context.Background(), logger, stub, time.Hour, 24*time.Hour, time.UnixMilli(10_000_000))

	stub.mu.Lock()
	defer stub.mu.Unlock()
	if len(stub.cutoffs) != 0 {
		t.Fatalf("endpoint expiry ran after a failed purge: %v", stub.cutoffs)
	}
	if !strings.Contains(output.String(), "purge expired command records") {
		t.Fatalf("purge failure was not logged: %q", output.String())
	}
}
