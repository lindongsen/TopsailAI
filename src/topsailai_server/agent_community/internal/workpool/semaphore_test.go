// Package workpool provides semaphore and pool tests.
package workpool

import (
	"context"
	"errors"
	"sync"
	"sync/atomic"
	"testing"
	"time"
)

// TestSemaphoreAcquireRelease verifies basic acquire and release.
func TestSemaphoreAcquireRelease(t *testing.T) {
	sem := NewSemaphore(2)

	ctx := context.Background()

	// Acquire first slot
	if err := sem.Acquire(ctx); err != nil {
		t.Fatalf("failed to acquire: %v", err)
	}
	if sem.Available() != 1 {
		t.Errorf("available = %d, want 1", sem.Available())
	}

	// Acquire second slot
	if err := sem.Acquire(ctx); err != nil {
		t.Fatalf("failed to acquire: %v", err)
	}
	if sem.Available() != 0 {
		t.Errorf("available = %d, want 0", sem.Available())
	}

	// Release one slot
	sem.Release()
	if sem.Available() != 1 {
		t.Errorf("available = %d, want 1", sem.Available())
	}

	// Release second slot
	sem.Release()
	if sem.Available() != 2 {
		t.Errorf("available = %d, want 2", sem.Available())
	}
}

// TestSemaphoreCapacity verifies capacity reporting.
func TestSemaphoreCapacity(t *testing.T) {
	sem := NewSemaphore(5)
	if sem.Capacity() != 5 {
		t.Errorf("capacity = %d, want 5", sem.Capacity())
	}
}

// TestSemaphoreAcquireTimeout verifies timeout behavior.
func TestSemaphoreAcquireTimeout(t *testing.T) {
	sem := NewSemaphore(1)

	// Acquire the only slot
	ctx := context.Background()
	if err := sem.Acquire(ctx); err != nil {
		t.Fatalf("failed to acquire: %v", err)
	}

	// Try to acquire with short timeout - should fail
	ctx2, cancel := context.WithTimeout(context.Background(), 50*time.Millisecond)
	defer cancel()

	err := sem.Acquire(ctx2)
	if err == nil {
		t.Error("expected timeout error")
	}
	if err != context.DeadlineExceeded {
		t.Errorf("expected DeadlineExceeded, got %v", err)
	}

	// Release and try again
	sem.Release()
	if err := sem.Acquire(ctx); err != nil {
		t.Fatalf("failed to acquire after release: %v", err)
	}
}

// TestSemaphoreAcquireWithTimeout verifies the convenience timeout method.
func TestSemaphoreAcquireWithTimeout(t *testing.T) {
	sem := NewSemaphore(1)

	// Acquire the only slot
	if err := sem.AcquireWithTimeout(time.Second); err != nil {
		t.Fatalf("failed to acquire: %v", err)
	}

	// Try with short timeout
	err := sem.AcquireWithTimeout(50 * time.Millisecond)
	if err == nil {
		t.Error("expected timeout error")
	}
}

// TestSemaphoreContextCancel verifies cancellation.
func TestSemaphoreContextCancel(t *testing.T) {
	sem := NewSemaphore(1)

	// Acquire the only slot
	ctx := context.Background()
	if err := sem.Acquire(ctx); err != nil {
		t.Fatalf("failed to acquire: %v", err)
	}

	// Try with cancelled context
	ctx2, cancel := context.WithCancel(context.Background())
	cancel() // Cancel immediately

	err := sem.Acquire(ctx2)
	if err == nil {
		t.Error("expected context cancelled error")
	}
	if err != context.Canceled {
		t.Errorf("expected Canceled, got %v", err)
	}
}

