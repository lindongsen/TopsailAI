package channel

import (
	"context"
	"errors"
	"testing"
	"time"

	"topsailai_agent_cluster/internal/protocol"
)

// blockBusinessWorker installs an OnFrame hook that blocks on the first
// inventory frame, so the peer's worker is occupied and its bounded queue is the
// only place a later frame can go. It returns a release function.
//
// The hook is what makes the queue reachable: while the worker is idle it drains
// every frame immediately, so a full queue can only be observed when the worker
// is genuinely busy. That is exactly the state a slow database write produces in
// production.
func blockBusinessWorker(t *testing.T, server *Server) func() {
	t.Helper()
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
	return func() {
		close(release)
		select {
		case <-entered:
		case <-time.After(2 * time.Second):
		}
	}
}

// occupyBusinessWorker sends one inventory frame and waits until the hook is
// running, so the worker is provably busy before the caller sends anything else.
func occupyBusinessWorker(t *testing.T, client *EndpointClient, ctx context.Context) {
	t.Helper()
	if err := client.SendFrame(ctx, inventoryFrame("occupies-worker", 1)); err != nil {
		t.Fatalf("send occupying inventory: %v", err)
	}
	// The hook signals by blocking; a short sleep is enough because the frame is
	// already written and the worker is the only consumer.
	time.Sleep(100 * time.Millisecond)
}

// TestFollowChunksDoNotFillTheBusinessQueue is the regression for the reported
// `logf` failure.
//
// The read loop dispatched follow chunks to their consumer and then also offered
// the same frame to the peer's bounded business queue. A follow tail is one frame
// per record, so a 300-line tail offered 300 frames to a queue of 16. Once the
// queue was full the read loop closed the whole connection, and the Server
// reported the follow as `endpoint_offline` even though the Endpoint was healthy.
//
// A follow frame is fully handled by deliverFollow, and the worker's OnFrame hook
// ignores every frame that is not an inventory report, so queueing it can only
// destroy the link.
func TestFollowChunksDoNotFillTheBusinessQueue(t *testing.T) {
	server := NewServer(nil)
	defer server.Close()
	release := blockBusinessWorker(t, server)
	defer release()

	client, ctx, _ := dialFollowEndpoint(t, server)
	occupyBusinessWorker(t, client, ctx)

	reply := make(chan error, 1)
	go func() {
		frame, err := client.Read(ctx)
		if err != nil {
			reply <- err
			return
		}
		if frame.Type != FrameOutputFollowRequest {
			reply <- errors.New("unexpected follow request frame")
			return
		}
		// One frame per record, which is how the Endpoint streams a tail.
		for i := 0; i < businessQueueDepth+8; i++ {
			chunk := protocol.OutputChunk{Lines: []string{"line"}, ObservedAtMS: 1000}
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

	chunks := 0
	for event := range events {
		if event.End != nil {
			if event.End.ErrorCode != "" {
				t.Fatalf("follow ended with %q, want the endpoint's own clean end", event.End.ErrorCode)
			}
			break
		}
		chunks++
	}
	if chunks != businessQueueDepth+8 {
		t.Fatalf("delivered %d chunks, want %d", chunks, businessQueueDepth+8)
	}

	server.Mu.RLock()
	_, active := server.Active["endpoint-1"]
	server.Mu.RUnlock()
	if !active {
		t.Fatal("a follow burst must not disconnect the peer")
	}
}

// TestFollowTerminalFrameDoesNotFillTheBusinessQueue proves the terminal frame is
// excluded from the business queue too, because it travels the same dispatch path
// and a single frame is enough to close a queue that is already full.
func TestFollowTerminalFrameDoesNotFillTheBusinessQueue(t *testing.T) {
	server := NewServer(nil)
	defer server.Close()
	release := blockBusinessWorker(t, server)
	defer release()

	client, ctx, _ := dialFollowEndpoint(t, server)
	occupyBusinessWorker(t, client, ctx)

	reply := make(chan error, 1)
	go func() {
		frame, err := client.Read(ctx)
		if err != nil {
			reply <- err
			return
		}
		if frame.Type != FrameOutputFollowRequest {
			reply <- errors.New("unexpected follow request frame")
			return
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

	for event := range events {
		if event.End != nil {
			if event.End.ErrorCode != "" {
				t.Fatalf("follow ended with %q, want a clean end", event.End.ErrorCode)
			}
			break
		}
	}

	server.Mu.RLock()
	_, active := server.Active["endpoint-1"]
	server.Mu.RUnlock()
	if !active {
		t.Fatal("a follow terminal frame must not disconnect the peer")
	}
}

// TestBusinessQueueOverflowStillClosesPeer guards the behaviour the fix must not
// remove. A peer that cannot absorb its own durable frames is genuinely
// unhealthy, so a full queue of inventory frames must still close the connection.
func TestBusinessQueueOverflowStillClosesPeer(t *testing.T) {
	server := NewServer(nil)
	defer server.Close()
	release := blockBusinessWorker(t, server)
	defer release()

	client, ctx, _ := dialFollowEndpoint(t, server)
	occupyBusinessWorker(t, client, ctx)

	for i := 0; i < businessQueueDepth+1; i++ {
		if err := client.SendFrame(ctx, inventoryFrame("fills-queue", int64(i+2))); err != nil {
			break
		}
	}

	deadline := time.Now().Add(3 * time.Second)
	for time.Now().Before(deadline) {
		server.Mu.RLock()
		_, active := server.Active["endpoint-1"]
		server.Mu.RUnlock()
		if !active {
			return
		}
		time.Sleep(20 * time.Millisecond)
	}
	t.Fatal("a full business queue must still close the peer")
}
