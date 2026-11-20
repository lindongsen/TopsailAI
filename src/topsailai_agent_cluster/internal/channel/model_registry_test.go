package channel

import (
	"context"
	"net/http"
	"net/http/httptest"
	"testing"
	"time"

	"github.com/coder/websocket/wsjson"
	"topsailai_agent_cluster/internal/protocol"
)

// TestModelRegistryOfflineAndPeerIsolation verifies a registry reply is accepted
// only from the exact peer that was asked, never from another Endpoint or a newer
// connection generation of the same Endpoint.
//
// The registry is a machine-level read, so a reply from a different machine would
// describe a different set of models. Accepting it would let one Endpoint answer a
// question about another, which is exactly the isolation the channel exists to keep.
func TestModelRegistryOfflineAndPeerIsolation(t *testing.T) {
	s := NewServer(nil)
	if _, err := s.RequestModelRegistry(context.Background(), "missing", protocol.ModelRegistryQuery{}); err == nil {
		t.Fatal("offline accepted")
	}
	owner := &Peer{EndpointID: "a", ConnectionGeneration: 1}
	other := &Peer{EndpointID: "b", ConnectionGeneration: 1}
	response := make(chan protocol.ModelRegistry, 1)
	s.pendingModelRegistry = map[string]pendingModelRegistryRequest{"r": {peer: owner, response: response}}
	frame := Frame{RequestID: "r", ModelRegistry: &protocol.ModelRegistry{ErrorCode: "test"}}
	s.deliverModelRegistry(other, frame)
	s.deliverModelRegistry(&Peer{EndpointID: "a", ConnectionGeneration: 2}, frame)
	if len(response) != 0 || len(s.pendingModelRegistry) != 1 {
		t.Fatal("foreign response accepted")
	}
	s.deliverModelRegistry(owner, frame)
	if len(response) != 1 || len(s.pendingModelRegistry) != 0 {
		t.Fatal("owner response lost")
	}
}

// TestModelRegistryChannelRoundTrip exercises real frames, cancellation and pending
// cleanup.
func TestModelRegistryChannelRoundTrip(t *testing.T) {
	s := NewServer(nil)
	httpServer := httptest.NewServer(http.HandlerFunc(s.Handler))
	defer httpServer.Close()
	ctx, cancel := context.WithTimeout(context.Background(), time.Second*5)
	defer cancel()
	endpoint := &EndpointClient{EndpointID: "e", InstanceID: "i"}
	if err := endpoint.Dial(ctx, websocketAddress(httpServer.URL)); err != nil {
		t.Fatal(err)
	}
	defer endpoint.Close()
	result := make(chan error, 1)
	go func() {
		var frame Frame
		if err := wsjson.Read(ctx, endpoint.Conn, &frame); err != nil {
			result <- err
			return
		}
		// The reply carries a selection so the round trip proves the selection
		// survives the frame, not only the entry list.
		result <- endpoint.SendFrame(ctx, Frame{Type: FrameModelRegistryResponse, RequestID: frame.RequestID, ModelRegistry: &protocol.ModelRegistry{
			Entries:          []protocol.ModelRegistryEntry{{ModelProfileID: "mp-1", ProviderDisplayName: "demo", Available: true}},
			CurrentProfileID: "mp-1",
			CurrentSource:    protocol.ModelSourceWorkspace,
			ObservedAtMS:     1,
		}})
	}()
	registry, err := s.RequestModelRegistry(ctx, "e", protocol.ModelRegistryQuery{})
	if err != nil || len(registry.Entries) != 1 || registry.CurrentProfileID != "mp-1" {
		t.Fatalf("%#v %v", registry, err)
	}
	if err := <-result; err != nil {
		t.Fatal(err)
	}
	cancelled, stop := context.WithCancel(ctx)
	stop()
	if _, err := s.RequestModelRegistry(cancelled, "e", protocol.ModelRegistryQuery{}); err == nil {
		t.Fatal("cancellation ignored")
	}
	s.Mu.Lock()
	defer s.Mu.Unlock()
	if len(s.pendingModelRegistry) != 0 {
		t.Fatal("pending request leaked")
	}
}

// TestModelRegistryDisconnectFailsWaiters verifies a disconnected Endpoint reports
// endpoint_unavailable immediately instead of blocking until the deadline.
//
// A registry read is a live provider query, so a disconnected Endpoint can never
// answer it. Waiting for the deadline would delay an error the caller must see now.
func TestModelRegistryDisconnectFailsWaiters(t *testing.T) {
	s := NewServer(nil)
	response := make(chan protocol.ModelRegistry, 1)
	s.pendingModelRegistry = map[string]pendingModelRegistryRequest{"r": {peer: &Peer{EndpointID: "a", ConnectionGeneration: 1}, response: response}}
	s.failPendingModelRegistry("b")
	if len(response) != 0 {
		t.Fatal("foreign endpoint failed")
	}
	s.failPendingModelRegistry("a")
	if len(response) != 1 {
		t.Fatal("waiter not released")
	}
	if result := <-response; result.ErrorCode != "endpoint_unavailable" {
		t.Fatalf("unexpected code %q", result.ErrorCode)
	}
	if len(s.pendingModelRegistry) != 0 {
		t.Fatal("pending request leaked")
	}
}

// TestModelRegistryCapacityBound verifies the pending bound rejects rather than
// queues. A registry read starts a provider process, so an unbounded backlog would
// let one operator multiply provider cost.
func TestModelRegistryCapacityBound(t *testing.T) {
	s := NewServer(nil)
	s.pendingModelRegistry = make(map[string]pendingModelRegistryRequest, maxPendingModelRegistry)
	for i := 0; i < maxPendingModelRegistry; i++ {
		s.pendingModelRegistry[string(rune('a'+i%26))+string(rune('a'+i/26))] = pendingModelRegistryRequest{peer: &Peer{EndpointID: "a", ConnectionGeneration: 1}, response: make(chan protocol.ModelRegistry, 1)}
	}
	s.Active["a"] = &Peer{EndpointID: "a", ConnectionGeneration: 1}
	if _, err := s.RequestModelRegistry(context.Background(), "a", protocol.ModelRegistryQuery{}); err == nil {
		t.Fatal("capacity bound ignored")
	}
}
