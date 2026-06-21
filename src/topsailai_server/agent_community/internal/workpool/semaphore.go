// Package workpool provides semaphore-based concurrency control for agent processing.
package workpool

import (
	"context"
	"errors"
	"fmt"
	"sync"
	"time"

	"github.com/topsailai/agent-community/pkg/logger"
)

// ErrPoolLimitReached indicates that a work-pool semaphore could not be
// acquired because the concurrency limit for the node, user, or group has been
// reached. Callers that consume NATS messages should negatively acknowledge the
// message so JetStream can redeliver it later rather than treating it as a
// processing failure.
var ErrPoolLimitReached = errors.New("work pool limit reached")
// Semaphore provides a counting semaphore using channels.
type Semaphore struct {
	ch chan struct{}
}

// NewSemaphore creates a new semaphore with the given capacity.
func NewSemaphore(capacity int) *Semaphore {
	return &Semaphore{
		ch: make(chan struct{}, capacity),
	}
}

// Acquire acquires a semaphore slot, blocking until one is available or context is done.
func (s *Semaphore) Acquire(ctx context.Context) error {
	select {
	case s.ch <- struct{}{}:
		return nil
	case <-ctx.Done():
		return ctx.Err()
	}
}

// AcquireWithTimeout acquires a semaphore slot with a timeout.
func (s *Semaphore) AcquireWithTimeout(timeout time.Duration) error {
	ctx, cancel := context.WithTimeout(context.Background(), timeout)
	defer cancel()
	return s.Acquire(ctx)
}

// TryAcquire attempts to acquire a semaphore slot without blocking.
// It returns true if a slot was acquired, false if the semaphore is at capacity.
func (s *Semaphore) TryAcquire() bool {
	select {
	case s.ch <- struct{}{}:
		return true
	default:
		return false
	}
}

// Release releases a semaphore slot.
func (s *Semaphore) Release() {
	select {
	case <-s.ch:
	default:
		// Prevent panic if Release is called without Acquire
	}
}

// Available returns the number of available slots.
func (s *Semaphore) Available() int {
	return cap(s.ch) - len(s.ch)
}

// Capacity returns the total capacity of the semaphore.
func (s *Semaphore) Capacity() int {
	return cap(s.ch)
}

// Pool manages multiple semaphores for global, per-user, and per-group concurrency.
type Pool struct {
	global   *Semaphore
	perUser  map[string]*Semaphore
	perGroup map[string]*Semaphore
	mu       sync.RWMutex

	globalCapacity   int
	perUserCapacity  int
	perGroupCapacity int
}

// NewPool creates a new work pool with the given capacities.
func NewPool(globalCapacity, perUserCapacity, perGroupCapacity int) *Pool {
	return &Pool{
		global:           NewSemaphore(globalCapacity),
		perUser:          make(map[string]*Semaphore),
		perGroup:         make(map[string]*Semaphore),
		globalCapacity:   globalCapacity,
		perUserCapacity:  perUserCapacity,
		perGroupCapacity: perGroupCapacity,
	}
}

// Acquire acquires slots from global, per-user, and per-group semaphores.
// All must be acquired atomically to prevent partial acquisition.
func (p *Pool) Acquire(ctx context.Context, userID, groupID string) error {
	// First acquire global semaphore
	if err := p.global.Acquire(ctx); err != nil {
		return fmt.Errorf("failed to acquire global semaphore: %w", err)
	}

	// Get or create per-user semaphore
	userSem := p.getOrCreateUserSemaphore(userID)
	if err := userSem.Acquire(ctx); err != nil {
		p.global.Release()
		return fmt.Errorf("failed to acquire per-user semaphore: %w", err)
	}

	// Get or create per-group semaphore
	groupSem := p.getOrCreateGroupSemaphore(groupID)
	if err := groupSem.Acquire(ctx); err != nil {
		userSem.Release()
		p.global.Release()
		return fmt.Errorf("failed to acquire per-group semaphore: %w", err)
	}

	return nil
}

// AcquireWithTimeout acquires slots with a timeout. When the timeout expires
// because the pool is at capacity, the returned error wraps ErrPoolLimitReached
// so callers can distinguish saturation from other failures.
func (p *Pool) AcquireWithTimeout(timeout time.Duration, userID, groupID, traceID string) error {
	logger.DebugM("workpool", traceID, "pool acquiring",
		"user_id", userID,
		"group_id", groupID,
		"global_available", p.global.Available(),
		"global_capacity", p.global.Capacity(),
	)

	start := time.Now()
	ctx, cancel := context.WithTimeout(context.Background(), timeout)
	defer cancel()

	err := p.Acquire(ctx, userID, groupID)
	waitMs := time.Since(start).Milliseconds()

	if err != nil {
		logger.WarnM("workpool", traceID, "pool acquire timeout",
			"user_id", userID,
			"group_id", groupID,
			"error", err.Error(),
			"wait_ms", waitMs,
		)
		p.LogStats(traceID)
		if errors.Is(err, context.DeadlineExceeded) {
			return fmt.Errorf("%w: %w", ErrPoolLimitReached, err)
		}
		return err
	}

	logger.DebugM("workpool", traceID, "pool acquired",
		"user_id", userID,
		"group_id", groupID,
		"wait_ms", waitMs,
		"global_available", p.global.Available(),
	)
	return nil
}

