package security

import (
	"errors"
	"fmt"
	"sync"
	"time"
)

// DefaultReplayWindow is the default freshness window a verifier accepts.
//
// Sixty seconds is long enough for a caller whose clock is a few seconds off and
// short enough that a captured proof stops being useful quickly. The verifier owns
// the value; a request cannot choose or widen it.
const DefaultReplayWindow = 60 * time.Second

// MaxReplayWindow bounds a configured window.
//
// A window measured in hours is not a freshness check: it turns a captured proof
// into a credential that works for the rest of the day, which is the failure the
// window exists to prevent.
const MaxReplayWindow = 10 * time.Minute

// DefaultReplayCapacity is the default number of unexpired nonces one verifier
// records.
//
// The capacity is a memory bound, not a traffic limit: at 32 bytes of nonce plus
// bookkeeping, 65536 entries stay in the low megabytes. A verifier that needs more
// states it explicitly rather than growing without a bound.
const DefaultReplayCapacity = 65536

// ErrReplayDetected reports a nonce that was already recorded inside the window.
var ErrReplayDetected = errors.New("authentication proof was already used")

// ErrReplayCacheFull reports a cache that cannot admit another nonce without
// evicting one that is still live.
//
// The refusal is deliberate. Evicting a live nonce would reopen replay for the
// proof it belonged to, so a full cache fails closed instead of silently weakening
// the check it exists to provide.
var ErrReplayCacheFull = errors.New("replay cache is full")

// ReplayCache records the nonces one verifier has admitted inside its window.
//
// The cache is keyed by credential key identifier and nonce, so two credentials that
// happen to use the same nonce do not collide. It is in-memory only: persisting it
// would create a record of every request, and the design keeps no such record.
//
// A cache is safe for concurrent use. The check-and-insert is one operation under
// one lock, so two concurrent copies of one proof cannot both be admitted.
type ReplayCache struct {
	mutex    sync.Mutex
	entries  map[replayKey]int64
	windowMS int64
	capacity int
	now      func() time.Time
}

// replayKey is the identity of one admitted proof.
type replayKey struct {
	keyID string
	nonce string
}

// NewReplayCache builds a cache with a window and a capacity.
//
// A zero window or a zero capacity is a configuration failure rather than a default,
// because a verifier that silently substituted a default would be a verifier whose
// operator cannot state what it enforces. The caller passes the values it validated.
func NewReplayCache(window time.Duration, capacity int) (*ReplayCache, error) {
	if window <= 0 {
		return nil, fmt.Errorf("replay window must be positive, got %s", window)
	}
	if window > MaxReplayWindow {
		return nil, fmt.Errorf("replay window %s exceeds the maximum %s", window, MaxReplayWindow)
	}
	if capacity <= 0 {
		return nil, fmt.Errorf("replay capacity must be positive, got %d", capacity)
	}
	return &ReplayCache{
		entries:  make(map[replayKey]int64, capacity),
		windowMS: window.Milliseconds(),
		capacity: capacity,
		now:      time.Now,
	}, nil
}

// Admit records a nonce and reports whether it was fresh.
//
// The order is fixed: expired entries are removed first, then the nonce is looked
// up, then it is inserted. A nonce that is already present is a replay and is not
// re-inserted, so its original expiry is preserved rather than extended by a replay
// attempt.
//
// A full cache refuses the request instead of evicting a live entry. The caller
// treats that refusal as a refusal, never as an admission.
func (c *ReplayCache) Admit(keyID string, nonce string) error {
	if c == nil {
		return ErrReplayCacheFull
	}
	if keyID == "" || nonce == "" {
		return fmt.Errorf("replay key is incomplete")
	}

	c.mutex.Lock()
	defer c.mutex.Unlock()

	nowMS := c.now().UnixMilli()
	c.removeExpired(nowMS)

	key := replayKey{keyID: keyID, nonce: nonce}
	if _, present := c.entries[key]; present {
		return ErrReplayDetected
	}
	if len(c.entries) >= c.capacity {
		return ErrReplayCacheFull
	}
	c.entries[key] = nowMS + c.windowMS
	return nil
}

// removeExpired drops every entry whose expiry has passed.
//
// The scan is bounded by the capacity, which is the reason the capacity exists: an
// unbounded map would make this scan the per-request cost that grows with traffic.
func (c *ReplayCache) removeExpired(nowMS int64) {
	for key, expiry := range c.entries {
		if expiry <= nowMS {
			delete(c.entries, key)
		}
	}
}

// Len reports how many unexpired entries the cache holds. It exists for a startup
// report and a test, not for the request path.
func (c *ReplayCache) Len() int {
	if c == nil {
		return 0
	}
	c.mutex.Lock()
	defer c.mutex.Unlock()
	c.removeExpired(c.now().UnixMilli())
	return len(c.entries)
}

// Capacity reports the configured capacity.
func (c *ReplayCache) Capacity() int {
	if c == nil {
		return 0
	}
	return c.capacity
}

// Window reports the configured window.
func (c *ReplayCache) Window() time.Duration {
	if c == nil {
		return 0
	}
	return time.Duration(c.windowMS) * time.Millisecond
}
