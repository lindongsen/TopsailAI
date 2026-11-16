package genericcli

import (
	"context"
	"errors"
	"testing"
	"time"

	"topsailai_agent_cluster/internal/adapter"
	"topsailai_agent_cluster/internal/providercli"
)

// TestDiscoveryCycleCannotDelayAnOperatorRead proves the Endpoint's own periodic
// inventory collection never delays a command the operator is waiting for.
//
// This is the property the operator asked for: periodic reporting must not affect
// an operation. Waiting for capacity is not enough, because a background cycle
// that wins the race still makes the operator wait for it. The two classes must
// own separate slots, so holding every discovery slot leaves read capacity free.
func TestDiscoveryCycleCannotDelayAnOperatorRead(t *testing.T) {
	scheduler := mustScheduler(t, providercli.ConcurrencyLimits{Total: 4, Discovery: 1, Mutation: 1, Follow: 1})
	held, err := scheduler.acquire(classDiscovery)
	if err != nil {
		t.Fatalf("acquire the discovery slot: %v", err)
	}
	defer held()
	// The collection cycle now occupies the only discovery slot. An operator read
	// must still start immediately instead of queueing behind it.
	started := time.Now()
	ctx, cancel := context.WithTimeout(context.Background(), 2*time.Second)
	defer cancel()
	release, err := scheduler.acquireWithin(ctx, classRead)
	if err != nil {
		t.Fatalf("an operator read was refused while a collection cycle held discovery: %v", err)
	}
	release()
	if elapsed := time.Since(started); elapsed > 100*time.Millisecond {
		t.Fatalf("the operator read waited %v behind the collection cycle, want an immediate grant", elapsed)
	}
}

// TestReadClassIsIndependentOfDiscovery proves the split is symmetric: a busy
// read class does not block the periodic cycle either, so reporting keeps running
// while operators work.
func TestReadClassIsIndependentOfDiscovery(t *testing.T) {
	scheduler := mustScheduler(t, providercli.ConcurrencyLimits{Total: 4, Discovery: 1, Mutation: 1, Follow: 1})
	held, err := scheduler.acquire(classRead)
	if err != nil {
		t.Fatalf("acquire the read slot: %v", err)
	}
	defer held()
	release, err := scheduler.acquire(classDiscovery)
	if err != nil {
		t.Fatalf("the collection cycle was refused while a read held its slot: %v", err)
	}
	release()
}

// TestReadClassHasItsOwnBound proves the read class is bounded rather than
// unbounded, so a burst of operator reads cannot exhaust the Provider CLI.
func TestReadClassHasItsOwnBound(t *testing.T) {
	scheduler := mustScheduler(t, providercli.ConcurrencyLimits{Total: 8, Discovery: 1, Mutation: 1, Follow: 1})
	first, err := scheduler.acquire(classRead)
	if err != nil {
		t.Fatalf("acquire the first read slot: %v", err)
	}
	defer first()
	// mustScheduler passes Discovery as the read limit, so the second read must be
	// refused once the read class is full.
	if release, err := scheduler.acquire(classRead); err == nil {
		release()
		t.Fatal("the read class admitted more callers than its limit")
	} else if !errors.Is(err, ErrCapacity) {
		t.Fatalf("error = %v, want it to wrap ErrCapacity", err)
	}
}

// TestReadRefusalIsRecognisableThroughTheAdapterContract proves the Endpoint can
// tell a busy adapter from a broken provider without importing this package.
func TestReadRefusalIsRecognisableThroughTheAdapterContract(t *testing.T) {
	scheduler := mustScheduler(t, providercli.ConcurrencyLimits{Total: 8, Discovery: 1, Mutation: 1, Follow: 1})
	held, err := scheduler.acquire(classRead)
	if err != nil {
		t.Fatalf("acquire the read slot: %v", err)
	}
	defer held()
	_, err = scheduler.acquire(classRead)
	if !errors.Is(err, adapter.ErrBusy) {
		t.Fatalf("error = %v, want it to wrap adapter.ErrBusy", err)
	}
}

// TestReadWaitsInsideTheCallerBudget proves a read that collides with another
// read of the same class waits for the slot instead of failing outright, and
// still fails once its own budget expires.
func TestReadWaitsInsideTheCallerBudget(t *testing.T) {
	scheduler := mustScheduler(t, providercli.ConcurrencyLimits{Total: 8, Discovery: 1, Mutation: 1, Follow: 1})
	held, err := scheduler.acquire(classRead)
	if err != nil {
		t.Fatalf("acquire the read slot: %v", err)
	}
	ctx, cancel := context.WithTimeout(context.Background(), 2*time.Second)
	defer cancel()
	done := make(chan error, 1)
	go func() {
		release, err := scheduler.acquireWithin(ctx, classRead)
		if release != nil {
			release()
		}
		done <- err
	}()
	time.Sleep(50 * time.Millisecond)
	held()
	select {
	case err := <-done:
		if err != nil {
			t.Fatalf("the waiting read did not get the released slot: %v", err)
		}
	case <-time.After(2 * time.Second):
		t.Fatal("the waiting read never returned after the slot was released")
	}
}

// TestReadWaitHonoursAnExpiredBudget proves a read with an already expired budget
// fails with the context error instead of waiting forever.
func TestReadWaitHonoursAnExpiredBudget(t *testing.T) {
	scheduler := mustScheduler(t, providercli.ConcurrencyLimits{Total: 8, Discovery: 1, Mutation: 1, Follow: 1})
	held, err := scheduler.acquire(classRead)
	if err != nil {
		t.Fatalf("acquire the read slot: %v", err)
	}
	defer held()
	ctx, cancel := context.WithDeadline(context.Background(), time.Now().Add(-time.Second))
	defer cancel()
	if release, err := scheduler.acquireWithin(ctx, classRead); err == nil {
		release()
		t.Fatal("a read acquired capacity with an expired budget")
	} else if !errors.Is(err, context.DeadlineExceeded) {
		t.Fatalf("error = %v, want context.DeadlineExceeded", err)
	}
}