// TryAcquire attempts to acquire slots from global, per-user, and per-group
// semaphores without blocking. If any semaphore is at capacity, all already-
// acquired slots are released and ErrPoolLimitReached is returned. This avoids
// holding a goroutine waiting while the pool is saturated and lets NATS
// JetStream redeliver the message later.
func (p *Pool) TryAcquire(userID, groupID, traceID string) error {
	logger.DebugM("workpool", traceID, "pool try acquiring",
		"user_id", userID,
		"group_id", groupID,
		"global_available", p.global.Available(),
		"global_capacity", p.global.Capacity(),
	)

	if !p.global.TryAcquire() {
		logger.WarnM("workpool", traceID, "pool global limit reached",
			"user_id", userID,
			"group_id", groupID,
		)
		p.LogStats(traceID)
		return ErrPoolLimitReached
	}

	userSem := p.getOrCreateUserSemaphore(userID)
	if !userSem.TryAcquire() {
		p.global.Release()
		logger.WarnM("workpool", traceID, "pool per-user limit reached",
			"user_id", userID,
			"group_id", groupID,
		)
		p.LogStats(traceID)
		return ErrPoolLimitReached
	}

	groupSem := p.getOrCreateGroupSemaphore(groupID)
	if !groupSem.TryAcquire() {
		userSem.Release()
		p.global.Release()
		logger.WarnM("workpool", traceID, "pool per-group limit reached",
			"user_id", userID,
			"group_id", groupID,
		)
		p.LogStats(traceID)
		return ErrPoolLimitReached
	}

	logger.DebugM("workpool", traceID, "pool try acquired",
		"user_id", userID,
		"group_id", groupID,
		"global_available", p.global.Available(),
	)
	return nil
}

// Release releases slots from global, per-user, and per-group semaphores.
func (p *Pool) Release(userID, groupID, traceID string) {
	p.global.Release()

	if userSem := p.getUserSemaphore(userID); userSem != nil {
		userSem.Release()
	}

	if groupSem := p.getGroupSemaphore(groupID); groupSem != nil {
		groupSem.Release()
	}

	logger.DebugM("workpool", traceID, "pool released",
		"user_id", userID,
		"group_id", groupID,
		"global_available", p.global.Available(),
	)
}

// getOrCreateUserSemaphore gets or creates a per-user semaphore.
func (p *Pool) getOrCreateUserSemaphore(userID string) *Semaphore {
	p.mu.Lock()
	defer p.mu.Unlock()

	if sem, exists := p.perUser[userID]; exists {
		return sem
	}

	sem := NewSemaphore(p.perUserCapacity)
	p.perUser[userID] = sem
	return sem
}

// getOrCreateGroupSemaphore gets or creates a per-group semaphore.
func (p *Pool) getOrCreateGroupSemaphore(groupID string) *Semaphore {
	p.mu.Lock()
	defer p.mu.Unlock()

	if sem, exists := p.perGroup[groupID]; exists {
		return sem
	}

	sem := NewSemaphore(p.perGroupCapacity)
	p.perGroup[groupID] = sem
	return sem
}

// getUserSemaphore gets a per-user semaphore (read-only).
func (p *Pool) getUserSemaphore(userID string) *Semaphore {
	p.mu.RLock()
	defer p.mu.RUnlock()

	if sem, exists := p.perUser[userID]; exists {
		return sem
	}
	return nil
}

// getGroupSemaphore gets a per-group semaphore (read-only).
func (p *Pool) getGroupSemaphore(groupID string) *Semaphore {
	p.mu.RLock()
	defer p.mu.RUnlock()

	if sem, exists := p.perGroup[groupID]; exists {
		return sem
	}
	return nil
}

// Stats returns current pool statistics.
type Stats struct {
	GlobalAvailable   int            `json:"global_available"`
	GlobalCapacity    int            `json:"global_capacity"`
	PerUserAvailable  map[string]int `json:"per_user_available"`
	PerGroupAvailable map[string]int `json:"per_group_available"`
}

// GetStats returns current pool statistics.
func (p *Pool) GetStats() Stats {
	p.mu.RLock()
	defer p.mu.RUnlock()

	stats := Stats{
		GlobalAvailable:   p.global.Available(),
		GlobalCapacity:    p.global.Capacity(),
		PerUserAvailable:  make(map[string]int),
		PerGroupAvailable: make(map[string]int),
	}

	for userID, sem := range p.perUser {
		stats.PerUserAvailable[userID] = sem.Available()
	}

	for groupID, sem := range p.perGroup {
		stats.PerGroupAvailable[groupID] = sem.Available()
	}

	return stats
}

// LogStats logs current pool statistics at INFO level.
func (p *Pool) LogStats(traceID string) {
	stats := p.GetStats()
	logger.InfoM("workpool", traceID, "pool stats",
		"global_available", stats.GlobalAvailable,
		"global_capacity", stats.GlobalCapacity,
		"per_user_available", stats.PerUserAvailable,
		"per_group_available", stats.PerGroupAvailable,
	)
}
