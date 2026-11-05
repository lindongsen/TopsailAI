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

// TestLaunchOfflineAndPeerIsolation verifies no cross-peer correlation acceptance.
func TestLaunchOfflineAndPeerIsolation(t *testing.T) {
	s := NewServer(nil)
	if _, err := s.RequestLaunchOptions(context.Background(), "missing", protocol.LaunchQuery{}); err == nil {
		t.Fatal("offline accepted")
	}
	owner := &Peer{EndpointID: "a", ConnectionGeneration: 1}
	other := &Peer{EndpointID: "b", ConnectionGeneration: 1}
	response := make(chan protocol.LaunchOptions, 1)
	s.pendingLaunch = map[string]pendingLaunchRequest{"r": {peer: owner, response: response}}
	frame := Frame{RequestID: "r", LaunchOptions: &protocol.LaunchOptions{ErrorCode: "test"}}
	s.deliverLaunch(other, frame)
	s.deliverLaunch(&Peer{EndpointID: "a", ConnectionGeneration: 2}, frame)
	if len(response) != 0 || len(s.pendingLaunch) != 1 {
		t.Fatal("foreign response accepted")
	}
	s.deliverLaunch(owner, frame)
	if len(response) != 1 || len(s.pendingLaunch) != 0 {
		t.Fatal("owner response lost")
	}
}

// TestLaunchChannelRoundTrip exercises real frames and pending cleanup.
func TestLaunchChannelRoundTrip(t *testing.T) {
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
		result <- endpoint.SendFrame(ctx, Frame{Type: FrameLaunchResponse, RequestID: frame.RequestID, LaunchOptions: &protocol.LaunchOptions{Projects: []protocol.Project{{Path: "/work/工程"}}}})
	}()
	options, err := s.RequestLaunchOptions(ctx, "e", protocol.LaunchQuery{AdapterID: "a"})
	if err != nil || len(options.Projects) != 1 {
		t.Fatalf("%#v %v", options, err)
	}
	if err := <-result; err != nil {
		t.Fatal(err)
	}
	cancelled, stop := context.WithCancel(ctx)
	stop()
	if _, err := s.RequestLaunchOptions(cancelled, "e", protocol.LaunchQuery{}); err == nil {
		t.Fatal("cancellation ignored")
	}
	s.Mu.Lock()
	defer s.Mu.Unlock()
	if len(s.pendingLaunch) != 0 {
		t.Fatal("pending request leaked")
	}
}
