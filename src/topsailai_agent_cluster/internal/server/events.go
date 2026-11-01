package server

import (
	"crypto/rand"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"net/http"
	"strconv"
	"sync"
	"time"

	serverstorage "topsailai_agent_cluster/internal/storage/server"
)

// Event is a latest-state invalidation and never contains historical payloads.
type Event struct {
	Type             string `json:"type,omitempty"`
	EndpointID       string `json:"endpoint_id"`
	SnapshotRevision int64  `json:"snapshot_revision"`
	ServerInstanceID string `json:"server_instance_id"`
	Sequence         uint64 `json:"sequence"`
}

// ManifestEntry identifies the latest persisted revision for one Endpoint.
type ManifestEntry struct {
	EndpointID       string `json:"endpoint_id"`
	SnapshotRevision int64  `json:"snapshot_revision"`
}

// Manifest is the bounded latest-state synchronization document.
type Manifest struct {
	ServerInstanceID string          `json:"server_instance_id"`
	Entries          []ManifestEntry `json:"entries"`
}

type eventSubscriber struct {
	ch       chan Event
	overflow bool
}

// EventBroker publishes bounded latest-state invalidations to SSE subscribers.
type EventBroker struct {
	mu          sync.Mutex
	instanceID  string
	sequence    uint64
	capacity    int
	subscribers map[*eventSubscriber]struct{}
}

// NewEventBroker creates a broker with a bounded subscriber queue.
func NewEventBroker(capacity int) *EventBroker {
	if capacity < 1 {
		capacity = 1
	}
	return &EventBroker{instanceID: newInstanceID(), capacity: capacity, subscribers: make(map[*eventSubscriber]struct{})}
}

// ServerInstanceID returns the identity used to detect a Server restart.
func (b *EventBroker) ServerInstanceID() string {
	b.mu.Lock()
	defer b.mu.Unlock()
	return b.instanceID
}

// Publish emits one invalidation after the corresponding state commit.
func (b *EventBroker) Publish(endpointID string, revision int64) {
	b.mu.Lock()
	defer b.mu.Unlock()
	b.sequence++
	event := Event{EndpointID: endpointID, SnapshotRevision: revision, ServerInstanceID: b.instanceID, Sequence: b.sequence}
	for subscriber := range b.subscribers {
		select {
		case subscriber.ch <- event:
		default:
			if subscriber.overflow {
				continue
			}
			subscriber.overflow = true
			for len(subscriber.ch) > 0 {
				<-subscriber.ch
			}
			resync := Event{Type: "resync_required", ServerInstanceID: b.instanceID, Sequence: b.sequence}
			subscriber.ch <- resync
			subscriber.overflow = false
		}
	}
}

// Subscribe returns a bounded event stream and a cleanup function.
func (b *EventBroker) Subscribe() (<-chan Event, func()) {
	b.mu.Lock()
	defer b.mu.Unlock()
	subscriber := &eventSubscriber{ch: make(chan Event, b.capacity)}
	b.subscribers[subscriber] = struct{}{}
	return subscriber.ch, func() {
		b.mu.Lock()
		defer b.mu.Unlock()
		if _, ok := b.subscribers[subscriber]; ok {
			delete(b.subscribers, subscriber)
			close(subscriber.ch)
		}
	}
}

// Manifest returns the current revision manifest from durable Server state.
func (b *EventBroker) Manifest(store *serverstorage.Store, endpointIDs []ManifestEntry) Manifest {
	return Manifest{ServerInstanceID: b.ServerInstanceID(), Entries: endpointIDs}
}

// EventHandler serves the SSE and manifest synchronization endpoints.
type EventHandler struct {
	Broker *EventBroker
	Store  *serverstorage.Store
}

// NewEventHandler constructs the latest-state event HTTP handler.
func NewEventHandler(broker *EventBroker, store *serverstorage.Store) http.Handler {
	return &EventHandler{Broker: broker, Store: store}
}

// ServeHTTP serves either /api/v1/events or /api/v1/manifest.
func (h *EventHandler) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	if h.Broker == nil {
		http.Error(w, "event broker unavailable", http.StatusServiceUnavailable)
		return
	}
	if r.URL.Path == "/api/v1/manifest" {
		h.manifest(w, r)
		return
	}
	if r.URL.Path != "/api/v1/events" {
		http.NotFound(w, r)
		return
	}
	if r.Method != http.MethodGet {
		http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
		return
	}
	stream, cleanup := h.Broker.Subscribe()
	defer cleanup()
	w.Header().Set("Content-Type", "text/event-stream")
	w.Header().Set("Cache-Control", "no-cache")
	flusher, ok := w.(http.Flusher)
	if !ok {
		http.Error(w, "streaming unsupported", http.StatusInternalServerError)
		return
	}
	for {
		select {
		case <-r.Context().Done():
			return
		case event, open := <-stream:
			if !open {
				return
			}
			data, _ := json.Marshal(event)
			eventName := event.Type
			if eventName == "" {
				eventName = "inventory_changed"
			}
			_, _ = fmt.Fprintf(w, "id: %d\nevent: %s\ndata: %s\n\n", event.Sequence, eventName, data)
			flusher.Flush()
		}
	}
}

func (h *EventHandler) manifest(w http.ResponseWriter, r *http.Request) {
	entries := []ManifestEntry{}
	if h.Store != nil {
		items, err := h.Store.ListInventoryRevisions(r.Context())
		if err != nil {
			http.Error(w, err.Error(), http.StatusInternalServerError)
			return
		}
		entries = make([]ManifestEntry, 0, len(items))
		for _, item := range items {
			entries = append(entries, ManifestEntry{EndpointID: item.EndpointID, SnapshotRevision: item.SnapshotRevision})
		}
	}
	_ = json.NewEncoder(w).Encode(Manifest{ServerInstanceID: h.Broker.ServerInstanceID(), Entries: entries})
}

func newInstanceID() string {
	var data [12]byte
	if _, err := rand.Read(data[:]); err != nil {
		return strconv.FormatInt(time.Now().UnixNano(), 10)
	}
	return hex.EncodeToString(data[:])
}
