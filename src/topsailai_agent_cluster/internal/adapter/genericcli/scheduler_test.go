package genericcli

import (
	"context"
	"errors"
	"testing"
	"time"

	"topsailai_agent_cluster/internal/adapter"
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

// TestSchedulerCapacityErrorIsRecognisableThroughTheAdapterContract proves the
// capacity condition is reachable through the sentinel the Endpoint owns.
//
// The Endpoint must not import this implementation package to recognise a busy
// adapter, so the check it performs is errors.Is(err, adapter.ErrBusy). If
// ErrCapacity stopped wrapping that sentinel, every capacity collision would fall
// back to the provider-failure code and the operator would again be told the
// target could not be observed.
func TestSchedulerCapacityErrorIsRecognisableThroughTheAdapterContract(t *testing.T) {
	scheduler := mustScheduler(t, providercli.ConcurrencyLimits{Total: 1, Discovery: 1, Mutation: 1, Follow: 1})
	release, err := scheduler.acquire(classDiscovery)
	if err != nil {
		t.Fatalf("acquire first slot: %v", err)
	}
	defer release()
	_, err = scheduler.acquire(classDiscovery)
	if err == nil {
		t.Fatal("second acquire succeeded with no capacity")
	}
	if !errors.Is(err, adapter.ErrBusy) {
		t.Fatalf("capacity error = %v, want it to wrap adapter.ErrBusy", err)
	}
	if !errors.Is(err, ErrCapacity) {
		t.Fatalf("capacity error = %v, want it to keep wrapping ErrCapacity", err)
	}
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

// mustScheduler builds a scheduler with a read limit that matches the discovery
// limit, so a test that holds one class slot cannot be refused by the read class
// for an unrelated reason. Tests that need a different read limit call
// newScheduler directly.
func mustScheduler(t *testing.T, limits providercli.ConcurrencyLimits) *scheduler {
	t.Helper()
	scheduler, err := newScheduler(limits, limits.Discovery)
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

// TestReadCapacityIsIndependentOfMutationAndFollowCapacity proves the read class
// is not merely renamed discovery: it is also independent of the other two
// classes, so a long follow stream cannot delay an operator read either.
func TestReadCapacityIsIndependentOfMutationAndFollowCapacity(t *testing.T) {
	limits := providercli.ConcurrencyLimits{Total: 4, Discovery: 1, Mutation: 1, Follow: 1}
	scheduler, err := newScheduler(limits, 1)
	if err != nil {
		t.Fatalf("newScheduler: %v", err)
	}
	heldMutation, err := scheduler.acquire(classMutation)
	if err != nil {
		t.Fatalf("acquire mutation: %v", err)
	}
	defer heldMutation()
	heldFollow, err := scheduler.acquire(classFollow)
	if err != nil {
		t.Fatalf("acquire follow: %v", err)
	}
	defer heldFollow()
	release, err := scheduler.acquire(classRead)
	if err != nil {
		t.Fatalf("a read was refused while mutation and follow were held: %v", err)
	}
	release()
}

// TestNewSchedulerRejectsANonPositiveReadLimit proves the read limit is validated
// like every other limit, so a zero value cannot silently create an unbounded or
// permanently refusing class.
func TestNewSchedulerRejectsANonPositiveReadLimit(t *testing.T) {
	limits := providercli.ConcurrencyLimits{Total: 4, Discovery: 1, Mutation: 1, Follow: 1}
	for _, readLimit := range []int{0, -1} {
		if _, err := newScheduler(limits, readLimit); err == nil {
			t.Fatalf("read limit %d was accepted", readLimit)
		}
	}
}

// TestAcquireWithinBudgetRefusesAfterBudget proves a follow that cannot get a slot
// is refused instead of waiting without limit.
//
// The negative assertion is the load-bearing one. The Endpoint classifies a follow
// failure by checking context.DeadlineExceeded before adapter.ErrBusy, so an error
// that carried the deadline sentinel would be reported to the operator as
// "cancelled" and a capacity refusal would read as a stream that ended. The budget
// expiry must therefore wrap ErrCapacity and nothing else.
func TestAcquireWithinBudgetRefusesAfterBudget(t *testing.T) {
	scheduler := mustScheduler(t, providercli.ConcurrencyLimits{Total: 4, Discovery: 1, Mutation: 1, Follow: 1})
	held, err := scheduler.acquire(classFollow)
	if err != nil {
		t.Fatalf("acquire follow: %v", err)
	}
	defer held()
	started := time.Now()
	_, err = scheduler.acquireWithinBudget(context.Background(), classFollow, 50*time.Millisecond)
	if err == nil {
		t.Fatal("a follow was admitted while the only follow slot was held")
	}
	if !errors.Is(err, ErrCapacity) {
		t.Fatalf("error = %v, want it to wrap ErrCapacity", err)
	}
	if !errors.Is(err, adapter.ErrBusy) {
		t.Fatalf("error = %v, want it to wrap adapter.ErrBusy so the Endpoint reports adapter_busy", err)
	}
	if errors.Is(err, context.DeadlineExceeded) {
		t.Fatalf("error = %v must not wrap context.DeadlineExceeded, because the Endpoint checks that before ErrBusy and would report cancelled", err)
	}
	if errors.Is(err, context.Canceled) {
		t.Fatalf("error = %v must not wrap context.Canceled", err)
	}
	if elapsed := time.Since(started); elapsed > 5*time.Second {
		t.Fatalf("refusal took %s, want it bounded by the budget", elapsed)
	}
}

// TestAcquireWithinBudgetReportsParentCancellation proves a cancelled parent is
// still reported as cancellation rather than as a capacity refusal, so an operator
// who stopped watching is not told the adapter was busy.
func TestAcquireWithinBudgetReportsParentCancellation(t *testing.T) {
	scheduler := mustScheduler(t, providercli.ConcurrencyLimits{Total: 4, Discovery: 1, Mutation: 1, Follow: 1})
	held, err := scheduler.acquire(classFollow)
	if err != nil {
		t.Fatalf("acquire follow: %v", err)
	}
	defer held()
	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	_, err = scheduler.acquireWithinBudget(ctx, classFollow, time.Minute)
	if err == nil {
		t.Fatal("a cancelled parent still admitted a follow")
	}
	if !errors.Is(err, context.Canceled) {
		t.Fatalf("error = %v, want it to wrap context.Canceled", err)
	}
}

// TestAcquireWithinBudgetAdmitsWhenSlotFrees proves the budget is a wait rather
// than an immediate refusal, so a follow that collides with a stream that is just
// finishing still starts.
func TestAcquireWithinBudgetAdmitsWhenSlotFrees(t *testing.T) {
	scheduler := mustScheduler(t, providercli.ConcurrencyLimits{Total: 4, Discovery: 1, Mutation: 1, Follow: 1})
	held, err := scheduler.acquire(classFollow)
	if err != nil {
		t.Fatalf("acquire follow: %v", err)
	}
	go func() {
		time.Sleep(30 * time.Millisecond)
		held()
	}()
	release, err := scheduler.acquireWithinBudget(context.Background(), classFollow, 5*time.Second)
	if err != nil {
		t.Fatalf("a follow was refused although the slot was released inside the budget: %v", err)
	}
	release()
}
