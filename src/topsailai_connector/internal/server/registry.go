package server

import (
	"fmt"
	"sync"

	"topsailai_connector/internal/security"
)

// Channel is one live Node connection as the registry sees it.
//
// The registry needs two things from a connection: the identity the Node reported
// and a way to close it. Everything else about the transport stays outside this
// interface, so the routing logic can be tested without a socket and a later
// transport change does not touch it.
type Channel interface {
	// NodeID is the identity the Node reported in hello. It is the value the
	// Server validated the tunnel token for, never a value a request may set.
	NodeID() string
	// Close releases the connection. It must be safe to call more than once,
	// because a replaced connection is closed by the registry and again by the
	// goroutine that owns it.
	Close() error
}

// Registration is the handle a connection keeps so it can later remove exactly
// its own entry.
//
// The handle carries a generation number instead of the connection itself, so
// removal never compares two interface values. Comparing interfaces panics when
// the dynamic type is not comparable, and a panic on a shutdown path is a crash
// caused by a cleanup routine.
type Registration struct {
	nodeID     string
	generation uint64
}

// NodeID returns the identity this registration was issued for.
func (r Registration) NodeID() string {
	return r.nodeID
}

// Registry maps a node id to its live connection.
//
// It is memory only. Persisting it would create a record of which Nodes exist and
// when they were last seen, which is a privacy decision this design does not
// make, and a stored record of a Node is the first step toward a stored record of
// its token.
//
// The registry holds no scope table and no permission table. It answers one
// question, "is there a live connection for this node id", and it cannot answer
// any other, so a compromised Server cannot use it to widen a caller's authority.
type Registry struct {
	mutex       sync.Mutex
	entries     map[string]registryEntry
	generations uint64
}

// registryEntry is one live connection plus the generation that installed it.
type registryEntry struct {
	channel    Channel
	generation uint64
}

// NewRegistry returns an empty registry.
func NewRegistry() *Registry {
	return &Registry{entries: make(map[string]registryEntry)}
}

// Register installs a connection and returns its registration plus the connection
// it replaced.
//
// The replaced connection is returned rather than closed here, and the caller
// closes it after Register returns. Closing it while the lock is held would
// deadlock the moment a transport's Close calls back into Unregister, which is
// exactly what a well behaved connection does on shutdown.
//
// A Node that reconnects replaces its entry: one connection serves one Node, so
// two live connections for one identity would be two answers to one request.
func (r *Registry) Register(channel Channel) (Registration, Channel, error) {
	if channel == nil {
		return Registration{}, nil, fmt.Errorf("channel is nil")
	}
	nodeID := channel.NodeID()
	if err := security.ValidateNodeID(nodeID); err != nil {
		return Registration{}, nil, err
	}

	r.mutex.Lock()
	defer r.mutex.Unlock()

	if r.entries == nil {
		r.entries = make(map[string]registryEntry)
	}
	r.generations++
	registration := Registration{nodeID: nodeID, generation: r.generations}

	previous := r.entries[nodeID]
	r.entries[nodeID] = registryEntry{channel: channel, generation: registration.generation}

	return registration, previous.channel, nil
}

// Unregister removes the entry a registration installed, and reports whether it
// removed anything.
//
// The generation is compared, so a replaced connection that finishes shutting
// down later cannot evict the connection that replaced it. Without that check the
// cleanup of an old connection would silently take the live one out of service,
// and the symptom would be a Node that looks connected and answers node_offline.
func (r *Registry) Unregister(registration Registration) bool {
	r.mutex.Lock()
	defer r.mutex.Unlock()

	entry, present := r.entries[registration.nodeID]
	if !present || entry.generation != registration.generation {
		return false
	}
	delete(r.entries, registration.nodeID)
	return true
}

// Lookup returns the live connection for a node id.
//
// The second result is false when no connection is registered, so a caller cannot
// mistake a nil channel for a live one.
func (r *Registry) Lookup(nodeID string) (Channel, bool) {
	r.mutex.Lock()
	defer r.mutex.Unlock()

	entry, present := r.entries[nodeID]
	if !present {
		return nil, false
	}
	return entry.channel, true
}

// Len reports how many Nodes are connected. It exists for a startup report and a
// test, not for routing.
func (r *Registry) Len() int {
	r.mutex.Lock()
	defer r.mutex.Unlock()
	return len(r.entries)
}

// CloseAll closes every connection and empties the registry.
//
// Every connection is closed even when an earlier one fails, because a shutdown
// that stops at the first error leaves the remaining Nodes connected to a Server
// that is going away. The first error is returned so the failure is not silent.
func (r *Registry) CloseAll() error {
	r.mutex.Lock()
	entries := r.entries
	r.entries = make(map[string]registryEntry)
	r.mutex.Unlock()

	var first error
	for _, entry := range entries {
		if err := entry.channel.Close(); err != nil && first == nil {
			first = err
		}
	}
	return first
}