// TestSemaphoreConcurrentAccess verifies concurrent acquire/release.
func TestSemaphoreConcurrentAccess(t *testing.T) {
	sem := NewSemaphore(3)
	var wg sync.WaitGroup
	var acquired int32
	var maxAcquired int32

	for i := 0; i < 10; i++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			ctx := context.Background()
			if err := sem.Acquire(ctx); err != nil {
				t.Errorf("failed to acquire: %v", err)
				return
			}

			current := atomic.AddInt32(&acquired, 1)
			for {
				max := atomic.LoadInt32(&maxAcquired)
				if current > max {
					if atomic.CompareAndSwapInt32(&maxAcquired, max, current) {
						break
					}
				} else {
					break
				}
			}

			time.Sleep(10 * time.Millisecond)
			atomic.AddInt32(&acquired, -1)
			sem.Release()
		}()
	}

	wg.Wait()

	if maxAcquired > 3 {
		t.Errorf("max concurrent = %d, want <= 3", maxAcquired)
	}
	if sem.Available() != 3 {
		t.Errorf("final available = %d, want 3", sem.Available())
	}
}

// TestSemaphoreReleaseWithoutAcquire verifies release without acquire is safe.
func TestSemaphoreReleaseWithoutAcquire(t *testing.T) {
	sem := NewSemaphore(2)

	// Release without acquire should not panic
	sem.Release()
	if sem.Available() != 2 {
		t.Errorf("available = %d, want 2", sem.Available())
	}
}

// TestPoolAcquireRelease verifies pool acquire and release.
func TestPoolAcquireRelease(t *testing.T) {
	pool := NewPool(5, 3, 2)
	ctx := context.Background()

	if err := pool.Acquire(ctx, "user1", "group1"); err != nil {
		t.Fatalf("failed to acquire: %v", err)
	}

	stats := pool.GetStats()
	if stats.GlobalAvailable != 4 {
		t.Errorf("global available = %d, want 4", stats.GlobalAvailable)
	}
	if stats.PerUserAvailable["user1"] != 2 {
		t.Errorf("user available = %d, want 2", stats.PerUserAvailable["user1"])
	}
	if stats.PerGroupAvailable["group1"] != 1 {
		t.Errorf("group available = %d, want 1", stats.PerGroupAvailable["group1"])
	}

	pool.Release("user1", "group1", "")

	stats = pool.GetStats()
	if stats.GlobalAvailable != 5 {
		t.Errorf("global available after release = %d, want 5", stats.GlobalAvailable)
	}
}

// TestPoolAcquireTimeout verifies pool timeout behavior.
func TestPoolAcquireTimeout(t *testing.T) {
	pool := NewPool(1, 1, 1)
	ctx := context.Background()

	// Acquire the only global slot
	if err := pool.Acquire(ctx, "user1", "group1"); err != nil {
		t.Fatalf("failed to acquire: %v", err)
	}

	// Try to acquire with same user/group - should timeout
	ctx2, cancel := context.WithTimeout(context.Background(), 50*time.Millisecond)
	defer cancel()

	err := pool.Acquire(ctx2, "user1", "group1")
	if err == nil {
		t.Error("expected timeout error")
	}

	pool.Release("user1", "group1", "")
}

// TestPoolDifferentUsers verifies different users have independent semaphores.
func TestPoolDifferentUsers(t *testing.T) {
	pool := NewPool(5, 2, 2)
	ctx := context.Background()

	// User1 acquires
	if err := pool.Acquire(ctx, "user1", "group1"); err != nil {
		t.Fatalf("failed to acquire for user1: %v", err)
	}

	// User2 should be able to acquire independently
	if err := pool.Acquire(ctx, "user2", "group1"); err != nil {
		t.Fatalf("failed to acquire for user2: %v", err)
	}

	stats := pool.GetStats()
	if stats.PerUserAvailable["user1"] != 1 {
		t.Errorf("user1 available = %d, want 1", stats.PerUserAvailable["user1"])
	}
	if stats.PerUserAvailable["user2"] != 1 {
		t.Errorf("user2 available = %d, want 1", stats.PerUserAvailable["user2"])
	}

	pool.Release("user1", "group1", "")
	pool.Release("user2", "group1", "")
}

// TestPoolDifferentGroups verifies different groups have independent semaphores.
func TestPoolDifferentGroups(t *testing.T) {
	pool := NewPool(5, 2, 2)
	ctx := context.Background()

	// Group1 acquires
	if err := pool.Acquire(ctx, "user1", "group1"); err != nil {
		t.Fatalf("failed to acquire for group1: %v", err)
	}

	// Group2 should be able to acquire independently
	if err := pool.Acquire(ctx, "user1", "group2"); err != nil {
		t.Fatalf("failed to acquire for group2: %v", err)
	}

	stats := pool.GetStats()
	if stats.PerGroupAvailable["group1"] != 1 {
		t.Errorf("group1 available = %d, want 1", stats.PerGroupAvailable["group1"])
	}
	if stats.PerGroupAvailable["group2"] != 1 {
		t.Errorf("group2 available = %d, want 1", stats.PerGroupAvailable["group2"])
	}

	pool.Release("user1", "group1", "")
	pool.Release("user1", "group2", "")
}

