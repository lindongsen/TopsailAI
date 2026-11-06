package channel

import (
	"context"
	"errors"
	"net/http"
	"net/http/httptest"
	"testing"
	"time"

	"topsailai_agent_cluster/internal/protocol"
)

// refreshReport builds a complete report used to prove forced-collection delivery.
func refreshReport(sessionID string, revision int64) protocol.InventoryReport {
	return protocol.InventoryReport{
		SchemaVersion:    "v1",
		SourceGeneration: "endpoint-local",
		SnapshotRevision: revision,
		ObservedAtMS:     1000,
		ReportComplete:   true,
		CollectionStatus: protocol.CollectionSucceeded,
		Adapters:         []protocol.AdapterSummary{{AdapterID: "adapter-1", DataKnown: true, CollectionStatus: protocol.CollectionSucceeded}},
		Sessions:         []protocol.Session{{SessionID: sessionID, AdapterID: "adapter-1", Generation: "generation-1", State: "running", CollectionStatus: protocol.CollectionSucceeded}},
	}
}

// TestRequestRefreshAndWaitReturnsCorrelatedReport proves a forced collection waits
// for the Endpoint reply and returns the report that reply carried.
func TestRequestRefreshAndWaitReturnsCorrelatedReport(t *testing.T) {
	server := NewServer(nil)
	persisted := make(chan struct{}, 1)
	server.OnFrame = func(_ Peer, frame Frame) {
		if frame.Type == FrameInventory && frame.RequestID != "" {
			persisted <- struct{}{}
		}
	}
	httpServer := httptest.NewServer(http.HandlerFunc(server.Handler))
	defer httpServer.Close()
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	client := &EndpointClient{EndpointID: "endpoint-1", InstanceID: "refresh"}
	if err := client.Dial(ctx, websocketAddress(httpServer.URL)); err != nil {
		t.Fatal(err)
	}
	defer client.Close()
	reply := make(chan error, 1)
	go func() {
		frame, err := client.Read(ctx)
		if err != nil {
			reply <- err
			return
		}
		if frame.Type != FrameInventoryRefresh || frame.RequestID == "" {
			reply <- errors.New("unexpected refresh request frame")
			return
		}
		reply <- client.SendFrame(ctx, Frame{Type: FrameInventory, ProtocolVersion: ProtocolVersion, RequestID: frame.RequestID, Payload: refreshReport("res-1", 7), SnapshotRevision: 7})
	}()
	report, err := server.RequestRefreshAndWait(ctx, "endpoint-1")
	if err != nil {
		t.Fatalf("forced collection: %v", err)
	}
	if err := <-reply; err != nil {
		t.Fatalf("endpoint reply: %v", err)
	}
	if report.SnapshotRevision != 7 || len(report.Sessions) != 1 || report.Sessions[0].SessionID != "res-1" {
		t.Fatalf("report=%+v", report)
	}
	// The persistence hook must run before the waiter is released, otherwise the
	// caller could read a document that is not committed yet.
	select {
	case <-persisted:
	default:
		t.Fatal("forced collection was delivered before the persistence hook ran")
	}
	if len(server.pendingRefresh) != 0 {
		t.Fatalf("pending refresh entries=%d", len(server.pendingRefresh))
	}
}

// TestFailPendingRefreshReportsOnlyMatchingEndpoint proves a disconnect fails the
// waiters of that Endpoint and leaves unrelated waiters untouched.
func TestFailPendingRefreshReportsOnlyMatchingEndpoint(t *testing.T) {
	server := NewServer(nil)
	matching := make(chan Frame, 1)
	other := make(chan Frame, 1)
	server.pendingRefresh["matching"] = pendingRefreshRequest{endpointID: "e1", response: matching}
	server.pendingRefresh["other"] = pendingRefreshRequest{endpointID: "e2", response: other}
	server.failPendingRefresh("e1")
	frame := <-matching
	if frame.Payload != nil {
		t.Fatalf("failure frame carried a payload: %#v", frame)
	}
	if _, ok := server.pendingRefresh["matching"]; ok {
		t.Fatal("matching pending refresh was not removed")
	}
	if _, ok := server.pendingRefresh["other"]; !ok {
		t.Fatal("unrelated pending refresh was removed")
	}
}

