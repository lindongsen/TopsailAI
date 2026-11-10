//go:build integration

package integration

import (
	"context"
	"encoding/json"
	"log/slog"
	"runtime"
	"testing"
	"time"

	"github.com/gorilla/websocket"

	"topsailai_connector/internal/protocol"
	"topsailai_connector/internal/security"
	"topsailai_connector/internal/server"
)

// reconnectRounds is how many connect/disconnect cycles the long-run test drives.
//
// Twenty is chosen because a per-round leak of one goroutine or one registry entry
// becomes unmistakable at that count while the test still finishes in seconds. A
// single round cannot distinguish "released" from "not yet released", and a
// thousand rounds would only add wall-clock time without adding evidence.
const reconnectRounds = 20

// goroutineTolerance is how many goroutines may remain above the baseline.
//
// The tolerance is not slack for a leak. It covers two things that are not leaks:
// the http.Server's accept loop and one connection goroutine that may still be
// unwinding when the last round closes. A leak of one goroutine per round would
// leave twenty above the baseline, which is ten times this tolerance, so the check
// still fails loudly for the defect it exists to catch.
const goroutineTolerance = 2

// longRunFixture is a real Server listener with no Node attached.
//
// The test dials the channel itself instead of starting a Node, because the
// question here is what the Server does with a connection that appears and
// disappears, and a Node would add its own retry loop to the measurement.
type longRunFixture struct {
	address     string
	tunnelToken security.Secret
	registry    *server.Registry
}

// newLongRunFixture starts a listener on a real port and waits until it binds.
func newLongRunFixture(t *testing.T) *longRunFixture {
	t.Helper()

	tunnelToken := security.Secret("tunnel-token-for-the-long-run-test")
	logger := slog.New(slog.DiscardHandler)
	registry := server.NewRegistry()

	listener, err := server.NewListener(server.Config{
		Listen:         "127.0.0.1:0",
		TunnelToken:    tunnelToken,
		ClientToken:    security.Secret("client-token-for-the-long-run-test"),
		RequestTimeout: 10 * time.Second,
	}, registry, logger)
	if err != nil {
		t.Fatalf("build the listener: %v", err)
	}

	serverContext, stopServer := context.WithCancel(context.Background())
	serverDone := make(chan error, 1)
	go func() {
		serverDone <- listener.Serve(serverContext)
	}()
	t.Cleanup(func() {
		stopServer()
		select {
		case err := <-serverDone:
			if err != nil {
				t.Errorf("the server returned %v, want nil after a clean shutdown", err)
			}
		case <-time.After(15 * time.Second):
			t.Error("the server did not stop")
		}
	})

	return &longRunFixture{
		address:     waitForBind(t, listener),
		tunnelToken: tunnelToken,
		registry:    registry,
	}
}

// connect performs one handshake and returns the open connection.
//
// The hello carries a real tunnel token and a node id the Server accepts, so the
// connection reaches the registration path rather than being refused earlier. A
// refused connection would never be registered and the round would prove nothing.
func (f *longRunFixture) connect(t *testing.T, nodeID string) *websocket.Conn {
	t.Helper()

	url := "ws://" + f.address + server.ChannelPath
	conn, _, err := websocket.DefaultDialer.Dial(url, nil)
	if err != nil {
		t.Fatalf("dial the channel: %v", err)
	}

	hello := protocol.Hello{
		Version:     protocol.Version,
		NodeID:      nodeID,
		TunnelToken: []byte(f.tunnelToken),
		Operations:  []string{"file.read"},
		Scopes:      []string{"project"},
	}
	payload, err := json.Marshal(hello)
	if err != nil {
		t.Fatalf("encode hello: %v", err)
	}
	frame, err := json.Marshal(protocol.Frame{Type: protocol.FrameHello, Payload: payload})
	if err != nil {
		t.Fatalf("encode hello frame: %v", err)
	}
	if err := conn.WriteMessage(websocket.TextMessage, frame); err != nil {
		t.Fatalf("write hello: %v", err)
	}

	if err := conn.SetReadDeadline(time.Now().Add(10 * time.Second)); err != nil {
		t.Fatalf("set read deadline: %v", err)
	}
	_, data, err := conn.ReadMessage()
	if err != nil {
		t.Fatalf("read hello_confirm: %v", err)
	}
	var confirm protocol.Frame
	if err := json.Unmarshal(data, &confirm); err != nil {
		t.Fatalf("decode hello_confirm: %v", err)
	}
	if confirm.Type != protocol.FrameHelloConfirm {
		t.Fatalf("the server answered %q, want hello_confirm", confirm.Type)
	}
	return conn
}

