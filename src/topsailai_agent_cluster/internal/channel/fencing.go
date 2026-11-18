package channel

import (
	"errors"
	"sync"
)

// ErrFenced indicates that a connection generation is no longer authoritative.
var ErrFenced = errors.New("channel connection is fenced")

// ErrOffline indicates that no authoritative Endpoint connection is available.
var ErrOffline = errors.New("endpoint is offline")

// ErrFollowCapacity indicates that the Server already holds the maximum number
// of concurrent follow streams.
//
// It is a distinct value rather than a formatted string because the HTTP layer
// must report it as its own condition. Reporting it as endpoint_offline told the
// operator the Endpoint was unreachable while it was healthy and answering, which
// sent every investigation to the transport instead of to the capacity limit.
var ErrFollowCapacity = errors.New("follow capacity exceeded")

// Fence assigns monotonically increasing authority independently per Endpoint.
type Fence struct {
	mu          sync.RWMutex
	generations map[string]int64
}

// NewFence constructs a connection fence.
func NewFence() *Fence { return &Fence{generations: make(map[string]int64)} }

// Acquire makes a new connection authoritative for one Endpoint.
func (f *Fence) Acquire(endpointID string) int64 {
	f.mu.Lock()
	defer f.mu.Unlock()
	f.generations[endpointID]++
	return f.generations[endpointID]
}

// Current reports the current generation for one Endpoint.
func (f *Fence) Current(endpointID string) int64 {
	f.mu.RLock()
	defer f.mu.RUnlock()
	return f.generations[endpointID]
}

// Check rejects a stale connection generation for one Endpoint.
func (f *Fence) Check(endpointID string, generation int64) error {
	if generation < 1 || generation != f.Current(endpointID) {
		return ErrFenced
	}
	return nil
}
