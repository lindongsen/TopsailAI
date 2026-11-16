package genericcli

import (
	"context"
	"errors"
	"testing"
	"time"

	"topsailai_agent_cluster/internal/providercli"
)

func TestSchedulerRejectsTotalSaturationWithoutBlocking(t *testing.T) {
	scheduler := mustScheduler(t, providercli.ConcurrencyLimits{Total: 1, Discovery: 1, Mutation: 1, Follow: 1})
	release, err := scheduler.acquire(classDiscovery)
	if err != nil {
		t.Fatalf("acquire first slot: %v", err)
	}
	defer release()
	if _, err := scheduler.acquire(classMutation); !errors.Is(err, ErrCapacity) {
		t.Fatalf("second acquire error = %v, want ErrCapacity", err)
	}
}

func TestSchedulerRejectsClassSaturationAndRestoresTotalSlot(t *testing.T) {
	scheduler := mustScheduler(t, providercli.ConcurrencyLimits{Total: 2, Discovery: 1, Mutation: 1, Follow: 1})
	releaseDiscovery, err := scheduler.acquire(classDiscovery)
	if err != nil {
		t.Fatalf("acquire discovery: %v", err)
	}
	defer releaseDiscovery()
	if _, err := scheduler.acquire(classDiscovery); !errors.Is(err, ErrCapacity) {
		t.Fatalf("second discovery error = %v, want ErrCapacity", err)
	}
	releaseMutation, err := scheduler.acquire(classMutation)
	if err != nil {
		t.Fatalf("class rejection leaked total capacity: %v", err)
	}
	releaseMutation()
}

func TestSchedulerReleaseIsIdempotent(t *testing.T) {
	scheduler := mustScheduler(t, providercli.ConcurrencyLimits{Total: 1, Discovery: 1, Mutation: 1, Follow: 1})
	release, err := scheduler.acquire(classFollow)
	if err != nil {
		t.Fatalf("acquire follow: %v", err)
	}
	release()
	release()
	next, err := scheduler.acquire(classFollow)
	if err != nil {
		t.Fatalf("acquire after duplicate release: %v", err)
	}
	next()
}

func TestSchedulersHaveIndependentCapacity(t *testing.T) {
	limits := providercli.ConcurrencyLimits{Total: 1, Discovery: 1, Mutation: 1, Follow: 1}
	first := mustScheduler(t, limits)
	second := mustScheduler(t, limits)
	releaseFirst, err := first.acquire(classMutation)
	if err != nil {
		t.Fatalf("acquire first scheduler: %v", err)
	}
	defer releaseFirst()
	releaseSecond, err := second.acquire(classMutation)
	if err != nil {
		t.Fatalf("first scheduler consumed second capacity: %v", err)
	}
	releaseSecond()
}

func TestEffectiveConcurrencyUsesPositiveMinimum(t *testing.T) {
	limits, err := effectiveConcurrency(
		providercli.ConcurrencyLimits{Total: 12, Discovery: 8, Mutation: 6, Follow: 4},
		providercli.ConcurrencyLimits{Total: 10, Discovery: 5, Mutation: 5, Follow: 3},
		providercli.ConcurrencyLimits{Total: 7, Discovery: 6, Mutation: 2, Follow: 2},
	)
	if err != nil {
		t.Fatalf("effectiveConcurrency: %v", err)
	}
	want := providercli.ConcurrencyLimits{Total: 7, Discovery: 5, Mutation: 2, Follow: 2}
	if limits != want {
		t.Fatalf("limits = %+v, want %+v", limits, want)
	}
}

func TestEffectiveConcurrencyRejectsInvalidInput(t *testing.T) {
	valid := providercli.ConcurrencyLimits{Total: 1, Discovery: 1, Mutation: 1, Follow: 1}
	_, err := effectiveConcurrency(valid, providercli.ConcurrencyLimits{}, valid)
	if err == nil {
		t.Fatal("invalid adapter limits were accepted")
	}
}

func mustScheduler(t *testing.T, limits providercli.ConcurrencyLimits) *scheduler {
	t.Helper()
	scheduler, err := newScheduler(limits)
	if err != nil {
		t.Fatalf("newScheduler: %v", err)
	}
	return scheduler
}

// TestAcquireWithinWaitsForAReleasedSlot proves a caller that arrives while the
// one discovery slot is held waits for it instead of failing outright. Before
// this wait existed, a read that collided with the collection cycle failed, which
// is why resume, history and model reads failed intermittently.
func TestAcquireWithinWaitsForAReleasedSlot(t *testing.T) {
	scheduler := mustScheduler(t, providercli.ConcurrencyLimits{Total: 1, Discovery: 1, Mutation: 1, Follow: 1})
	held, err := scheduler.acquire(classDiscovery)
	if err != nil {
		t.Fatalf("acquire the held slot: %v", err)
	}
	const holdFor = 30 * time.Millisecond
	go func() {
		time.Sleep(holdFor)
		held()
	}()
	ctx, cancel := context.WithTimeout(context.Background(), 2*time.Second)
	defer cancel()
	started := time.Now()
	release, err := scheduler.acquireWithin(ctx, classDiscovery)
	elapsed := time.Since(started)
	if err != nil {
		t.Fatalf("acquireWithin gave up instead of waiting: %v", err)
	}
	defer release()
	if elapsed < holdFor {
		t.Fatalf("acquireWithin returned after %v, want it to wait at least %v for the released slot", elapsed, holdFor)
	}
}

// TestAcquireWithinFailsWhenTheBudgetExpires is the near-miss baseline: waiting
// must stay bounded by the caller's own budget, and the error must name both the
// capacity refusal and the expired budget so a caller can tell a busy adapter
// from a broken provider.
func TestAcquireWithinFailsWhenTheBudgetExpires(t *testing.T) {
	scheduler := mustScheduler(t, providercli.ConcurrencyLimits{Total: 1, Discovery: 1, Mutation: 1, Follow: 1})
	release, err := scheduler.acquire(classDiscovery)
	if err != nil {
		t.Fatalf("acquire the held slot: %v", err)
	}
	defer release()
	ctx, cancel := context.WithDeadline(context.Background(), time.Now().Add(-time.Second))
	defer cancel()
	// The call runs on its own goroutine so a missing budget check fails the test
	// instead of hanging the suite forever.
	type outcome struct {
		release func()
		err     error
	}
	done := make(chan outcome, 1)
	go func() {
		release, err := scheduler.acquireWithin(ctx, classDiscovery)
		done <- outcome{release: release, err: err}
	}()
	select {
	case got := <-done:
		if got.release != nil {
			got.release()
		}
		if got.err == nil {
			t.Fatal("acquireWithin succeeded with an expired budget and no capacity")
		}
		if !errors.Is(got.err, ErrCapacity) {
			t.Fatalf("error = %v, want it to wrap ErrCapacity", got.err)
		}
		if !errors.Is(got.err, context.DeadlineExceeded) {
			t.Fatalf("error = %v, want it to wrap context.DeadlineExceeded", got.err)
		}
	case <-time.After(2 * time.Second):
		t.Fatal("acquireWithin ignored the expired budget and kept waiting")
	}
}