// TestPoolConcurrentAccess verifies concurrent pool access.
func TestPoolConcurrentAccess(t *testing.T) {
	pool := NewPool(5, 3, 2)
	var wg sync.WaitGroup
	var successCount int32

	for i := 0; i < 20; i++ {
		wg.Add(1)
		go func(idx int) {
			defer wg.Done()
			userID := "user" + string(rune('0'+idx%3))
			groupID := "group" + string(rune('0'+idx%2))

			ctx, cancel := context.WithTimeout(context.Background(), 100*time.Millisecond)
			defer cancel()

			if err := pool.Acquire(ctx, userID, groupID); err != nil {
				return
			}

			atomic.AddInt32(&successCount, 1)
			time.Sleep(10 * time.Millisecond)
			pool.Release(userID, groupID, "")
		}(i)
	}

	wg.Wait()

	if successCount == 0 {
		t.Error("expected some successful acquisitions")
	}

	stats := pool.GetStats()
	if stats.GlobalAvailable != 5 {
		t.Errorf("final global available = %d, want 5", stats.GlobalAvailable)
	}
}

// TestPoolStats verifies stats reporting.
func TestPoolStats(t *testing.T) {
	pool := NewPool(10, 5, 5)
	ctx := context.Background()

	// Acquire some slots
	pool.Acquire(ctx, "user1", "group1")
	pool.Acquire(ctx, "user1", "group1")
	pool.Acquire(ctx, "user2", "group2")

	stats := pool.GetStats()

	if stats.GlobalCapacity != 10 {
		t.Errorf("global capacity = %d, want 10", stats.GlobalCapacity)
	}
	if stats.GlobalAvailable != 7 {
		t.Errorf("global available = %d, want 7", stats.GlobalAvailable)
	}
	if stats.PerUserAvailable["user1"] != 3 {
		t.Errorf("user1 available = %d, want 3", stats.PerUserAvailable["user1"])
	}
	if stats.PerUserAvailable["user2"] != 4 {
		t.Errorf("user2 available = %d, want 4", stats.PerUserAvailable["user2"])
	}
	if stats.PerGroupAvailable["group1"] != 3 {
		t.Errorf("group1 available = %d, want 3", stats.PerGroupAvailable["group1"])
	}
	if stats.PerGroupAvailable["group2"] != 4 {
		t.Errorf("group2 available = %d, want 4", stats.PerGroupAvailable["group2"])
	}

	pool.Release("user1", "group1", "")
	pool.Release("user1", "group1", "")
	pool.Release("user2", "group2", "")
}

// TestSemaphore_Acquire_AlreadyCancelledContext verifies Acquire fails immediately on a cancelled context.
func TestSemaphore_Acquire_AlreadyCancelledContext(t *testing.T) {
	sem := NewSemaphore(0)

	ctx, cancel := context.WithCancel(context.Background())
	cancel() // cancel before acquire

	err := sem.Acquire(ctx)
	if err == nil {
		t.Fatal("expected error on cancelled context")
	}
	if err != context.Canceled {
		t.Errorf("expected context.Canceled, got %v", err)
	}
}

// TestSemaphore_AcquireWithTimeout_ZeroTimeout verifies zero timeout returns an error.
func TestSemaphore_AcquireWithTimeout_ZeroTimeout(t *testing.T) {
	sem := NewSemaphore(1)

	// Exhaust the semaphore so the next acquire must wait.
	if err := sem.Acquire(context.Background()); err != nil {
		t.Fatalf("failed to acquire: %v", err)
	}
	defer sem.Release()

	err := sem.AcquireWithTimeout(0)
	if err == nil {
		t.Fatal("expected timeout error")
	}
	if err != context.DeadlineExceeded {
		t.Errorf("expected DeadlineExceeded, got %v", err)
	}
}

