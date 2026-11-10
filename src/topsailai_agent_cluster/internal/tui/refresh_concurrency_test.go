package tui

import (
	"context"
	"errors"
	"sync"
	"testing"
	"time"

	"topsailai_agent_cluster/internal/protocol"
)

// barrierStub releases a forced collection only after every expected Endpoint has
// entered one. A serial implementation can never satisfy the barrier, so the test
// proves concurrency instead of merely observing that the code compiles.
type barrierStub struct {
	interactiveStub
	mu       sync.Mutex
	entered  int
	expected int
	release  chan struct{}
	// inFlight and maxInFlight measure the observed concurrency.
	inFlight    int
	maxInFlight int
	// blockOn makes one Endpoint wait for its own context instead of the barrier,
	// so a test can model a hung collection.
	blockOn string
	// deadlineSeen records whether each call received a bounded context.
	deadlineSeen bool
}

func newBarrierStub(expected int) *barrierStub {
	return &barrierStub{
		interactiveStub: *scopeStub(),
		expected:        expected,
		release:         make(chan struct{}),
	}
}

func (s *barrierStub) RefreshInventory(ctx context.Context, endpointID string) (protocol.InventoryReport, error) {
	if _, ok := ctx.Deadline(); ok {
		s.mu.Lock()
		s.deadlineSeen = true
		s.mu.Unlock()
	}
	s.mu.Lock()
	s.inFlight++
	if s.inFlight > s.maxInFlight {
		s.maxInFlight = s.inFlight
	}
	s.entered++
	arrived := s.entered
	blocked := s.blockOn == endpointID
	s.mu.Unlock()
	defer func() {
		s.mu.Lock()
		s.inFlight--
		s.mu.Unlock()
	}()
	if blocked {
		<-ctx.Done()
		return protocol.InventoryReport{}, ctx.Err()
	}
	if arrived >= s.expected {
		// The last arrival opens the barrier for everyone.
		select {
		case <-s.release:
		default:
			close(s.release)
		}
	}
	select {
	case <-s.release:
	case <-time.After(5 * time.Second):
		// A serial implementation reaches this branch, so the test fails with a
		// clear message instead of hanging until the suite timeout.
		return protocol.InventoryReport{}, errors.New("collection did not run concurrently")
	case <-ctx.Done():
		return protocol.InventoryReport{}, ctx.Err()
	}
	s.mu.Lock()
	report := s.reports[endpointID]
	s.mu.Unlock()
	return report, nil
}

// TestForceCollectionRunsEndpointsConcurrently proves a workspace refresh overlaps
// Endpoint collections. Under a serial loop the first collection would block on the
// barrier until its own timeout, so the command would cost the sum of every
// Endpoint instead of the slowest one.
func TestForceCollectionRunsEndpointsConcurrently(t *testing.T) {
	stub := newBarrierStub(2)
	loaded, err := forceCollection(context.Background(), stub, "")
	if err != nil {
		t.Fatalf("forceCollection: %v", err)
	}
	if len(loaded.errors) != 0 {
		t.Fatalf("concurrent collection reported errors: %v", loaded.errors)
	}
	if len(loaded.reports) != 2 {
		t.Fatalf("reports=%d, want one per endpoint", len(loaded.reports))
	}
	if stub.maxInFlight < 2 {
		t.Fatalf("max in-flight collections=%d, want at least 2", stub.maxInFlight)
	}
	if !stub.deadlineSeen {
		t.Fatal("forced collection ran without a per-endpoint deadline")
	}
}

// TestForceCollectionBoundsConcurrency proves the worker pool caps concurrent
// collections, so a large fleet cannot open one provider discovery per Endpoint at
// once and exceed the Server's pending-collection capacity.
func TestForceCollectionBoundsConcurrency(t *testing.T) {
	stub := newBarrierStub(refreshConcurrency)
	stub.endpoints = nil
	stub.reports = make(map[string]protocol.InventoryReport)
	for index := 0; index < refreshConcurrency*2; index++ {
		endpointID := "endpoint-" + string(rune('a'+index))
		stub.endpoints = append(stub.endpoints, protocol.Endpoint{EndpointID: endpointID, Hostname: endpointID})
		stub.reports[endpointID] = scopeInventory("res-"+endpointID, "generation-1")
	}
	// The barrier expects only one pool's worth of arrivals, so the first batch
	// releases and the remaining Endpoints proceed in the next batch.
	loaded, err := forceCollection(context.Background(), stub, "")
	if err != nil {
		t.Fatalf("forceCollection: %v", err)
	}
	if len(loaded.reports) != len(stub.endpoints) {
		t.Fatalf("reports=%d, want %d", len(loaded.reports), len(stub.endpoints))
	}
	if stub.maxInFlight > refreshConcurrency {
		t.Fatalf("max in-flight collections=%d, want at most %d", stub.maxInFlight, refreshConcurrency)
	}
}

// TestForceCollectionIsolatesAHungEndpoint proves one Endpoint that never answers
// is reported as its own failure while the healthy Endpoints still render, so a
// single slow Endpoint cannot hide the rest of the fleet.
func TestForceCollectionIsolatesAHungEndpoint(t *testing.T) {
	stub := newBarrierStub(1)
	stub.blockOn = "endpoint-2"
	// The parent deadline stands in for the per-endpoint budget, so the test does
	// not wait for the production timeout.
	ctx, cancel := context.WithTimeout(context.Background(), 200*time.Millisecond)
	defer cancel()
	started := time.Now()
	loaded, err := forceCollection(ctx, stub, "")
	if err != nil {
		t.Fatalf("forceCollection: %v", err)
	}
	if elapsed := time.Since(started); elapsed > 3*time.Second {
		t.Fatalf("hung endpoint held the command for %s", elapsed)
	}
	if _, failed := loaded.errors["endpoint-2"]; !failed {
		t.Fatalf("hung endpoint was not reported: %v", loaded.errors)
	}
	if _, ok := loaded.reports["endpoint-1"]; !ok {
		t.Fatalf("healthy endpoint was hidden by the hung one: %v", loaded.reports)
	}
}

// TestForceCollectionUsesTheCommittedRefreshResponse proves the forced collection
// uses the document the Server returns after commit, so it does not spend a second
// round trip re-reading the same document.
func TestForceCollectionUsesTheCommittedRefreshResponse(t *testing.T) {
	stub := refreshScopeStub()
	stub.fresh["endpoint-1"] = scopeInventory("fresh-session", "fresh-generation")
	loaded, err := forceCollection(context.Background(), stub, "")
	if err != nil {
		t.Fatalf("forceCollection: %v", err)
	}
	if len(loaded.errors) != 0 {
		t.Fatalf("unexpected errors: %v", loaded.errors)
	}
	if stub.inventoryCalls != 0 {
		t.Fatalf("projection reads=%d, want none after a committed refresh", stub.inventoryCalls)
	}
	if got := loaded.reports["endpoint-1"].Sessions[0].ClusterSessionID; got != "fresh-session" {
		t.Fatalf("rendered session=%q, want the committed refresh document", got)
	}
}
