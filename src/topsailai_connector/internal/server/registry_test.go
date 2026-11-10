package server

import (
	"errors"
	"sync"
	"testing"
)

// fakeChannel is a Channel that records how often it was closed.
type fakeChannel struct {
	nodeID     string
	closeErr   error
	mutex      sync.Mutex
	closeCount int
}

// NodeID reports the identity this fake was built for.
func (f *fakeChannel) NodeID() string { return f.nodeID }

// Close records the call and returns the configured error.
func (f *fakeChannel) Close() error {
	f.mutex.Lock()
	defer f.mutex.Unlock()
	f.closeCount++
	return f.closeErr
}

// closes reports how many times Close was called.
func (f *fakeChannel) closes() int {
	f.mutex.Lock()
	defer f.mutex.Unlock()
	return f.closeCount
}

// TestRegistryRegisterAndLookup checks that a registered connection is found by
// its node id.
func TestRegistryRegisterAndLookup(t *testing.T) {
	registry := NewRegistry()
	channel := &fakeChannel{nodeID: "node_0123456789abcdefghijklmnop"}

	registration, replaced, err := registry.Register(channel)
	if err != nil {
		t.Fatalf("Register() = %v, want nil", err)
	}
	if replaced != nil {
		t.Fatalf("replaced = %v, want nil", replaced)
	}
	if registration.NodeID() != channel.nodeID {
		t.Fatalf("registration node id = %q, want %q", registration.NodeID(), channel.nodeID)
	}

	found, ok := registry.Lookup(channel.nodeID)
	if !ok {
		t.Fatalf("Lookup() ok = false, want true")
	}
	if found != channel {
		t.Fatalf("Lookup() = %v, want the registered channel", found)
	}
	if registry.Len() != 1 {
		t.Fatalf("Len() = %d, want 1", registry.Len())
	}
}

// TestRegistryLookupUnknownNode checks that an unknown node id reports absence
// rather than a nil channel that a caller might use.
func TestRegistryLookupUnknownNode(t *testing.T) {
	registry := NewRegistry()

	channel, ok := registry.Lookup("node_0123456789abcdefghijklmnop")
	if ok {
		t.Fatalf("Lookup() ok = true, want false")
	}
	if channel != nil {
		t.Fatalf("Lookup() = %v, want nil", channel)
	}
}

// TestRegistryRejectsNilChannel checks that a nil connection is refused, because
// a nil entry would answer Lookup with a live-looking absence.
func TestRegistryRejectsNilChannel(t *testing.T) {
	registry := NewRegistry()

	if _, _, err := registry.Register(nil); err == nil {
		t.Fatalf("Register(nil) = nil error, want a refusal")
	}
	if registry.Len() != 0 {
		t.Fatalf("Len() = %d, want 0", registry.Len())
	}
}

// TestRegistryRejectsInvalidNodeID checks that a malformed identity is refused
// before it becomes a routing key.
//
// The cases are the ones ValidateNodeID refuses: an empty value, a missing
// prefix, an empty body and a character outside the lowercase set. A short body
// is not refused here, because the validator does not enforce the documented
// 128 bit length; that gap is recorded as an issue rather than asserted as a
// rule this unit does not implement.
func TestRegistryRejectsInvalidNodeID(t *testing.T) {
	registry := NewRegistry()

	for _, nodeID := range []string{"", "not-a-node-id", "node_", "node_0123456789abcdef0123456789abcdeZ", "node_0123456789ABCDEF0123456789abcdef"} {
		t.Run(nodeID, func(t *testing.T) {
			channel := &fakeChannel{nodeID: nodeID}
			if _, _, err := registry.Register(channel); err == nil {
				t.Fatalf("Register(%q) = nil error, want a refusal", nodeID)
			}
		})
	}
}

// TestRegistryReconnectReplacesEntry checks that a second connection for one
// identity replaces the first and returns it for closing.
//
// One connection serves one Node: two live connections for one identity would be
// two answers to one request.
func TestRegistryReconnectReplacesEntry(t *testing.T) {
	registry := NewRegistry()
	first := &fakeChannel{nodeID: "node_0123456789abcdefghijklmnop"}
	second := &fakeChannel{nodeID: first.nodeID}

	if _, _, err := registry.Register(first); err != nil {
		t.Fatalf("Register(first) = %v, want nil", err)
	}
	_, replaced, err := registry.Register(second)
	if err != nil {
		t.Fatalf("Register(second) = %v, want nil", err)
	}
	if replaced != first {
		t.Fatalf("replaced = %v, want the first channel", replaced)
	}

	found, ok := registry.Lookup(first.nodeID)
	if !ok {
		t.Fatalf("Lookup() ok = false, want true")
	}
	if found != second {
		t.Fatalf("Lookup() = %v, want the second channel", found)
	}
	if registry.Len() != 1 {
		t.Fatalf("Len() = %d, want 1", registry.Len())
	}
}

// TestRegistryUnregisterRemovesOwnEntry checks that a registration removes the
// entry it installed.
func TestRegistryUnregisterRemovesOwnEntry(t *testing.T) {
	registry := NewRegistry()
	channel := &fakeChannel{nodeID: "node_0123456789abcdefghijklmnop"}

	registration, _, err := registry.Register(channel)
	if err != nil {
		t.Fatalf("Register() = %v, want nil", err)
	}
	if !registry.Unregister(registration) {
		t.Fatalf("Unregister() = false, want true")
	}
	if registry.Len() != 0 {
		t.Fatalf("Len() = %d, want 0", registry.Len())
	}
	if _, ok := registry.Lookup(channel.nodeID); ok {
		t.Fatalf("Lookup() ok = true, want false")
	}
}