// TestPool_Acquire_PartialFailureRollback verifies that partial acquisition failures
// release already-acquired semaphores.
func TestPool_Acquire_PartialFailureRollback(t *testing.T) {
	pool := NewPool(5, 2, 2)

	// Exhaust the per-user semaphore for "user1".
	userSem := pool.getOrCreateUserSemaphore("user1")
	if err := userSem.Acquire(context.Background()); err != nil {
		t.Fatalf("failed to acquire user semaphore: %v", err)
	}
	if err := userSem.Acquire(context.Background()); err != nil {
		t.Fatalf("failed to acquire user semaphore: %v", err)
	}
	defer userSem.Release()
	defer userSem.Release()

	// Global should be acquired, then user acquire should fail and global released.
	ctx, cancel := context.WithTimeout(context.Background(), 100*time.Millisecond)
	defer cancel()
	err := pool.Acquire(ctx, "user1", "group1")
	if err == nil {
		t.Fatal("expected acquire to fail when user semaphore is exhausted")
	}

	stats := pool.GetStats()
	if stats.GlobalAvailable != 5 {
		t.Errorf("global available = %d, want 5 (rollback failed)", stats.GlobalAvailable)
	}

	// Release the user semaphore and exhaust the per-group semaphore for "group1".
	userSem.Release()
	userSem.Release()
	groupSem := pool.getOrCreateGroupSemaphore("group1")
	if err := groupSem.Acquire(context.Background()); err != nil {
		t.Fatalf("failed to acquire group semaphore: %v", err)
	}
	if err := groupSem.Acquire(context.Background()); err != nil {
		t.Fatalf("failed to acquire group semaphore: %v", err)
	}
	defer groupSem.Release()
	defer groupSem.Release()

	// Global and user should be acquired, then group acquire should fail and both released.
	ctx2, cancel2 := context.WithTimeout(context.Background(), 100*time.Millisecond)
	defer cancel2()
	err = pool.Acquire(ctx2, "user1", "group1")
	if err == nil {
		t.Fatal("expected acquire to fail when group semaphore is exhausted")
	}

	stats = pool.GetStats()
	if stats.GlobalAvailable != 5 {
		t.Errorf("global available = %d, want 5 (rollback failed)", stats.GlobalAvailable)
	}
	if stats.PerUserAvailable["user1"] != 2 {
		t.Errorf("user1 available = %d, want 2 (rollback failed)", stats.PerUserAvailable["user1"])
	}
}

// TestPool_AcquireWithTimeout_SuccessAndTimeout verifies both success and timeout paths.
func TestPool_AcquireWithTimeout_SuccessAndTimeout(t *testing.T) {
	pool := NewPool(1, 1, 1)

	// Success path.
	if err := pool.AcquireWithTimeout(100*time.Millisecond, "user1", "group1", "trace-1"); err != nil {
		t.Fatalf("failed to acquire: %v", err)
	}

	// Timeout path: global semaphore is already held.
	err := pool.AcquireWithTimeout(50*time.Millisecond, "user2", "group2", "trace-2")
	if err == nil {
		t.Fatal("expected timeout error")
	}
	if !errors.Is(err, ErrPoolLimitReached) || !errors.Is(err, context.DeadlineExceeded) {
		t.Errorf("expected ErrPoolLimitReached wrapping DeadlineExceeded, got %v", err)
	}

	pool.Release("user1", "group1", "")
}

// TestPool_Release_NonExistentUserGroup verifies releasing unknown user/group does not panic.
func TestPool_Release_NonExistentUserGroup(t *testing.T) {
	pool := NewPool(5, 5, 5)

	// Should not panic even though the user/group were never acquired.
	pool.Release("unknown-user", "unknown-group", "")

	stats := pool.GetStats()
	if stats.GlobalAvailable != 5 {
		t.Errorf("global available = %d, want 5", stats.GlobalAvailable)
	}
}

