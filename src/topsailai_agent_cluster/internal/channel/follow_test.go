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

// followRequest builds one standard follow request for a resource generation.
func followRequest(resourceID string) protocol.OutputFollowRequest {
	return protocol.OutputFollowRequest{EndpointID: "endpoint-1", ResourceID: resourceID, Generation: "generation-1", MaxLines: 20, MaxBytes: 4096}
}

// dialFollowEndpoint connects one Endpoint client to a test Server and returns
// the client together with a cleanup function.
func dialFollowEndpoint(t *testing.T, server *Server) (*EndpointClient, context.Context, context.CancelFunc) {
	t.Helper()
	httpServer := httptest.NewServer(http.HandlerFunc(server.Handler))
	t.Cleanup(httpServer.Close)
	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	t.Cleanup(cancel)
	client := &EndpointClient{EndpointID: "endpoint-1", InstanceID: "follow"}
	if err := client.Dial(ctx, websocketAddress(httpServer.URL)); err != nil {
		cancel()
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = client.Close() })
	return client, ctx, cancel
}

// TestRequestFollowDeliversChunksThenEnd proves a follow delivers every chunk
// before exactly one terminal end event, so a consumer can tell a finished
// stream from an interrupted one.
func TestRequestFollowDeliversChunksThenEnd(t *testing.T) {
	server := NewServer(nil)
	client, ctx, _ := dialFollowEndpoint(t, server)
	reply := make(chan error, 1)
	go func() {
		frame, err := client.Read(ctx)
		if err != nil {
			reply <- err
			return
		}
		if frame.Type != FrameOutputFollowRequest || frame.RequestID == "" {
			reply <- errors.New("unexpected follow request frame")
			return
		}
		for _, line := range []string{"first", "second"} {
			chunk := protocol.OutputChunk{Lines: []string{line}, ObservedAtMS: 1000}
			if err := client.SendFrame(ctx, Frame{Type: FrameOutputChunk, ProtocolVersion: ProtocolVersion, RequestID: frame.RequestID, OutputChunk: &chunk}); err != nil {
				reply <- err
				return
			}
		}
		end := protocol.OutputEnd{ObservedAtMS: 2000}
		reply <- client.SendFrame(ctx, Frame{Type: FrameOutputEnd, ProtocolVersion: ProtocolVersion, RequestID: frame.RequestID, OutputEnd: &end})
	}()
	events, err := server.RequestFollow(ctx, "endpoint-1", followRequest("res-1"))
	if err != nil {
		t.Fatalf("request follow: %v", err)
	}
	if err := <-reply; err != nil {
		t.Fatalf("endpoint reply: %v", err)
	}
	var lines []string
	for event := range events {
		if event.End != nil {
			if event.End.ErrorCode != "" {
				t.Fatalf("unexpected end code %q", event.End.ErrorCode)
			}
			break
		}
		if event.Chunk == nil {
			t.Fatal("event carried neither chunk nor end")
		}
		lines = append(lines, event.Chunk.Lines...)
	}
	if len(lines) != 2 || lines[0] != "first" || lines[1] != "second" {
		t.Fatalf("lines=%v", lines)
	}
	server.Mu.Lock()
	pending := len(server.pendingFollow)
	server.Mu.Unlock()
	if pending != 0 {
		t.Fatalf("pending follow entries=%d", pending)
	}
}

// TestRequestFollowCancellationEndsStream proves cancelling the caller context
// releases the pending entry and terminates the stream, so a provider child is
// never left streaming into a queue nobody reads.
func TestRequestFollowCancellationEndsStream(t *testing.T) {
	server := NewServer(nil)
	client, ctx, _ := dialFollowEndpoint(t, server)
	requested := make(chan struct{}, 1)
	go func() {
		if _, err := client.Read(ctx); err == nil {
			requested <- struct{}{}
		}
	}()
	followCtx, cancel := context.WithCancel(ctx)
	events, err := server.RequestFollow(followCtx, "endpoint-1", followRequest("res-1"))
	if err != nil {
		t.Fatalf("request follow: %v", err)
	}
	select {
	case <-requested:
	case <-time.After(5 * time.Second):
		t.Fatal("endpoint did not receive the follow request")
	}
	cancel()
	select {
	case event, ok := <-events:
		if !ok {
			t.Fatal("event channel closed without a terminal end event")
		}
		if event.End == nil || event.End.ErrorCode != "cancelled" {
			t.Fatalf("event=%+v", event)
		}
	case <-time.After(5 * time.Second):
		t.Fatal("cancellation did not terminate the stream")
	}
	server.Mu.Lock()
	pending := len(server.pendingFollow)
	server.Mu.Unlock()
	if pending != 0 {
		t.Fatalf("pending follow entries=%d", pending)
	}
}

// TestRequestFollowRejectsOfflineEndpoint proves a follow for an Endpoint with no
// authoritative peer fails immediately instead of waiting for a deadline.
func TestRequestFollowRejectsOfflineEndpoint(t *testing.T) {
	server := NewServer(nil)
	ctx, cancel := context.WithTimeout(context.Background(), 2*time.Second)
	defer cancel()
	if _, err := server.RequestFollow(ctx, "endpoint-1", followRequest("res-1")); err == nil {
		t.Fatal("follow for an offline endpoint was accepted")
	}
	server.Mu.Lock()
	pending := len(server.pendingFollow)
	server.Mu.Unlock()
	if pending != 0 {
		t.Fatalf("pending follow entries=%d", pending)
	}
}