// TestRegistryUnregisterTwiceIsSafe checks that a second removal reports false
// instead of failing, because a shutdown path may run twice.
func TestRegistryUnregisterTwiceIsSafe(t *testing.T) {
	registry := NewRegistry()
	channel := &fakeChannel{nodeID: "node_0123456789abcdefghijklmnop"}

	registration, _, err := registry.Register(channel)
	if err != nil {
		t.Fatalf("Register() = %v, want nil", err)
	}
	if !registry.Unregister(registration) {
		t.Fatalf("first Unregister() = false, want true")
	}
	if registry.Unregister(registration) {
		t.Fatalf("second Unregister() = true, want false")
	}
}

// TestRegistryStaleUnregisterKeepsReplacement checks that a replaced connection
// cannot evict the connection that replaced it.
//
// Without the generation check the cleanup of an old connection would take the
// live one out of service, and the symptom would be a Node that looks connected
// and answers node_offline.
func TestRegistryStaleUnregisterKeepsReplacement(t *testing.T) {
	registry := NewRegistry()
	first := &fakeChannel{nodeID: "node_0123456789abcdefghijklmnop"}
	second := &fakeChannel{nodeID: first.nodeID}

	firstRegistration, _, err := registry.Register(first)
	if err != nil {
		t.Fatalf("Register(first) = %v, want nil", err)
	}
	if _, _, err := registry.Register(second); err != nil {
		t.Fatalf("Register(second) = %v, want nil", err)
	}

	if registry.Unregister(firstRegistration) {
		t.Fatalf("Unregister(stale) = true, want false")
	}

	found, ok := registry.Lookup(first.nodeID)
	if !ok {
		t.Fatalf("Lookup() ok = false, want true")
	}
	if found != second {
		t.Fatalf("Lookup() = %v, want the second channel", found)
	}
}

// TestRegistryUnregisterUnknownRegistration checks that removing a registration
// the registry never issued reports false.
func TestRegistryUnregisterUnknownRegistration(t *testing.T) {
	registry := NewRegistry()

	if registry.Unregister(Registration{nodeID: "node_0123456789abcdefghijklmnop", generation: 7}) {
		t.Fatalf("Unregister(unknown) = true, want false")
	}
}

// TestRegistryCloseAllClosesEveryChannel checks that shutdown closes every
// connection and empties the registry.
func TestRegistryCloseAllClosesEveryChannel(t *testing.T) {
	registry := NewRegistry()
	first := &fakeChannel{nodeID: "node_0123456789abcdefghijklmnop"}
	second := &fakeChannel{nodeID: "node_ponmlkjihgfedcba9876543210"}

	for _, channel := range []*fakeChannel{first, second} {
		if _, _, err := registry.Register(channel); err != nil {
			t.Fatalf("Register() = %v, want nil", err)
		}
	}

	if err := registry.CloseAll(); err != nil {
		t.Fatalf("CloseAll() = %v, want nil", err)
	}
	if first.closes() != 1 || second.closes() != 1 {
		t.Fatalf("close counts = %d, %d, want 1, 1", first.closes(), second.closes())
	}
	if registry.Len() != 0 {
		t.Fatalf("Len() = %d, want 0", registry.Len())
	}
}

// TestRegistryCloseAllReportsFirstError checks that a failing close is reported
// while the remaining connections are still closed.
//
// A shutdown that stops at the first error leaves the remaining Nodes connected
// to a Server that is going away.
func TestRegistryCloseAllReportsFirstError(t *testing.T) {
	registry := NewRegistry()
	failing := &fakeChannel{nodeID: "node_0123456789abcdefghijklmnop", closeErr: errors.New("close failed")}
	healthy := &fakeChannel{nodeID: "node_ponmlkjihgfedcba9876543210"}

	for _, channel := range []*fakeChannel{failing, healthy} {
		if _, _, err := registry.Register(channel); err != nil {
			t.Fatalf("Register() = %v, want nil", err)
		}
	}

	if err := registry.CloseAll(); err == nil {
		t.Fatalf("CloseAll() = nil, want the close error")
	}
	if healthy.closes() != 1 {
		t.Fatalf("healthy close count = %d, want 1", healthy.closes())
	}
}

// TestRegistryConcurrentRegisterAndLookup checks that concurrent use does not
// race, which the race detector verifies when this test runs under -race.
func TestRegistryConcurrentRegisterAndLookup(t *testing.T) {
	registry := NewRegistry()
	const workers = 8

	var waitGroup sync.WaitGroup
	for index := 0; index < workers; index++ {
		waitGroup.Add(1)
		go func(index int) {
			defer waitGroup.Done()
			channel := &fakeChannel{nodeID: "node_0123456789abcdefghijklmnop"}
			registration, replaced, err := registry.Register(channel)
			if err != nil {
				return
			}
			if replaced != nil {
				replaced.Close()
			}
			registry.Lookup(channel.nodeID)
			registry.Len()
			registry.Unregister(registration)
		}(index)
	}
	waitGroup.Wait()
}