// TestPool_ZeroCapacities verifies behavior when all capacities are zero.
func TestPool_ZeroCapacities(t *testing.T) {
	pool := NewPool(0, 0, 0)

	stats := pool.GetStats()
	if stats.GlobalCapacity != 0 {
		t.Errorf("global capacity = %d, want 0", stats.GlobalCapacity)
	}
	if stats.GlobalAvailable != 0 {
		t.Errorf("global available = %d, want 0", stats.GlobalAvailable)
	}

	err := pool.AcquireWithTimeout(50*time.Millisecond, "user1", "group1", "")
	if err == nil {
		t.Fatal("expected timeout error with zero capacity")
	}
	if !errors.Is(err, ErrPoolLimitReached) || !errors.Is(err, context.DeadlineExceeded) {
		t.Errorf("expected ErrPoolLimitReached wrapping DeadlineExceeded, got %v", err)
	}
}

// TestPool_GetStats_NoDataRace verifies GetStats is safe under concurrent acquire/release.
func TestPool_GetStats_NoDataRace(t *testing.T) {
	pool := NewPool(10, 5, 5)
	var wg sync.WaitGroup

	for i := 0; i < 50; i++ {
		wg.Add(1)
		go func(idx int) {
			defer wg.Done()
			userID := "user" + string(rune('0'+idx%3))
			groupID := "group" + string(rune('0'+idx%2))

			ctx, cancel := context.WithTimeout(context.Background(), 100*time.Millisecond)
			defer cancel()

			if err := pool.Acquire(ctx, userID, groupID); err != nil {
				return
			}
			_ = pool.GetStats()
			pool.Release(userID, groupID, "")
		}(i)
	}

	for i := 0; i < 10; i++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			for j := 0; j < 100; j++ {
				_ = pool.GetStats()
			}
		}()
	}

	wg.Wait()
}

// TestPool_TryAcquire_SuccessAndFailure verifies the non-blocking TryAcquire path.
func TestPool_TryAcquire_SuccessAndFailure(t *testing.T) {
	pool := NewPool(1, 1, 1)

	// First acquire should succeed.
	if err := pool.TryAcquire("user1", "group1", "trace-1"); err != nil {
		t.Fatalf("expected successful try acquire, got %v", err)
	}

	stats := pool.GetStats()
	if stats.GlobalAvailable != 0 {
		t.Errorf("global available = %d, want 0", stats.GlobalAvailable)
	}

	// Second acquire should fail without blocking.
	err := pool.TryAcquire("user2", "group2", "trace-2")
	if err == nil {
		t.Fatal("expected ErrPoolLimitReached")
	}
	if !errors.Is(err, ErrPoolLimitReached) {
		t.Errorf("expected ErrPoolLimitReached, got %v", err)
	}

	pool.Release("user1", "group1", "trace-1")

	// After release, acquire should succeed again.
	if err := pool.TryAcquire("user2", "group2", "trace-3"); err != nil {
		t.Fatalf("expected successful try acquire after release, got %v", err)
	}
	pool.Release("user2", "group2", "trace-3")
}

// TestPool_TryAcquire_PartialFailureRollback verifies that a partial TryAcquire
// failure releases any slots that were already acquired.
func TestPool_TryAcquire_PartialFailureRollback(t *testing.T) {
	pool := NewPool(2, 2, 1)

	// Exhaust the per-group semaphore for "group1".
	groupSem := pool.getOrCreateGroupSemaphore("group1")
	if err := groupSem.Acquire(context.Background()); err != nil {
		t.Fatalf("failed to acquire group semaphore: %v", err)
	}
	defer groupSem.Release()

	// TryAcquire should acquire global and user slots, then fail on group and
	// roll back the previously acquired slots.
	err := pool.TryAcquire("user1", "group1", "trace-1")
	if err == nil {
		t.Fatal("expected ErrPoolLimitReached due to exhausted group semaphore")
	}
	if !errors.Is(err, ErrPoolLimitReached) {
		t.Errorf("expected ErrPoolLimitReached, got %v", err)
	}

	stats := pool.GetStats()
	if stats.GlobalAvailable != 2 {
		t.Errorf("global available = %d, want 2 (rollback failed)", stats.GlobalAvailable)
	}
	if stats.PerUserAvailable["user1"] != 2 {
		t.Errorf("user1 available = %d, want 2 (rollback failed)", stats.PerUserAvailable["user1"])
	}
}