// waitForRegistryLen waits until the registry holds exactly want entries.
//
// Polling rather than sleeping is what makes the assertion about the Server's
// behaviour instead of about how fast the test machine is. A fixed sleep would
// either be too short on a loaded machine or waste time on an idle one.
func (f *longRunFixture) waitForRegistryLen(t *testing.T, want int) {
	t.Helper()

	deadline := time.Now().Add(15 * time.Second)
	for {
		if f.registry.Len() == want {
			return
		}
		if time.Now().After(deadline) {
			t.Fatalf("the registry holds %d entries, want %d", f.registry.Len(), want)
		}
		time.Sleep(2 * time.Millisecond)
	}
}

// waitForGoroutines waits until the goroutine count falls to at most limit.
//
// A closed connection's reader goroutine exits shortly after Close returns, so the
// count is polled instead of sampled once. Sampling once would report a leak that
// is only a goroutine still unwinding, which is the classic false positive in this
// kind of check.
func waitForGoroutines(t *testing.T, limit int) int {
	t.Helper()

	deadline := time.Now().Add(15 * time.Second)
	for {
		count := runtime.NumGoroutine()
		if count <= limit {
			return count
		}
		if time.Now().After(deadline) {
			return count
		}
		time.Sleep(10 * time.Millisecond)
	}
}

// TestServerReleasesEveryConnectionOverManyRounds proves that a connection which
// appears and disappears leaves nothing behind.
//
// Each round asserts the registry returns to zero, which is the Server's own record
// of what is connected. The goroutine count is compared against a baseline taken
// after the listener is up, so a leak of one goroutine per round shows up as twenty
// above the baseline rather than being hidden by the Server's own startup cost.
func TestServerReleasesEveryConnectionOverManyRounds(t *testing.T) {
	fixture := newLongRunFixture(t)

	// The baseline is taken after the listener is bound, so the accept loop and the
	// http.Server's own goroutines are already counted and cannot be mistaken for a
	// leak caused by a connection.
	baseline := runtime.NumGoroutine()
	t.Logf("baseline goroutines: %d", baseline)

	for round := 0; round < reconnectRounds; round++ {
		nodeID := "node_0123456789abcdefghijklmnop"

		conn := fixture.connect(t, nodeID)
		fixture.waitForRegistryLen(t, 1)

		if err := conn.Close(); err != nil {
			t.Fatalf("round %d: close the connection: %v", round, err)
		}
		fixture.waitForRegistryLen(t, 0)
	}

	if entries := fixture.registry.Len(); entries != 0 {
		t.Fatalf("the registry holds %d entries after %d rounds, want 0", entries, reconnectRounds)
	}

	limit := baseline + goroutineTolerance
	count := waitForGoroutines(t, limit)
	if count > limit {
		t.Fatalf("goroutines are %d after %d rounds, want at most %d (baseline %d plus a tolerance of %d)",
			count, reconnectRounds, limit, baseline, goroutineTolerance)
	}
	t.Logf("goroutines after %d rounds: %d (baseline %d, tolerance %d)",
		reconnectRounds, count, baseline, goroutineTolerance)
}

// TestServerReleasesAReplacedConnection proves that a reconnect replaces the entry
// instead of adding one, and that the replaced connection's own shutdown does not
// evict its replacement.
//
// This is the generation check in Unregister. Without it the old connection's
// cleanup would remove the entry the new connection installed, and the symptom
// would be a Node that looks connected and answers node_offline.
func TestServerReleasesAReplacedConnection(t *testing.T) {
	fixture := newLongRunFixture(t)
	nodeID := "node_0123456789abcdefghijklmnop"

	first := fixture.connect(t, nodeID)
	fixture.waitForRegistryLen(t, 1)

	second := fixture.connect(t, nodeID)
	// One identity, two connections, one entry: the replacement must not add a
	// second entry, because two live connections for one identity would be two
	// answers to one request.
	fixture.waitForRegistryLen(t, 1)

	// Closing the first connection runs its shutdown path, which unregisters a stale
	// generation. The replacement must survive it.
	if err := first.Close(); err != nil {
		t.Fatalf("close the replaced connection: %v", err)
	}
	time.Sleep(200 * time.Millisecond)
	if entries := fixture.registry.Len(); entries != 1 {
		t.Fatalf("the registry holds %d entries after the replaced connection closed, want 1", entries)
	}

	if err := second.Close(); err != nil {
		t.Fatalf("close the replacement: %v", err)
	}
	fixture.waitForRegistryLen(t, 0)
}
