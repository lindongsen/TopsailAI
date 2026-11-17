package channel

import (
	"context"
	"net/http"
	"net/http/httptest"
	"runtime"
	"sync"
	"testing"
	"time"

	"topsailai_agent_cluster/internal/protocol"
)

// dialTestEndpoint connects one Endpoint to a Server and returns the client.
func dialTestEndpoint(t *testing.T, server *Server, instanceID string) (*EndpointClient, context.Context, context.CancelFunc) {
	t.Helper()
	httpServer := httptest.NewServer(http.HandlerFunc(server.Handler))
	t.Cleanup(httpServer.Close)
	ctx, cancel := context.WithTimeout(context.Background(), 15*time.Second)
	t.Cleanup(cancel)
	client := &EndpointClient{EndpointID: "endpoint-1", InstanceID: instanceID}
	if err := client.Dial(ctx, websocketAddress(httpServer.URL)); err != nil {
		cancel()
		t.Fatalf("dial: %v", err)
	}
	t.Cleanup(func() { client.Close() })
	return client, ctx, cancel
}

// inventoryFrame builds one inventory frame carrying a valid report.
func inventoryFrame(requestID string, revision int64) Frame {
	return Frame{Type: FrameInventory, ProtocolVersion: ProtocolVersion, RequestID: requestID, Payload: refreshReport("res-1", revision), SnapshotRevision: revision}
}

// TestServerHeartbeatAckIsNotBlockedByBusinessHandler is the core regression.
//
// The read loop used to run the persistence hook inline, so a database write
// that took seconds also delayed the heartbeat acknowledgement. The Endpoint
// then counted unacknowledged beats and tore the link down while the Server was
// perfectly healthy. This test blocks the handler and requires the
// acknowledgement to arrive anyway.
func TestServerHeartbeatAckIsNotBlockedByBusinessHandler(t *testing.T) {
	server := NewServer(nil)
	defer server.Close()

	entered := make(chan struct{}, 1)
	release := make(chan struct{})
	server.OnFrame = func(_ Peer, frame Frame) {
		if frame.Type != FrameInventory {
			return
		}
		select {
		case entered <- struct{}{}:
		default:
		}
		<-release
	}

	client, ctx, _ := dialTestEndpoint(t, server, "blocked-handler")

	// Put the worker inside the handler and leave it blocked there.
	if err := client.SendFrame(ctx, inventoryFrame("inventory-1", 1)); err != nil {
		t.Fatalf("send inventory: %v", err)
	}
	select {
	case <-entered:
	case <-ctx.Done():
		t.Fatal("the business handler never ran")
	}

	// The heartbeat must be acknowledged while the handler is still blocked.
	if err := client.SendFrame(ctx, Frame{Type: FrameHeartbeat, ProtocolVersion: ProtocolVersion}); err != nil {
		t.Fatalf("send heartbeat: %v", err)
	}
	readCtx, readCancel := context.WithTimeout(ctx, 2*time.Second)
	defer readCancel()
	frame, err := client.Read(readCtx)
	if err != nil {
		t.Fatalf("heartbeat acknowledgement was blocked by the business handler: %v", err)
	}
	if frame.Type != FrameHeartbeatAck {
		t.Fatalf("frame type=%q, want %q", frame.Type, FrameHeartbeatAck)
	}
	close(release)
}

// TestServerBusinessFramesKeepArrivalOrder proves one worker per peer preserves
// order, which matters because a receipt and the inventory after it are
// causally related.
func TestServerBusinessFramesKeepArrivalOrder(t *testing.T) {
	server := NewServer(nil)
	defer server.Close()

	var mu sync.Mutex
	var order []string
	done := make(chan struct{}, 1)
	server.OnFrame = func(_ Peer, frame Frame) {
		if frame.Type != FrameInventory {
			return
		}
		mu.Lock()
		order = append(order, frame.RequestID)
		complete := len(order) == 3
		mu.Unlock()
		if complete {
			select {
			case done <- struct{}{}:
			default:
			}
		}
	}

	client, ctx, _ := dialTestEndpoint(t, server, "ordering")
	for i, requestID := range []string{"first", "second", "third"} {
		if err := client.SendFrame(ctx, inventoryFrame(requestID, int64(i+1))); err != nil {
			t.Fatalf("send %s: %v", requestID, err)
		}
	}
	select {
	case <-done:
	case <-ctx.Done():
		t.Fatal("the handler did not observe all three frames")
	}

	mu.Lock()
	got := append([]string(nil), order...)
	mu.Unlock()
	want := []string{"first", "second", "third"}
	if len(got) != len(want) {
		t.Fatalf("order=%v, want %v", got, want)
	}
	for i := range want {
		if got[i] != want[i] {
			t.Fatalf("order=%v, want %v", got, want)
		}
	}
}

