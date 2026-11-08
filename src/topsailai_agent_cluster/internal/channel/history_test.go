package channel

import (
	"context"
	"github.com/coder/websocket/wsjson"
	"net/http"
	"net/http/httptest"
	"testing"
	"time"
	"topsailai_agent_cluster/internal/protocol"
)

// TestHistoryOfflineAndPeerIsolation verifies a history reply is accepted only
// from the exact peer that was asked, never from another Endpoint or a newer
// connection generation of the same Endpoint.
func TestHistoryOfflineAndPeerIsolation(t *testing.T) {
	s := NewServer(nil)
	if _, err := s.RequestHistory(context.Background(), "missing", protocol.HistoryQuery{}); err == nil {
		t.Fatal("offline accepted")
	}
	owner := &Peer{EndpointID: "a", ConnectionGeneration: 1}
	other := &Peer{EndpointID: "b", ConnectionGeneration: 1}
	response := make(chan protocol.HistoryResult, 1)
	s.pendingHistory = map[string]pendingHistoryRequest{"r": {peer: owner, response: response}}
	frame := Frame{RequestID: "r", HistoryResult: &protocol.HistoryResult{ErrorCode: "test"}}
	s.deliverHistory(other, frame)
	s.deliverHistory(&Peer{EndpointID: "a", ConnectionGeneration: 2}, frame)
	if len(response) != 0 || len(s.pendingHistory) != 1 {
		t.Fatal("foreign response accepted")
	}
	s.deliverHistory(owner, frame)
	if len(response) != 1 || len(s.pendingHistory) != 0 {
		t.Fatal("owner response lost")
	}
}

// TestHistoryChannelRoundTrip exercises real frames, cancellation and pending cleanup.
func TestHistoryChannelRoundTrip(t *testing.T) {
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
		result <- endpoint.SendFrame(ctx, Frame{Type: FrameHistoryResponse, RequestID: frame.RequestID, HistoryResult: &protocol.HistoryResult{Rows: []protocol.HistoryRow{{ProviderSessionID: "wa-1"}}}})
	}()
	history, err := s.RequestHistory(ctx, "e", protocol.HistoryQuery{})
	if err != nil || len(history.Rows) != 1 {
		t.Fatalf("%#v %v", history, err)
	}
	if err := <-result; err != nil {
		t.Fatal(err)
	}
	cancelled, stop := context.WithCancel(ctx)
	stop()
	if _, err := s.RequestHistory(cancelled, "e", protocol.HistoryQuery{}); err == nil {
		t.Fatal("cancellation ignored")
	}
	s.Mu.Lock()
	defer s.Mu.Unlock()
	if len(s.pendingHistory) != 0 {
		t.Fatal("pending request leaked")
	}
}

// TestHistoryDisconnectFailsWaiters verifies a disconnected Endpoint reports
// endpoint_unavailable immediately instead of blocking until the deadline.
func TestHistoryDisconnectFailsWaiters(t *testing.T) {
	s := NewServer(nil)
	response := make(chan protocol.HistoryResult, 1)
	s.pendingHistory = map[string]pendingHistoryRequest{"r": {peer: &Peer{EndpointID: "a", ConnectionGeneration: 1}, response: response}}
	s.failPendingHistory("b")
	if len(response) != 0 {
		t.Fatal("foreign endpoint failed")
	}
	s.failPendingHistory("a")
	if len(response) != 1 {
		t.Fatal("waiter not released")
	}
	if result := <-response; result.ErrorCode != "endpoint_unavailable" {
		t.Fatalf("unexpected code %q", result.ErrorCode)
	}
	if len(s.pendingHistory) != 0 {
		t.Fatal("pending request leaked")
	}
}

// TestHistoryCapacityBound verifies the pending bound rejects rather than queues.
func TestHistoryCapacityBound(t *testing.T) {
	s := NewServer(nil)
	s.pendingHistory = make(map[string]pendingHistoryRequest, maxPendingHistory)
	for i := 0; i < maxPendingHistory; i++ {
		s.pendingHistory[string(rune('a'+i%26))+string(rune('a'+i/26))] = pendingHistoryRequest{peer: &Peer{EndpointID: "a", ConnectionGeneration: 1}, response: make(chan protocol.HistoryResult, 1)}
	}
	s.Active["a"] = &Peer{EndpointID: "a", ConnectionGeneration: 1}
	if _, err := s.RequestHistory(context.Background(), "a", protocol.HistoryQuery{}); err == nil {
		t.Fatal("capacity bound ignored")
	}
}