// TestRequestRefreshAndWaitFailsOnDisconnect proves a disconnected Endpoint fails
// the waiter instead of blocking until its own deadline.
func TestRequestRefreshAndWaitFailsOnDisconnect(t *testing.T) {
	server := NewServer(nil)
	httpServer := httptest.NewServer(http.HandlerFunc(server.Handler))
	defer httpServer.Close()
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	client := &EndpointClient{EndpointID: "endpoint-1", InstanceID: "disconnect"}
	if err := client.Dial(ctx, websocketAddress(httpServer.URL)); err != nil {
		t.Fatal(err)
	}
	// The Endpoint never answers the refresh request, then drops the connection.
	go func() {
		_, _ = client.Read(ctx)
		_ = client.Close()
	}()
	start := time.Now()
	if _, err := server.RequestRefreshAndWait(ctx, "endpoint-1"); err == nil {
		t.Fatal("disconnected Endpoint did not fail the forced collection")
	}
	if elapsed := time.Since(start); elapsed > 3*time.Second {
		t.Fatalf("waiter blocked for %s instead of failing on disconnect", elapsed)
	}
	if len(server.pendingRefresh) != 0 {
		t.Fatalf("pending refresh entries=%d", len(server.pendingRefresh))
	}
}

// TestRequestRefreshAndWaitHonoursDeadline proves a silent Endpoint cannot hold the
// waiter past its deadline and that the pending entry is released.
func TestRequestRefreshAndWaitHonoursDeadline(t *testing.T) {
	server := NewServer(nil)
	httpServer := httptest.NewServer(http.HandlerFunc(server.Handler))
	defer httpServer.Close()
	dialCtx, dialCancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer dialCancel()
	client := &EndpointClient{EndpointID: "endpoint-1", InstanceID: "silent"}
	if err := client.Dial(dialCtx, websocketAddress(httpServer.URL)); err != nil {
		t.Fatal(err)
	}
	defer client.Close()
	go func() {
		for {
			if _, err := client.Read(dialCtx); err != nil {
				return
			}
		}
	}()
	ctx, cancel := context.WithTimeout(context.Background(), 150*time.Millisecond)
	defer cancel()
	if _, err := server.RequestRefreshAndWait(ctx, "endpoint-1"); !errors.Is(err, context.DeadlineExceeded) {
		t.Fatalf("deadline error=%v", err)
	}
	if len(server.pendingRefresh) != 0 {
		t.Fatalf("pending refresh entries=%d", len(server.pendingRefresh))
	}
}

// TestRequestRefreshAndWaitRejectsCapacity proves forced collections are bounded so
// discovery cannot be amplified by unbounded concurrent requests.
func TestRequestRefreshAndWaitRejectsCapacity(t *testing.T) {
	server := NewServer(nil)
	for i := 0; i < maxPendingRefresh; i++ {
		server.pendingRefresh[string(rune('a'+i%26))+string(rune('a'+i/26))] = pendingRefreshRequest{endpointID: "e1", response: make(chan Frame, 1)}
	}
	if _, err := server.RequestRefreshAndWait(context.Background(), "e1"); err == nil {
		t.Fatal("capacity limit was not enforced")
	}
	if len(server.pendingRefresh) != maxPendingRefresh {
		t.Fatalf("capacity rejection changed pending entries=%d", len(server.pendingRefresh))
	}
}

// TestDeliverRefreshIgnoresAnotherEndpoint proves a reply is only delivered to the
// waiter of the Endpoint that produced it.
func TestDeliverRefreshIgnoresAnotherEndpoint(t *testing.T) {
	server := NewServer(nil)
	response := make(chan Frame, 1)
	server.pendingRefresh["request-1"] = pendingRefreshRequest{endpointID: "e1", response: response}
	server.deliverRefresh(&Peer{EndpointID: "e2"}, Frame{Type: FrameInventory, RequestID: "request-1", Payload: refreshReport("res-1", 1)})
	select {
	case frame := <-response:
		t.Fatalf("cross-endpoint reply was delivered: %#v", frame)
	default:
	}
	if _, ok := server.pendingRefresh["request-1"]; !ok {
		t.Fatal("cross-endpoint reply removed the pending request")
	}
	server.deliverRefresh(&Peer{EndpointID: "e1"}, Frame{Type: FrameInventory, RequestID: "request-1", Payload: refreshReport("res-1", 1)})
	select {
	case frame := <-response:
		if frame.RequestID != "request-1" {
			t.Fatalf("delivered frame=%#v", frame)
		}
	default:
		t.Fatal("matching reply was not delivered")
	}
}
