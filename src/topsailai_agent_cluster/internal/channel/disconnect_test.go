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