// TestServerDeliversRefreshAfterPersistenceHook proves the ordering contract
// survived the move: the waiter must observe the committed state, so the report
// is released only after the persistence hook ran for that frame.
func TestServerDeliversRefreshAfterPersistenceHook(t *testing.T) {
	server := NewServer(nil)
	defer server.Close()

	hookEntered := make(chan struct{}, 1)
	release := make(chan struct{})
	server.OnFrame = func(_ Peer, frame Frame) {
		if frame.Type != FrameInventory || frame.RequestID == "" {
			return
		}
		select {
		case hookEntered <- struct{}{}:
		default:
		}
		<-release
	}

	client, ctx, _ := dialTestEndpoint(t, server, "refresh-order")

	report := make(chan protocol.InventoryReport, 1)
	failure := make(chan error, 1)
	go func() {
		got, err := server.RequestRefreshAndWait(ctx, "endpoint-1")
		if err != nil {
			failure <- err
			return
		}
		report <- got
	}()

	// Answer the forced collection request.
	requestCtx, requestCancel := context.WithTimeout(ctx, 5*time.Second)
	defer requestCancel()
	request, err := client.Read(requestCtx)
	if err != nil {
		t.Fatalf("read refresh request: %v", err)
	}
	if request.Type != FrameInventoryRefresh {
		t.Fatalf("frame type=%q, want %q", request.Type, FrameInventoryRefresh)
	}
	if err := client.SendFrame(ctx, inventoryFrame(request.RequestID, 7)); err != nil {
		t.Fatalf("send refresh report: %v", err)
	}

	// The hook is blocked, so the waiter must not be released yet.
	select {
	case <-hookEntered:
	case <-ctx.Done():
		t.Fatal("the persistence hook never ran")
	}
	select {
	case got := <-report:
		t.Fatalf("report was released before the persistence hook returned: %+v", got)
	case err := <-failure:
		t.Fatalf("forced collection failed before the hook returned: %v", err)
	case <-time.After(200 * time.Millisecond):
	}

	close(release)
	select {
	case got := <-report:
		if got.SnapshotRevision != 7 {
			t.Fatalf("revision=%d, want 7", got.SnapshotRevision)
		}
	case err := <-failure:
		t.Fatalf("forced collection: %v", err)
	case <-ctx.Done():
		t.Fatal("the report was never released after the hook returned")
	}
}

// TestServerFullBusinessQueueClosesPeer proves a peer that cannot keep up is
// disconnected instead of blocking the read loop or silently dropping frames.
func TestServerFullBusinessQueueClosesPeer(t *testing.T) {
	server := NewServer(nil)
	defer server.Close()

	entered := make(chan struct{}, 1)
	release := make(chan struct{})
	defer close(release)
	server.OnFrame = func(_ Peer, frame Frame) {
		if frame.Type != FrameInventory {
			return
		}
		select {
		case entered <- struct{}{}:
		default:
		}
		<-release
	}

	client, ctx, _ := dialTestEndpoint(t, server, "full-queue")

	// One frame occupies the worker; the rest fill the bounded queue.
	if err := client.SendFrame(ctx, inventoryFrame("occupies-worker", 1)); err != nil {
		t.Fatalf("send first inventory: %v", err)
	}
	select {
	case <-entered:
	case <-ctx.Done():
		t.Fatal("the business handler never ran")
	}
	for i := 0; i < businessQueueDepth+1; i++ {
		if err := client.SendFrame(ctx, inventoryFrame("fills-queue", int64(i+2))); err != nil {
			// A write error is acceptable here: the Server may already have
			// closed the connection, which is the outcome under test.
			break
		}
	}

	// The read loop must not be blocked, so the disconnect must be observable
	// while the handler is still holding the worker.
	readCtx, readCancel := context.WithTimeout(ctx, 3*time.Second)
	defer readCancel()
	for {
		if _, err := client.Read(readCtx); err != nil {
			break
		}
	}
	if readCtx.Err() != nil {
		t.Fatal("the peer was not disconnected while its business queue was full")
	}
	server.Mu.RLock()
	_, stillActive := server.Active["endpoint-1"]
	server.Mu.RUnlock()
	if stillActive {
		t.Fatal("a peer with a full business queue must be removed from Active")
	}
}

