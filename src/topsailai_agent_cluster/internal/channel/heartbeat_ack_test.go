package channel

import (
	"context"
	"errors"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/coder/websocket"
	"github.com/coder/websocket/wsjson"
)

// silentServer accepts one Endpoint-initiated connection, completes the
// handshake, and then stops answering without closing the socket.
//
// This is the failure the heartbeat rule exists for. A Server that exits or is
// killed closes its socket, so the Endpoint's read fails immediately and the
// reconnect path runs even with no liveness rule at all. A Server that keeps
// its socket open and stops replying produces no read error, so only an
// unacknowledged heartbeat can reveal it. A test that stops a Server therefore
// cannot prove this rule works.
func silentServer(t *testing.T) (string, func()) {
	t.Helper()
	handler := func(w http.ResponseWriter, r *http.Request) {
		conn, err := websocket.Accept(w, r, &websocket.AcceptOptions{InsecureSkipVerify: true})
		if err != nil {
			return
		}
		var hello Frame
		if err := wsjson.Read(r.Context(), conn, &hello); err != nil {
			return
		}
		ack := Frame{Type: FrameHelloAck, ProtocolVersion: ProtocolVersion, ConnectionGeneration: "1", EndpointID: hello.EndpointID}
		if err := wsjson.Write(r.Context(), conn, ack); err != nil {
			return
		}
		var attached Frame
		if err := wsjson.Read(r.Context(), conn, &attached); err != nil {
			return
		}
		// The handshake is complete and the socket stays open. Nothing is read
		// and nothing is written from here on, which is exactly a Server whose
		// process is alive but whose application stopped responding.
		<-r.Context().Done()
		_ = conn.CloseNow()
	}
	server := httptest.NewServer(http.HandlerFunc(handler))
	return websocketAddress(server.URL), server.Close
}

// TestRunHeartbeatDeclaresSilentServerUnhealthy pins the liveness rule: a Server
// that stops acknowledging heartbeats is declared unhealthy once the
// unacknowledged time reaches the window, and the connection is closed so the
// existing reconnect path can walk the address list.
func TestRunHeartbeatDeclaresSilentServerUnhealthy(t *testing.T) {
	address, closeServer := silentServer(t)
	defer closeServer()

	client := &EndpointClient{EndpointID: "endpoint-1", InstanceID: "instance-1"}
	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()
	if err := client.Dial(ctx, address); err != nil {
		t.Fatalf("dial the silent server: %v", err)
	}

	var mu sync.Mutex
	var reported []time.Duration
	client.OnServerUnhealthy = func(unacknowledged time.Duration) {
		mu.Lock()
		reported = append(reported, unacknowledged)
		mu.Unlock()
	}
	client.HeartbeatAckTimeout = 20 * time.Millisecond
	client.UnhealthyWindow = 150 * time.Millisecond

	// RunHeartbeat returns nil after making the decision, because the decision
	// is the outcome and the connection close is the mechanism. An error would
	// be logged as a heartbeat fault and would hide that the Server was judged
	// unhealthy.
	if err := client.RunHeartbeat(ctx, 50*time.Millisecond); err != nil {
		t.Fatalf("RunHeartbeat returned %v, want nil after the unhealthy decision", err)
	}

	mu.Lock()
	count := len(reported)
	var last time.Duration
	if count > 0 {
		last = reported[count-1]
	}
	mu.Unlock()
	if count != 1 {
		t.Fatalf("OnServerUnhealthy calls=%d, want exactly one decision", count)
	}
	if last < client.UnhealthyWindow {
		t.Fatalf("reported unacknowledged=%s, want at least the %s window", last, client.UnhealthyWindow)
	}

	// Closing the connection is the whole mechanism: the channel loop already
	// treats a read error as transport loss and reconnects through the ordered
	// address list. If the connection were left open the Endpoint would stay on
	// an unresponsive Server forever.
	readCtx, readCancel := context.WithTimeout(context.Background(), 2*time.Second)
	defer readCancel()
	if _, err := client.Read(readCtx); err == nil {
		t.Fatal("read after the unhealthy decision must fail, so the reconnect path runs")
	}
}

