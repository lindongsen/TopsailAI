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

// TestModelCatalogOfflineAndPeerIsolation verifies a catalog reply is accepted
// only from the exact peer that was asked, never from another Endpoint or a newer
// connection generation of the same Endpoint.
func TestModelCatalogOfflineAndPeerIsolation(t *testing.T) {
	s := NewServer(nil)
	if _, err := s.RequestModelCatalog(context.Background(), "missing", protocol.ModelCatalogQuery{}); err == nil {
		t.Fatal("offline accepted")
	}
	owner := &Peer{EndpointID: "a", ConnectionGeneration: 1}
	other := &Peer{EndpointID: "b", ConnectionGeneration: 1}
	response := make(chan protocol.ModelCatalog, 1)
	s.pendingModelCatalog = map[string]pendingModelCatalogRequest{"r": {peer: owner, response: response}}
	frame := Frame{RequestID: "r", ModelCatalog: &protocol.ModelCatalog{ErrorCode: "test"}}
	s.deliverModelCatalog(other, frame)
	s.deliverModelCatalog(&Peer{EndpointID: "a", ConnectionGeneration: 2}, frame)
	if len(response) != 0 || len(s.pendingModelCatalog) != 1 {
		t.Fatal("foreign response accepted")
	}
	s.deliverModelCatalog(owner, frame)
	if len(response) != 1 || len(s.pendingModelCatalog) != 0 {
		t.Fatal("owner response lost")
	}
}

// TestModelCatalogChannelRoundTrip exercises real frames, cancellation and pending
// cleanup.
func TestModelCatalogChannelRoundTrip(t *testing.T) {
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
		result <- endpoint.SendFrame(ctx, Frame{Type: FrameModelCatalogResponse, RequestID: frame.RequestID, ModelCatalog: &protocol.ModelCatalog{Profiles: []protocol.ModelProfile{{ModelProfileID: "mp-1"}}}})
	}()
	catalog, err := s.RequestModelCatalog(ctx, "e", protocol.ModelCatalogQuery{})
	if err != nil || len(catalog.Profiles) != 1 {
		t.Fatalf("%#v %v", catalog, err)
	}
	if err := <-result; err != nil {
		t.Fatal(err)
	}
	cancelled, stop := context.WithCancel(ctx)
	stop()
	if _, err := s.RequestModelCatalog(cancelled, "e", protocol.ModelCatalogQuery{}); err == nil {
		t.Fatal("cancellation ignored")
	}
	s.Mu.Lock()
	defer s.Mu.Unlock()
	if len(s.pendingModelCatalog) != 0 {
		t.Fatal("pending request leaked")
	}
}

// TestModelCatalogDisconnectFailsWaiters verifies a disconnected Endpoint reports
// endpoint_unavailable immediately instead of blocking until the deadline.
func TestModelCatalogDisconnectFailsWaiters(t *testing.T) {
	s := NewServer(nil)
	response := make(chan protocol.ModelCatalog, 1)
	s.pendingModelCatalog = map[string]pendingModelCatalogRequest{"r": {peer: &Peer{EndpointID: "a", ConnectionGeneration: 1}, response: response}}
	s.failPendingModelCatalog("b")
	if len(response) != 0 {
		t.Fatal("foreign endpoint failed")
	}
	s.failPendingModelCatalog("a")
	if len(response) != 1 {
		t.Fatal("waiter not released")
	}
	if result := <-response; result.ErrorCode != "endpoint_unavailable" {
		t.Fatalf("unexpected code %q", result.ErrorCode)
	}
	if len(s.pendingModelCatalog) != 0 {
		t.Fatal("pending request leaked")
	}
}

// TestModelCatalogCapacityBound verifies the pending bound rejects rather than
// queues.
func TestModelCatalogCapacityBound(t *testing.T) {
	s := NewServer(nil)
	s.pendingModelCatalog = make(map[string]pendingModelCatalogRequest, maxPendingModelCatalog)
	for i := 0; i < maxPendingModelCatalog; i++ {
		s.pendingModelCatalog[string(rune('a'+i%26))+string(rune('a'+i/26))] = pendingModelCatalogRequest{peer: &Peer{EndpointID: "a", ConnectionGeneration: 1}, response: make(chan protocol.ModelCatalog, 1)}
	}
	s.Active["a"] = &Peer{EndpointID: "a", ConnectionGeneration: 1}
	if _, err := s.RequestModelCatalog(context.Background(), "a", protocol.ModelCatalogQuery{}); err == nil {
		t.Fatal("capacity bound ignored")
	}
}
