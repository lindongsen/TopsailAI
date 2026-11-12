package channel

import (
	"context"
	"net/http"
	"net/http/httptest"
	"sync"
	"testing"
	"time"
)

// disconnectRecord captures one disconnect notification.
type disconnectRecord struct {
	peer         Peer
	observedAtMS int64
}

// TestDisconnectNotifiesOnlyAuthoritativePeer verifies that a fenced older
// connection cannot report its replacement as disconnected.
func TestDisconnectNotifiesOnlyAuthoritativePeer(t *testing.T) {
	server := NewServer(nil)
	var mu sync.Mutex
	records := make([]disconnectRecord, 0, 2)
	server.OnDisconnect = func(peer Peer, observedAtMS int64) {
		mu.Lock()
		defer mu.Unlock()
		records = append(records, disconnectRecord{peer: peer, observedAtMS: observedAtMS})
	}
	httpServer := httptest.NewServer(http.HandlerFunc(server.Handler))
	defer httpServer.Close()
	address := websocketAddress(httpServer.URL)
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()

	first := &EndpointClient{EndpointID: "endpoint-1", InstanceID: "instance-1"}
	if err := first.Dial(ctx, address); err != nil {
		t.Fatal(err)
	}
	second := &EndpointClient{EndpointID: "endpoint-1", InstanceID: "instance-2"}
	if err := second.Dial(ctx, address); err != nil {
		t.Fatal(err)
	}
	// Closing the fenced first connection must not notify for the live peer. The
	// server already closed it, so a close error is expected here.
	_ = first.Close()
	time.Sleep(100 * time.Millisecond)
	mu.Lock()
	if len(records) != 0 {
		mu.Unlock()
		t.Fatalf("fenced disconnect produced notifications: %+v", records)
	}
	mu.Unlock()

	if err := second.Close(); err != nil {
		t.Fatal(err)
	}
	deadline := time.Now().Add(3 * time.Second)
	for time.Now().Before(deadline) {
		mu.Lock()
		count := len(records)
		mu.Unlock()
		if count > 0 {
			break
		}
		time.Sleep(20 * time.Millisecond)
	}
	mu.Lock()
	defer mu.Unlock()
	if len(records) != 1 {
		t.Fatalf("notifications=%d, want exactly one: %+v", len(records), records)
	}
	if records[0].peer.InstanceID != "instance-2" {
		t.Fatalf("notified instance=%q, want instance-2", records[0].peer.InstanceID)
	}
	if records[0].observedAtMS <= 0 {
		t.Fatalf("observed_at_ms=%d, want a positive timestamp", records[0].observedAtMS)
	}
}

// TestDisconnectCallbackRunsOutsideChannelLock verifies that a slow persistence
// callback cannot block channel operations.
func TestDisconnectCallbackRunsOutsideChannelLock(t *testing.T) {
	server := NewServer(nil)
	release := make(chan struct{})
	entered := make(chan struct{}, 1)
	server.OnDisconnect = func(Peer, int64) {
		entered <- struct{}{}
		<-release
	}
	httpServer := httptest.NewServer(http.HandlerFunc(server.Handler))
	defer httpServer.Close()
	address := websocketAddress(httpServer.URL)
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()

	client := &EndpointClient{EndpointID: "endpoint-1", InstanceID: "instance-1"}
	if err := client.Dial(ctx, address); err != nil {
		t.Fatal(err)
	}
	if err := client.Close(); err != nil {
		t.Fatal(err)
	}
	select {
	case <-entered:
	case <-time.After(3 * time.Second):
		t.Fatal("disconnect callback was not invoked")
	}

	// While the callback is blocked, channel state must remain readable.
	done := make(chan struct{})
	go func() {
		_ = server.IsOnline("endpoint-1", time.Now())
		close(done)
	}()
	select {
	case <-done:
	case <-time.After(2 * time.Second):
		close(release)
		t.Fatal("channel lock was held during the disconnect callback")
	}
	close(release)
}

// TestExpireStalePeersClosesOnlyExpiredAuthoritativePeer verifies a silent
// half-open connection is removed while a recently observed peer remains live.
func TestExpireStalePeersClosesOnlyExpiredAuthoritativePeer(t *testing.T) {
	server := NewServer(nil)
	server.HeartbeatTimeout = 30 * time.Second
	var mu sync.Mutex
	records := make([]disconnectRecord, 0, 1)
	server.OnDisconnect = func(peer Peer, observedAtMS int64) {
		mu.Lock()
		defer mu.Unlock()
		records = append(records, disconnectRecord{peer: peer, observedAtMS: observedAtMS})
	}
	httpServer := httptest.NewServer(http.HandlerFunc(server.Handler))
	defer httpServer.Close()
	address := websocketAddress(httpServer.URL)
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()

	staleClient := &EndpointClient{EndpointID: "stale-endpoint", InstanceID: "stale-instance"}
	if err := staleClient.Dial(ctx, address); err != nil {
		t.Fatal(err)
	}
	freshClient := &EndpointClient{EndpointID: "fresh-endpoint", InstanceID: "fresh-instance"}
	if err := freshClient.Dial(ctx, address); err != nil {
		t.Fatal(err)
	}
	defer freshClient.Close()

	now := time.Now()
	server.Mu.Lock()
	server.Active["stale-endpoint"].LastSeen = now.Add(-31 * time.Second)
	server.Active["fresh-endpoint"].LastSeen = now.Add(-time.Second)
	server.Mu.Unlock()

	expired := server.ExpireStalePeers(now)
	if len(expired) != 1 || expired[0].EndpointID != "stale-endpoint" {
		t.Fatalf("expired peers=%+v, want only stale-endpoint", expired)
	}
	server.Mu.RLock()
	_, staleActive := server.Active["stale-endpoint"]
	freshPeer := server.Active["fresh-endpoint"]
	server.Mu.RUnlock()
	if staleActive {
		t.Fatal("stale peer remains active")
	}
	if freshPeer == nil || freshPeer.InstanceID != "fresh-instance" {
		t.Fatalf("fresh peer=%+v, want active fresh-instance", freshPeer)
	}
	if err := server.SendCommand(context.Background(), "stale-endpoint", Frame{Type: FrameHeartbeat}); err == nil {
		t.Fatal("Server sent a request to an offline Endpoint")
	}

	// Closing the already-expired client lets its read side settle. The Server
	// read loop must not publish a second disconnect for the same old peer.
	_ = staleClient.Close()
	time.Sleep(100 * time.Millisecond)
	mu.Lock()
	defer mu.Unlock()
	if len(records) != 1 {
		t.Fatalf("disconnect notifications=%d, want exactly one: %+v", len(records), records)
	}
	if records[0].peer.EndpointID != "stale-endpoint" || records[0].observedAtMS != now.UnixMilli() {
		t.Fatalf("disconnect record=%+v, want stale-endpoint at %d", records[0], now.UnixMilli())
	}
}

// TestExpireStalePeersDisabled verifies a non-positive timeout does not close
// peers, preserving the existing explicit opt-out behavior.
func TestExpireStalePeersDisabled(t *testing.T) {
	server := NewServer(nil)
	server.HeartbeatTimeout = 0
	server.Active["endpoint-1"] = &Peer{EndpointID: "endpoint-1", LastSeen: time.Time{}}
	if expired := server.ExpireStalePeers(time.Now()); len(expired) != 0 {
		t.Fatalf("expired peers=%+v, want none", expired)
	}
	if server.Active["endpoint-1"] == nil {
		t.Fatal("disabled liveness removed the active peer")
	}
}