// TestRunHeartbeatKeepsAcknowledgedServerHealthy pins the opposite direction: a
// Server that answers every heartbeat must never be declared unhealthy, however
// many beats pass. Without this the rule could pass the silent-Server test by
// declaring every Server unhealthy.
func TestRunHeartbeatKeepsAcknowledgedServerHealthy(t *testing.T) {
	server := NewServer(nil)
	httpServer := httptest.NewServer(http.HandlerFunc(server.Handler))
	defer httpServer.Close()
	defer server.Close()

	client := &EndpointClient{EndpointID: "endpoint-1", InstanceID: "instance-1"}
	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()
	if err := client.Dial(ctx, websocketAddress(httpServer.URL)); err != nil {
		t.Fatalf("dial the answering server: %v", err)
	}

	var unhealthy int
	var mu sync.Mutex
	client.OnServerUnhealthy = func(time.Duration) {
		mu.Lock()
		unhealthy++
		mu.Unlock()
	}
	client.HeartbeatAckTimeout = 200 * time.Millisecond
	client.UnhealthyWindow = 100 * time.Millisecond

	// The channel loop is the single reader of the connection, so the test
	// stands in for it here: every acknowledgement frame is recorded through the
	// same method the loop calls. Reading the connection from the heartbeat
	// sender instead would consume other frames, which is why the production
	// wiring puts this in the loop.
	readCtx, readCancel := context.WithCancel(ctx)
	defer readCancel()
	go func() {
		for {
			frame, err := client.Read(readCtx)
			if err != nil {
				return
			}
			if frame.Type == FrameHeartbeatAck {
				client.AcknowledgeHeartbeat()
			}
		}
	}()

	// Six beats span three unhealthy windows, so a rule that counted beats
	// instead of acknowledged time would fire here. Readiness is asserted while
	// the loop is still running: the loop context is also the write context, so
	// letting it expire tears the connection down and the assertion would race
	// that shutdown instead of measuring the healthy path.
	heartbeatCtx, stopHeartbeat := context.WithCancel(ctx)
	defer stopHeartbeat()
	loopDone := make(chan error, 1)
	go func() { loopDone <- client.RunHeartbeat(heartbeatCtx, 50*time.Millisecond) }()
	time.Sleep(300 * time.Millisecond)

	mu.Lock()
	count := unhealthy
	mu.Unlock()
	if count != 0 {
		t.Fatalf("OnServerUnhealthy calls=%d, want none while every heartbeat is acknowledged", count)
	}
	if !client.Ready() {
		t.Fatal("the endpoint must stay ready while the server answers")
	}
	stopHeartbeat()
	if err := <-loopDone; err != nil && !errors.Is(err, context.Canceled) {
		t.Fatalf("RunHeartbeat returned %v while the server was answering", err)
	}
}

// TestAcknowledgeHeartbeatBeforeAnyBeatDoesNotPanic pins the lazy allocation of
// the acknowledgement channel. A nil channel would make every heartbeat look
// unacknowledged, so a healthy Server would be declared unhealthy after one
// window; the channel must therefore exist before the first beat is sent.
func TestAcknowledgeHeartbeatBeforeAnyBeatDoesNotPanic(t *testing.T) {
	client := &EndpointClient{}
	client.AcknowledgeHeartbeat()
	client.AcknowledgeHeartbeat()
	if client.heartbeatAckChannel() == nil {
		t.Fatal("the acknowledgement channel must be allocated on first use")
	}
}

// TestStaleAcknowledgementDoesNotSatisfyTheNextBeat pins the drain before each
// send. A leftover acknowledgement from a previous beat would otherwise be
// consumed by the next wait, so a Server that answered once and then stopped
// would look healthy for as many beats as it had stale acknowledgements.
func TestStaleAcknowledgementDoesNotSatisfyTheNextBeat(t *testing.T) {
	client := &EndpointClient{}
	client.AcknowledgeHeartbeat()
	client.drainHeartbeatAcks()

	ctx, cancel := context.WithTimeout(context.Background(), 2*time.Second)
	defer cancel()
	if client.awaitHeartbeatAck(ctx, 50*time.Millisecond) {
		t.Fatal("a drained acknowledgement must not satisfy the next wait")
	}
}

// TestRunHeartbeatReportsOfflineWhenDetached pins that a heartbeat sent while no
// connection is installed returns the offline error instead of waiting for an
// acknowledgement that cannot arrive. The service loop restarts the heartbeat
// after such an error, so this path is expected during every re-home.
func TestRunHeartbeatReportsOfflineWhenDetached(t *testing.T) {
	client := &EndpointClient{}
	ctx, cancel := context.WithTimeout(context.Background(), 2*time.Second)
	defer cancel()
	err := client.RunHeartbeat(ctx, 20*time.Millisecond)
	if err == nil {
		t.Fatal("a heartbeat with no connection must report an error")
	}
	if !strings.Contains(err.Error(), "offline") {
		t.Fatalf("heartbeat error=%v, want the offline error", err)
	}
}
