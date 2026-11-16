package channel

import (
	"context"
	"net/http"
	"net/http/httptest"
	"testing"
	"time"
)

// dialTimes dials the given address the requested number of times so the Server
// assigns that many generations to one Endpoint. Each dial replaces the previous
// peer, so the Endpoint ends up holding the last generation the Server assigned.
func dialTimes(t *testing.T, client *EndpointClient, address string, times int) {
	t.Helper()
	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()
	for i := 0; i < times; i++ {
		if err := client.Dial(ctx, address); err != nil {
			t.Fatalf("dial %d of %d: %v", i+1, times, err)
		}
	}
}

// TestEndpointAdoptsLowerGenerationAfterTransportLoss pins the re-home
// behaviour: after a transport failure the Endpoint must adopt the next
// Server's generation even when that generation is lower than the one the
// previous Server assigned.
//
// The failure this guards is not a network fault. A fresh Server starts its
// in-memory fence at 1, so an Endpoint that still holds generation 5 from the
// previous Server rejects the new link as superseded and reconnects forever.
// The Endpoint must therefore forget the dead connection when the transport
// fails, because there is no live link left to fence against.
func TestEndpointAdoptsLowerGenerationAfterTransportLoss(t *testing.T) {
	first := NewServer(nil)
	firstHTTP := httptest.NewServer(http.HandlerFunc(first.Handler))
	defer firstHTTP.Close()

	client := &EndpointClient{EndpointID: "endpoint-1", InstanceID: "instance-1"}
	dialTimes(t, client, websocketAddress(firstHTTP.URL), 5)
	if client.Generation != 5 {
		t.Fatalf("generation after five dials = %d, want 5", client.Generation)
	}

	// The transport fails. Closing the peer connection is what a Server crash or
	// a network partition looks like to the Endpoint.
	first.Mu.Lock()
	peer := first.Active["endpoint-1"]
	first.Mu.Unlock()
	if peer == nil {
		t.Fatal("the first server installed no peer")
	}
	_ = peer.Conn.CloseNow()

	// The service loop observes the loss through Read, which is the only read
	// path the Endpoint has.
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	if _, err := client.Read(ctx); err == nil {
		t.Fatal("read after the peer connection closed must fail")
	}

	// A second, independent Server starts its fence at 1.
	second := NewServer(nil)
	secondHTTP := httptest.NewServer(http.HandlerFunc(second.Handler))
	defer secondHTTP.Close()

	if err := client.Dial(ctx, websocketAddress(secondHTTP.URL)); err != nil {
		t.Fatalf("re-home to a server whose generation is lower must succeed: %v", err)
	}
	if client.Generation != 1 {
		t.Fatalf("generation after re-home = %d, want 1", client.Generation)
	}
	if !client.Ready() {
		t.Fatal("the endpoint must report ready after adopting the new server")
	}
}

// TestEndpointDetachKeepsGenerationAndClearsReadiness pins the two properties
// the re-home fix depends on: the dead connection is forgotten, and the
// Endpoint stops claiming readiness, while the last generation is retained so a
// same-Server reconnect still fences correctly.
func TestEndpointDetachKeepsGenerationAndClearsReadiness(t *testing.T) {
	server := NewServer(nil)
	httpServer := httptest.NewServer(http.HandlerFunc(server.Handler))
	defer httpServer.Close()

	client := &EndpointClient{EndpointID: "endpoint-1", InstanceID: "instance-1"}
	dialTimes(t, client, websocketAddress(httpServer.URL), 3)
	if !client.Ready() {
		t.Fatal("the endpoint must be ready after a successful dial")
	}

	client.mu.Lock()
	conn := client.Conn
	client.mu.Unlock()
	client.Detach(conn)

	if client.Ready() {
		t.Fatal("a detached endpoint must not report ready")
	}
	if client.Generation != 3 {
		t.Fatalf("generation after detach = %d, want the retained 3", client.Generation)
	}
	if _, err := client.Read(context.Background()); err == nil {
		t.Fatal("read after detach must fail instead of blocking on a dead connection")
	}
}

// TestEndpointDetachIgnoresAReplacedConnection pins the race guard: a read that
// fails on an old connection must not clear a newer connection that was adopted
// while the read was in flight. Without the guard, a slow failing read could
// erase a healthy link and let a stale generation win.
func TestEndpointDetachIgnoresAReplacedConnection(t *testing.T) {
	server := NewServer(nil)
	httpServer := httptest.NewServer(http.HandlerFunc(server.Handler))
	defer httpServer.Close()

	client := &EndpointClient{EndpointID: "endpoint-1", InstanceID: "instance-1"}
	dialTimes(t, client, websocketAddress(httpServer.URL), 2)

	client.mu.Lock()
	stale := client.Conn
	client.mu.Unlock()

	// A newer connection replaces the one the failing read observed.
	dialTimes(t, client, websocketAddress(httpServer.URL), 1)
	client.mu.Lock()
	current := client.Conn
	client.mu.Unlock()
	if current == stale {
		t.Fatal("the second dial did not replace the connection")
	}

	client.Detach(stale)

	client.mu.Lock()
	after := client.Conn
	client.mu.Unlock()
	if after != current {
		t.Fatal("detaching a replaced connection cleared the live one")
	}
	if !client.Ready() {
		t.Fatal("the endpoint must stay ready after a stale detach")
	}
}

// TestEndpointFencedReadKeepsTheConnection pins that a generation mismatch is
// not treated as a transport failure. A fenced frame means the Server considers
// a different link authoritative, so the Endpoint must keep its connection and
// let the bidirectional convergence rule decide, rather than forgetting the
// link and accepting any later generation.
func TestEndpointFencedReadKeepsTheConnection(t *testing.T) {
	server := NewServer(nil)
	httpServer := httptest.NewServer(http.HandlerFunc(server.Handler))
	defer httpServer.Close()

	client := &EndpointClient{EndpointID: "endpoint-1", InstanceID: "instance-1"}
	dialTimes(t, client, websocketAddress(httpServer.URL), 2)

	client.mu.Lock()
	conn := client.Conn
	client.mu.Unlock()

	// A frame carrying a different generation is fenced, not a transport error.
	server.Mu.Lock()
	peer := server.Active["endpoint-1"]
	server.Mu.Unlock()
	if peer == nil {
		t.Fatal("the server installed no peer")
	}
	if err := peer.Conn.Write(context.Background(), 1, []byte(`{"type":"heartbeat","protocol_version":"v1","connection_generation":"99"}`)); err != nil {
		t.Fatalf("write fenced frame: %v", err)
	}

	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	if _, err := client.Read(ctx); err == nil {
		t.Fatal("a fenced frame must be rejected")
	}

	client.mu.Lock()
	after := client.Conn
	client.mu.Unlock()
	if after != conn {
		t.Fatal("a fenced read must keep the connection")
	}
}