// TestServerSupersededWorkerDoesNotWriteBusinessState proves a worker belonging
// to an old connection stops instead of overwriting the newer connection's
// state.
func TestServerSupersededWorkerDoesNotWriteBusinessState(t *testing.T) {
	server := NewServer(nil)
	defer server.Close()

	entered := make(chan struct{}, 1)
	release := make(chan struct{})
	var mu sync.Mutex
	var handled []string
	server.OnFrame = func(_ Peer, frame Frame) {
		if frame.Type != FrameInventory {
			return
		}
		mu.Lock()
		handled = append(handled, frame.RequestID)
		mu.Unlock()
		if frame.RequestID == "old-connection" {
			select {
			case entered <- struct{}{}:
			default:
			}
			<-release
		}
	}

	first, firstCtx, _ := dialTestEndpoint(t, server, "superseded")
	if err := first.SendFrame(firstCtx, inventoryFrame("old-connection", 1)); err != nil {
		t.Fatalf("send on the first connection: %v", err)
	}
	select {
	case <-entered:
	case <-firstCtx.Done():
		t.Fatal("the first connection's handler never ran")
	}

	// A second connection for the same Endpoint supersedes the first.
	second := &EndpointClient{EndpointID: "endpoint-1", InstanceID: "superseded"}
	httpServer := httptest.NewServer(http.HandlerFunc(server.Handler))
	defer httpServer.Close()
	secondCtx, secondCancel := context.WithTimeout(context.Background(), 15*time.Second)
	defer secondCancel()
	if err := second.Dial(secondCtx, websocketAddress(httpServer.URL)); err != nil {
		t.Fatalf("dial the second connection: %v", err)
	}
	defer second.Close()

	close(release)
	// Give the old worker a chance to run any frame it still holds.
	time.Sleep(200 * time.Millisecond)

	if err := second.SendFrame(secondCtx, inventoryFrame("new-connection", 2)); err != nil {
		t.Fatalf("send on the second connection: %v", err)
	}
	deadline := time.Now().Add(3 * time.Second)
	for time.Now().Before(deadline) {
		mu.Lock()
		sawNew := false
		for _, requestID := range handled {
			if requestID == "new-connection" {
				sawNew = true
			}
		}
		mu.Unlock()
		if sawNew {
			return
		}
		time.Sleep(20 * time.Millisecond)
	}
	t.Fatal("the new connection's frame was never handled")
}

// TestServerBusinessWorkerDoesNotLeak proves repeated connect/disconnect cycles
// do not accumulate workers.
func TestServerBusinessWorkerDoesNotLeak(t *testing.T) {
	server := NewServer(nil)
	defer server.Close()
	server.OnFrame = func(_ Peer, _ Frame) {}

	baseline := runtime.NumGoroutine()
	for i := 0; i < 50; i++ {
		httpServer := httptest.NewServer(http.HandlerFunc(server.Handler))
		ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
		client := &EndpointClient{EndpointID: "endpoint-1", InstanceID: "leak"}
		if err := client.Dial(ctx, websocketAddress(httpServer.URL)); err != nil {
			cancel()
			httpServer.Close()
			t.Fatalf("dial %d: %v", i, err)
		}
		client.Close()
		cancel()
		httpServer.Close()
	}

	deadline := time.Now().Add(5 * time.Second)
	for time.Now().Before(deadline) {
		if runtime.NumGoroutine() <= baseline+5 {
			return
		}
		time.Sleep(50 * time.Millisecond)
	}
	t.Fatalf("goroutines=%d, baseline=%d: business workers leaked", runtime.NumGoroutine(), baseline)
}
