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
	mu                  sync.Mutex
	cutoffs             []int64
	purgeCutoffs        []int64
	reconcileCalls      []int64
	degradeCutoffs      []int64
	degradeNowMS        []int64
	degradeRetentionMS  []int64
	converged           int64
	purged              int64
	degradedIDs         []string
	degradedInventoryID []string
	inventoryIDs        []string
	deletedIDs          []string
	deletedCommandIDs   []string
	cancel              context.CancelFunc
	cancelCall          int
	expireErr           error
	degradeErr          error
	purgeErr            error
	reconcileErr        error
	purgeCallSeen       int
	degradeCallSeen     int
	order               []string
}

// ReconcileExpiredCommands records one convergence invocation.
func (s *expiryStoreStub) ReconcileExpiredCommands(_ context.Context, nowMS int64) (int64, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.reconcileCalls = append(s.reconcileCalls, nowMS)
	s.order = append(s.order, "reconcile")
	if s.reconcileErr != nil {
		return 0, s.reconcileErr
	}
	return s.converged, nil
}

// DegradeOfflineEndpoints records one degradation invocation.
func (s *expiryStoreStub) DegradeOfflineEndpoints(_ context.Context, cutoffMS, nowMS, retentionMS int64) (serverstorage.EndpointDegradeResult, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.degradeCutoffs = append(s.degradeCutoffs, cutoffMS)
	s.order = append(s.order, "degrade")
	s.degradeNowMS = append(s.degradeNowMS, nowMS)
	s.degradeRetentionMS = append(s.degradeRetentionMS, retentionMS)
	s.degradeCallSeen++
	if s.degradeErr != nil {
		return serverstorage.EndpointDegradeResult{}, s.degradeErr
	}
	return serverstorage.EndpointDegradeResult{DegradedEndpointIDs: s.degradedIDs, InventoryEndpointIDs: s.degradedInventoryID}, nil
}

// ExpireDegradedEndpoints records one expiry invocation.
func (s *expiryStoreStub) ExpireDegradedEndpoints(_ context.Context, cutoffMS int64) (serverstorage.EndpointExpiryResult, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.cutoffs = append(s.cutoffs, cutoffMS)
	s.order = append(s.order, "expire")
	if len(s.cutoffs) == s.cancelCall && s.cancel != nil {
		s.cancel()
	}
	if s.expireErr != nil {
		return serverstorage.EndpointExpiryResult{}, s.expireErr
	}
	return serverstorage.EndpointExpiryResult{InventoryEndpointIDs: s.inventoryIDs, DeletedEndpointIDs: s.deletedIDs, DeletedCommandIDs: s.deletedCommandIDs}, nil
}

