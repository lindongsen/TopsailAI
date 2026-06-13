// Package workpool provides semaphore and pool tests.
package workpool

import (
	"context"
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
