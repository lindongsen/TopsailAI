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

// TestProjectCatalogOfflineAndPeerIsolation verifies a catalog reply is accepted
// only from the exact peer that was asked, never from another Endpoint or a newer
// connection generation of the same Endpoint.
func TestProjectCatalogOfflineAndPeerIsolation(t *testing.T) {
	s := NewServer(nil)
	if _, err := s.RequestProjectCatalog(context.Background(), "missing", protocol.ProjectCatalogQuery{}); err == nil {
		t.Fatal("offline accepted")
	}
	owner := &Peer{EndpointID: "a", ConnectionGeneration: 1}
	other := &Peer{EndpointID: "b", ConnectionGeneration: 1}
	response := make(chan protocol.ProjectCatalog, 1)
	s.pendingProjectCatalog = map[string]pendingProjectCatalogRequest{"r": {peer: owner, response: response}}
	frame := Frame{RequestID: "r", ProjectCatalog: &protocol.ProjectCatalog{ErrorCode: "test"}}
	s.deliverProjectCatalog(other, frame)
	s.deliverProjectCatalog(&Peer{EndpointID: "a", ConnectionGeneration: 2}, frame)
	if len(response) != 0 || len(s.pendingProjectCatalog) != 1 {
		t.Fatal("foreign response accepted")
	}
	s.deliverProjectCatalog(owner, frame)
	if len(response) != 1 || len(s.pendingProjectCatalog) != 0 {
		t.Fatal("owner response lost")
	}
}

// TestProjectCatalogChannelRoundTrip exercises real frames, cancellation and pending
// cleanup.
func TestProjectCatalogChannelRoundTrip(t *testing.T) {
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
		result <- endpoint.SendFrame(ctx, Frame{Type: FrameProjectCatalogResponse, RequestID: frame.RequestID, ProjectCatalog: &protocol.ProjectCatalog{Projects: []protocol.Project{{ProjectID: "pr-1", Name: "demo", Path: "/work/demo"}}}})
	}()
	catalog, err := s.RequestProjectCatalog(ctx, "e", protocol.ProjectCatalogQuery{})
	if err != nil || len(catalog.Projects) != 1 {
		t.Fatalf("%#v %v", catalog, err)
	}
	if err := <-result; err != nil {
		t.Fatal(err)
	}
	cancelled, stop := context.WithCancel(ctx)
	stop()
	if _, err := s.RequestProjectCatalog(cancelled, "e", protocol.ProjectCatalogQuery{}); err == nil {
		t.Fatal("cancellation ignored")
	}
	s.Mu.Lock()
	defer s.Mu.Unlock()
	if len(s.pendingProjectCatalog) != 0 {
		t.Fatal("pending request leaked")
	}
}

// TestProjectCatalogDisconnectFailsWaiters verifies a disconnected Endpoint reports
// endpoint_unavailable immediately instead of blocking until the deadline.
func TestProjectCatalogDisconnectFailsWaiters(t *testing.T) {
	s := NewServer(nil)
	response := make(chan protocol.ProjectCatalog, 1)
	s.pendingProjectCatalog = map[string]pendingProjectCatalogRequest{"r": {peer: &Peer{EndpointID: "a", ConnectionGeneration: 1}, response: response}}
	s.failPendingProjectCatalog("b")
	if len(response) != 0 {
		t.Fatal("foreign endpoint failed")
	}
	s.failPendingProjectCatalog("a")
	if len(response) != 1 {
		t.Fatal("waiter not released")
	}
	if result := <-response; result.ErrorCode != "endpoint_unavailable" {
		t.Fatalf("unexpected code %q", result.ErrorCode)
	}
	if len(s.pendingProjectCatalog) != 0 {
		t.Fatal("pending request leaked")
	}
}

// TestProjectCatalogCapacityBound verifies the pending bound rejects rather than
// queues.
func TestProjectCatalogCapacityBound(t *testing.T) {
	s := NewServer(nil)
	s.pendingProjectCatalog = make(map[string]pendingProjectCatalogRequest, maxPendingProjectCatalog)
	for i := 0; i < maxPendingProjectCatalog; i++ {
		s.pendingProjectCatalog[string(rune('a'+i%26))+string(rune('a'+i/26))] = pendingProjectCatalogRequest{peer: &Peer{EndpointID: "a", ConnectionGeneration: 1}, response: make(chan protocol.ProjectCatalog, 1)}
	}
	s.Active["a"] = &Peer{EndpointID: "a", ConnectionGeneration: 1}
	if _, err := s.RequestProjectCatalog(context.Background(), "a", protocol.ProjectCatalogQuery{}); err == nil {
		t.Fatal("capacity bound ignored")
	}
}