// PurgeExpiredCommands records one command purge invocation.
func (s *expiryStoreStub) PurgeExpiredCommands(_ context.Context, cutoffMS int64) (int64, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.purgeCutoffs = append(s.purgeCutoffs, cutoffMS)
	s.order = append(s.order, "purge")
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
		runEndpointExpiry(ctx, logger, stub, 5*time.Minute, time.Hour, 720*time.Hour)
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
		runEndpointExpiryAtInterval(ctx, logger, stub, 5*time.Minute, time.Hour, 720*time.Hour, time.Millisecond)
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

// TestExpireEndpointRecordsLogsCompletionWhenNothingDeleted verifies a sweep
// that selects zero rows still reports that it ran. Without this line a sweep
// that deleted nothing is indistinguishable from a sweep that never ran, which
// is how the unreachable offline state stayed hidden.
func TestExpireEndpointRecordsLogsCompletionWhenNothingDeleted(t *testing.T) {
	var output bytes.Buffer
	logger := slog.New(slog.NewTextHandler(&output, nil))
	stub := &expiryStoreStub{}
	expireEndpointRecords(context.Background(), logger, stub, time.Hour, 24*time.Hour, 720*time.Hour, time.UnixMilli(10_000_000))

	logged := output.String()
	if !strings.Contains(logged, "retention sweep complete") {
		t.Fatalf("completion line missing from %q", logged)
	}
	for _, field := range []string{"purged_commands=0", "deleted_inventory=0", "deleted_metadata=0"} {
		if !strings.Contains(logged, field) {
			t.Fatalf("field %q missing from %q", field, logged)
		}
	}
}

// TestExpireEndpointRecordsLogsCountsWhenRowsDeleted verifies the completion
// line carries the real counts and that the per-row lines are still emitted.
func TestExpireEndpointRecordsLogsCountsWhenRowsDeleted(t *testing.T) {
	var output bytes.Buffer
	logger := slog.New(slog.NewTextHandler(&output, nil))
	stub := &expiryStoreStub{purged: 3, inventoryIDs: []string{"gone-1"}, deletedIDs: []string{"gone-1"}}
	expireEndpointRecords(context.Background(), logger, stub, time.Hour, 24*time.Hour, 720*time.Hour, time.UnixMilli(10_000_000))

	logged := output.String()
	for _, field := range []string{"purged_commands=3", "deleted_inventory=1", "deleted_metadata=1"} {
		if !strings.Contains(logged, field) {
			t.Fatalf("field %q missing from %q", field, logged)
		}
	}
	for _, line := range []string{"expired degraded endpoint inventory", "expired degraded endpoint metadata"} {
		if !strings.Contains(logged, line) {
			t.Fatalf("per-row line %q missing from %q", line, logged)
		}
	}
}

// TestExpireEndpointRecordsPurgesCommandsBeforeEndpointExpiry verifies the purge
// runs first, so a metadata row blocked only by a now-purgeable command is
// removed in the same sweep instead of surviving one extra cycle.
func TestExpireEndpointRecordsPurgesCommandsBeforeEndpointExpiry(t *testing.T) {
	logger := slog.New(slog.NewTextHandler(io.Discard, nil))
	stub := &expiryStoreStub{}
	expireEndpointRecords(context.Background(), logger, stub, time.Hour, 24*time.Hour, 720*time.Hour, time.UnixMilli(10_000_000))

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
	expireEndpointRecords(context.Background(), logger, stub, time.Hour, 24*time.Hour, 720*time.Hour, time.UnixMilli(10_000_000))

	stub.mu.Lock()
	defer stub.mu.Unlock()
	if len(stub.cutoffs) != 0 {
		t.Fatalf("endpoint expiry ran after a failed purge: %v", stub.cutoffs)
	}
	if !strings.Contains(output.String(), "purge expired command records") {
		t.Fatalf("purge failure was not logged: %q", output.String())
	}
}

// TestExpireEndpointRecordsReconcilesBeforePurge verifies convergence runs first. A command that
// is still non-terminal is not purgeable, so purging before converging would leave the converged
// row waiting one extra cycle before it could be deleted.
func TestExpireEndpointRecordsReconcilesBeforePurge(t *testing.T) {
	logger := slog.New(slog.NewTextHandler(io.Discard, nil))
	stub := &expiryStoreStub{}
	expireEndpointRecords(context.Background(), logger, stub, time.Hour, 24*time.Hour, 720*time.Hour, time.UnixMilli(10_000_000))

	stub.mu.Lock()
	defer stub.mu.Unlock()
	if len(stub.reconcileCalls) != 1 {
		t.Fatalf("reconcile calls = %d, want 1", len(stub.reconcileCalls))
	}
	if stub.reconcileCalls[0] != 10_000_000 {
		t.Fatalf("reconcile nowMS = %d, want the sweep clock 10000000", stub.reconcileCalls[0])
	}
	if stub.purgeCallSeen != 1 {
		t.Fatalf("purge calls = %d, want 1", stub.purgeCallSeen)
	}
}

// TestExpireEndpointRecordsStopsWhenReconcileFails verifies a failed convergence does not
// continue into purge or endpoint expiry. Continuing would report a partial sweep as complete
// and would delete command rows while other rows were still stuck non-terminal.
func TestExpireEndpointRecordsStopsWhenReconcileFails(t *testing.T) {
	var output bytes.Buffer
	logger := slog.New(slog.NewTextHandler(&output, nil))
	stub := &expiryStoreStub{reconcileErr: context.DeadlineExceeded}
	expireEndpointRecords(context.Background(), logger, stub, time.Hour, 24*time.Hour, 720*time.Hour, time.UnixMilli(10_000_000))

	stub.mu.Lock()
	defer stub.mu.Unlock()
	if stub.purgeCallSeen != 0 {
		t.Fatalf("purge ran after a failed reconcile: %d calls", stub.purgeCallSeen)
	}
	if len(stub.cutoffs) != 0 {
		t.Fatalf("endpoint expiry ran after a failed reconcile: %v", stub.cutoffs)
	}
	if !strings.Contains(output.String(), "reconcile expired command records") {
		t.Fatalf("reconcile failure was not logged: %q", output.String())
	}
	if strings.Contains(output.String(), "retention sweep complete") {
		t.Fatalf("a failed sweep reported completion: %q", output.String())
	}
}

// TestExpireEndpointRecordsLogsConvergedCount verifies the completion line carries the
// convergence count, so an operator can tell a sweep that converged nothing from one that
// converged rows without reading the database.
func TestExpireEndpointRecordsLogsConvergedCount(t *testing.T) {
	var output bytes.Buffer
	logger := slog.New(slog.NewTextHandler(&output, nil))
	stub := &expiryStoreStub{converged: 2}
	expireEndpointRecords(context.Background(), logger, stub, time.Hour, 24*time.Hour, 720*time.Hour, time.UnixMilli(10_000_000))

	if !strings.Contains(output.String(), "converged_commands=2") {
		t.Fatalf("converged count missing from %q", output.String())
	}
}

// TestExpireEndpointRecordsDegradesBeforeExpiring verifies degradation runs
// before expiry in the same sweep.
//
// Expiry only selects rows that are already degraded, so an offline row that
// just crossed the offline window must be degraded in this sweep. If expiry ran
// first, that row would wait one more cycle before its degraded window even
// started, and the configured degraded retention would be silently longer than
// the operator asked for.
func TestExpireEndpointRecordsDegradesBeforeExpiring(t *testing.T) {
	logger := slog.New(slog.NewTextHandler(io.Discard, nil))
	stub := &expiryStoreStub{}
	expireEndpointRecords(context.Background(), logger, stub, time.Hour, 24*time.Hour, 720*time.Hour, time.UnixMilli(10_000_000))

	stub.mu.Lock()
	defer stub.mu.Unlock()
	if stub.degradeCallSeen != 1 {
		t.Fatalf("degrade calls = %d, want 1", stub.degradeCallSeen)
	}
	if len(stub.cutoffs) != 1 {
		t.Fatalf("expiry calls = %d, want 1", len(stub.cutoffs))
	}
	// The degrade cutoff is the offline window, so it must be newer than the
	// command cutoff and older than the sweep clock.
	if stub.degradeCutoffs[0] != 10_000_000-int64(time.Hour/time.Millisecond) {
		t.Fatalf("degrade cutoff = %d, want the offline window applied to the sweep clock", stub.degradeCutoffs[0])
	}
	if stub.degradeNowMS[0] != 10_000_000 {
		t.Fatalf("degrade nowMS = %d, want the sweep clock", stub.degradeNowMS[0])
	}
	if stub.degradeRetentionMS[0] != int64(720*time.Hour/time.Millisecond) {
		t.Fatalf("degrade retention = %d, want 720h in milliseconds", stub.degradeRetentionMS[0])
	}
	// The order is the load-bearing part: expiry only selects rows that are
	// already degraded, so degrade must precede expire in the same sweep.
	want := []string{"reconcile", "purge", "degrade", "expire"}
	if len(stub.order) != len(want) {
		t.Fatalf("call order = %v, want %v", stub.order, want)
	}
	for i := range want {
		if stub.order[i] != want[i] {
			t.Fatalf("call order = %v, want %v", stub.order, want)
		}
	}
}

// TestExpireEndpointRecordsStopsWhenDegradeFails verifies a failed degradation
// does not continue into expiry.
//
// Continuing would delete rows while other rows were still stuck offline, and
// the completion line would report a partial sweep as a complete one.
func TestExpireEndpointRecordsStopsWhenDegradeFails(t *testing.T) {
	var output bytes.Buffer
	logger := slog.New(slog.NewTextHandler(&output, nil))
	stub := &expiryStoreStub{degradeErr: context.DeadlineExceeded}
	expireEndpointRecords(context.Background(), logger, stub, time.Hour, 24*time.Hour, 720*time.Hour, time.UnixMilli(10_000_000))

	stub.mu.Lock()
	defer stub.mu.Unlock()
	if len(stub.cutoffs) != 0 {
		t.Fatalf("expiry ran after a failed degrade: %v", stub.cutoffs)
	}
	if !strings.Contains(output.String(), "degrade offline endpoint records") {
		t.Fatalf("degrade failure was not logged: %q", output.String())
	}
	if strings.Contains(output.String(), "retention sweep complete") {
		t.Fatalf("a failed sweep reported completion: %q", output.String())
	}
}

// TestExpireEndpointRecordsLogsDegradedAndDeletedCounts verifies the completion
// line and the per-row lines carry the degradation and cascade counts, so an
// operator can tell what a sweep did without reading the database.
func TestExpireEndpointRecordsLogsDegradedAndDeletedCounts(t *testing.T) {
	var output bytes.Buffer
	logger := slog.New(slog.NewTextHandler(&output, nil))
	stub := &expiryStoreStub{
		degradedIDs:         []string{"stale-1"},
		degradedInventoryID: []string{"stale-1"},
		deletedIDs:          []string{"gone-1"},
		deletedCommandIDs:   []string{"cmd-1", "cmd-2"},
	}
	expireEndpointRecords(context.Background(), logger, stub, time.Hour, 24*time.Hour, 720*time.Hour, time.UnixMilli(10_000_000))

	logged := output.String()
	for _, field := range []string{"degraded_endpoints=1", "deleted_degraded_inventory=1", "deleted_commands=2", "deleted_metadata=1", "degraded_retention=720h0m0s"} {
		if !strings.Contains(logged, field) {
			t.Fatalf("field %q missing from %q", field, logged)
		}
	}
	for _, line := range []string{"degraded offline endpoint", "deleted degraded endpoint inventory", "deleted expired endpoint command", "expired degraded endpoint metadata"} {
		if !strings.Contains(logged, line) {
			t.Fatalf("per-row line %q missing from %q", line, logged)
		}
	}
}