// TestRequestFollowBoundsConcurrentStreams proves the concurrency bound rejects a
// follow beyond capacity instead of queueing it, because a queued follow would
// start late while the operator already believes the stream is live.
func TestRequestFollowBoundsConcurrentStreams(t *testing.T) {
	server := NewServer(nil)
	client, ctx, _ := dialFollowEndpoint(t, server)
	// Drain the request frames so the Endpoint never answers and every admitted
	// follow stays pending.
	go func() {
		for {
			if _, err := client.Read(ctx); err != nil {
				return
			}
		}
	}()
	for i := 0; i < maxPendingFollow; i++ {
		if _, err := server.RequestFollow(ctx, "endpoint-1", followRequest("res-1")); err != nil {
			t.Fatalf("follow %d: %v", i, err)
		}
	}
	if _, err := server.RequestFollow(ctx, "endpoint-1", followRequest("res-1")); err == nil {
		t.Fatal("follow beyond capacity was accepted")
	}
}

// TestFollowOverflowEndsStreamWithExplicitCode proves a consumer that falls
// behind the bounded buffer learns that data was lost instead of receiving a
// partial stream that looks complete.
//
// The consumer deliberately does not read until the overflow is detected, so the
// queue really does fill. The terminal event is then delivered by discarding
// queued chunks, which is safe because the end event already declares the loss.
func TestFollowOverflowEndsStreamWithExplicitCode(t *testing.T) {
	server := NewServer(nil)
	client, ctx, _ := dialFollowEndpoint(t, server)
	reply := make(chan error, 1)
	go func() {
		frame, err := client.Read(ctx)
		if err != nil {
			reply <- err
			return
		}
		// One more chunk than the buffer holds, so the last delivery overflows.
		for i := 0; i <= followChunkBuffer; i++ {
			chunk := protocol.OutputChunk{Lines: []string{"line"}, ObservedAtMS: 1000}
			if err := client.SendFrame(ctx, Frame{Type: FrameOutputChunk, ProtocolVersion: ProtocolVersion, RequestID: frame.RequestID, OutputChunk: &chunk}); err != nil {
				reply <- err
				return
			}
		}
		reply <- nil
	}()
	events, err := server.RequestFollow(ctx, "endpoint-1", followRequest("res-1"))
	if err != nil {
		t.Fatalf("request follow: %v", err)
	}
	if err := <-reply; err != nil {
		t.Fatalf("endpoint reply: %v", err)
	}
	// Wait for the read loop to consume every frame and detect the overflow.
	deadline := time.Now().Add(5 * time.Second)
	for {
		server.Mu.Lock()
		pending := len(server.pendingFollow)
		server.Mu.Unlock()
		if pending == 0 {
			break
		}
		if time.Now().After(deadline) {
			t.Fatal("overflow was not detected")
		}
		time.Sleep(10 * time.Millisecond)
	}
	chunks := 0
	var end *protocol.OutputEnd
	for event := range events {
		if event.End != nil {
			end = event.End
			break
		}
		chunks++
	}
	if end == nil {
		t.Fatal("overflow did not terminate the stream")
	}
	if end.ErrorCode != "consumer_overflow" {
		t.Fatalf("end code=%q", end.ErrorCode)
	}
	// The end event must be delivered even though the queue was full, so the
	// consumer never mistakes a truncated stream for a finished one.
	if chunks > followChunkBuffer {
		t.Fatalf("chunks=%d", chunks)
	}
}

// TestDisconnectFailsPendingFollow proves a disconnected Endpoint never leaves a
// consumer waiting for chunks that can no longer arrive.
func TestDisconnectFailsPendingFollow(t *testing.T) {
	server := NewServer(nil)
	client, ctx, _ := dialFollowEndpoint(t, server)
	requested := make(chan struct{}, 1)
	go func() {
		if _, err := client.Read(ctx); err == nil {
			requested <- struct{}{}
		}
	}()
	events, err := server.RequestFollow(ctx, "endpoint-1", followRequest("res-1"))
	if err != nil {
		t.Fatalf("request follow: %v", err)
	}
	select {
	case <-requested:
	case <-time.After(5 * time.Second):
		t.Fatal("endpoint did not receive the follow request")
	}
	_ = client.Close()
	select {
	case event, ok := <-events:
		if !ok {
			t.Fatal("event channel closed without a terminal end event")
		}
		if event.End == nil || event.End.ErrorCode != "endpoint_offline" {
			t.Fatalf("event=%+v", event)
		}
	case <-time.After(5 * time.Second):
		t.Fatal("disconnect did not terminate the stream")
	}
}

// TestDisconnectFailsPendingOutput proves a disconnected Endpoint also fails a
// waiting snapshot request instead of letting it block until its own deadline.
func TestDisconnectFailsPendingOutput(t *testing.T) {
	server := NewServer(nil)
	client, ctx, _ := dialFollowEndpoint(t, server)
	requested := make(chan struct{}, 1)
	go func() {
		if _, err := client.Read(ctx); err == nil {
			requested <- struct{}{}
		}
	}()
	result := make(chan protocol.OutputSnapshotResponse, 1)
	go func() {
		response, _ := server.RequestOutput(ctx, "endpoint-1", protocol.OutputSnapshotRequest{EndpointID: "endpoint-1", ResourceID: "res-1", Generation: "generation-1"})
		result <- response
	}()
	select {
	case <-requested:
	case <-time.After(5 * time.Second):
		t.Fatal("endpoint did not receive the output request")
	}
	_ = client.Close()
	select {
	case response := <-result:
		if response.ErrorCode != "endpoint_offline" {
			t.Fatalf("error code=%q", response.ErrorCode)
		}
	case <-time.After(5 * time.Second):
		t.Fatal("disconnect did not fail the pending output request")
	}
}
