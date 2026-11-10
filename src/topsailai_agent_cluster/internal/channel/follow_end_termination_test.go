package channel

import (
	"testing"
	"time"

	"topsailai_agent_cluster/internal/protocol"
)

// TestDeliverFollowEndCannotSpinOnBufferedQueue locks the invariant that makes
// deliverFollowEnd terminate instead of busy-looping.
//
// The loop is safe because the follow event channel is always buffered. On a
// buffered channel the two selects cannot both take their default branch: a full
// queue makes the send default and the receive succeed, and a non-full queue
// makes the send succeed. The loop therefore discards at most one queued chunk
// and returns, even when the consumer never reads again.
//
// This test exists so a future change cannot "fix" a reported spin by adding a
// sleep or a backoff. Such a change would slow the ordinary overflow path, which
// is the path that must report data loss promptly, without fixing anything.
func TestDeliverFollowEndCannotSpinOnBufferedQueue(t *testing.T) {
	events := make(chan FollowEvent, followChunkBuffer)
	for i := 0; i < followChunkBuffer; i++ {
		events <- FollowEvent{Chunk: &protocol.OutputChunk{Lines: []string{"x"}}}
	}

	done := make(chan struct{})
	go func() {
		deliverFollowEnd(events, &protocol.OutputEnd{ErrorCode: "consumer_overflow"})
		close(done)
	}()

	select {
	case <-done:
	case <-time.After(2 * time.Second):
		t.Fatal("deliverFollowEnd did not return with a full queue and an idle consumer")
	}

	// The terminal frame must be present in the queue, so a consumer that resumes
	// reading learns that data was lost instead of seeing a truncated stream.
	// It sits behind the surviving chunks, which is correct: the end is the last
	// event of its stream.
	var end *protocol.OutputEnd
	remaining := 0
	for {
		select {
		case event := <-events:
			if event.End != nil {
				end = event.End
			} else {
				remaining++
			}
			continue
		default:
		}
		break
	}
	if end == nil {
		t.Fatal("the terminal frame was not delivered")
	}
	if end.ErrorCode != "consumer_overflow" {
		t.Fatalf("end code=%q, want consumer_overflow", end.ErrorCode)
	}
	if remaining != followChunkBuffer-1 {
		t.Fatalf("surviving chunks=%d, want %d: the loop must discard exactly one chunk", remaining, followChunkBuffer-1)
	}
}

// TestDeliverFollowEndTerminatesUnderConcurrentDrain proves the loop also
// terminates when a consumer drains concurrently, which is the only situation
// where both selects could otherwise take their default branch.
func TestDeliverFollowEndTerminatesUnderConcurrentDrain(t *testing.T) {
	for round := 0; round < 200; round++ {
		events := make(chan FollowEvent, followChunkBuffer)
		for i := 0; i < followChunkBuffer; i++ {
			events <- FollowEvent{Chunk: &protocol.OutputChunk{Lines: []string{"x"}}}
		}
		stop := make(chan struct{})
		drained := make(chan struct{})
		go func() {
			defer close(drained)
			for {
				select {
				case <-stop:
					return
				default:
				}
				select {
				case <-events:
				default:
				}
			}
		}()

		done := make(chan struct{})
		go func() {
			deliverFollowEnd(events, &protocol.OutputEnd{ErrorCode: "consumer_overflow"})
			close(done)
		}()

		select {
		case <-done:
		case <-time.After(2 * time.Second):
			close(stop)
			<-drained
			t.Fatalf("round %d: deliverFollowEnd did not return under concurrent drain", round)
		}
		close(stop)
		<-drained
	}
}

// TestFollowEventChannelIsAlwaysBuffered guards the precondition the loop relies
// on. An unbuffered follow channel would let both selects default and turn the
// loop into a real spin, so the buffer is a correctness requirement rather than
// a tuning choice.
//
// The capacity is derived from the requested tail, so the assertion is that the
// derived value is positive and is what the channel actually got. Asserting a
// fixed constant here would pin the defect this change removes.
func TestFollowEventChannelIsAlwaysBuffered(t *testing.T) {
	if followChunkBuffer <= 0 {
		t.Fatalf("followChunkBuffer=%d, an unbuffered follow channel would make deliverFollowEnd spin", followChunkBuffer)
	}
	server := NewServer(nil)
	_, ctx, _ := dialFollowEndpoint(t, server)
	request := followRequest("res-1")
	events, err := server.RequestFollow(ctx, "endpoint-1", request)
	if err != nil {
		t.Fatalf("request follow: %v", err)
	}
	want := followQueueCapacity(request.MaxLines)
	if want <= 0 {
		t.Fatalf("followQueueCapacity(%d)=%d, an unbuffered follow channel would make deliverFollowEnd spin", request.MaxLines, want)
	}
	if cap(events) != want {
		t.Fatalf("follow channel capacity=%d, want %d", cap(events), want)
	}
}

// TestFollowQueueCapacityCoversTheRequestedTail proves the queue is never
// smaller than the tail the caller asked for.
//
// The Endpoint delivers one frame per record, so a queue smaller than the tail
// fills before the consumer can drain it and the Server then reports a healthy
// consumer as a stalled one. That is the consumer_overflow defect: the operator
// asked for 300 lines, the queue held 64, and the stream died at record 63.
func TestFollowQueueCapacityCoversTheRequestedTail(t *testing.T) {
	for _, maxLines := range []int{0, 1, 20, 100, 300, 1000, 10000} {
		capacity := followQueueCapacity(maxLines)
		if capacity < maxLines {
			t.Fatalf("followQueueCapacity(%d)=%d, the queue is smaller than the requested tail", maxLines, capacity)
		}
		if capacity < followChunkBuffer {
			t.Fatalf("followQueueCapacity(%d)=%d, below the buffered floor %d", maxLines, capacity, followChunkBuffer)
		}
		if capacity > followMaxChunkBuffer {
			t.Fatalf("followQueueCapacity(%d)=%d, above the ceiling %d", maxLines, capacity, followMaxChunkBuffer)
		}
	}
}

// TestFollowQueueCapacityIsBounded proves a large requested tail cannot reserve
// unbounded Server memory, so the derivation is a bound rather than a removal of
// the bound.
func TestFollowQueueCapacityIsBounded(t *testing.T) {
	if got := followQueueCapacity(1 << 30); got != followMaxChunkBuffer {
		t.Fatalf("followQueueCapacity(1<<30)=%d, want the ceiling %d", got, followMaxChunkBuffer)
	}
	if got := followQueueCapacity(-5); got != followChunkBuffer {
		t.Fatalf("followQueueCapacity(-5)=%d, want the floor %d", got, followChunkBuffer)
	}
}

// TestFollowDeliversAFullTailToASlowConsumer reproduces the reported defect end
// to end: a requested tail delivered as one frame per record, consumed by a
// reader that pays a small per-record cost.
//
// Before the queue was derived from the tail, this ended with consumer_overflow
// after 63 of 300 records. The per-record cost is what makes the difference
// visible: a consumer that reads instantly can drain a 64-slot queue, so a test
// without that cost would pass on the broken code and prove nothing.
func TestFollowDeliversAFullTailToASlowConsumer(t *testing.T) {
	const tail = 300
	server := NewServer(nil)
	client, ctx, _ := dialFollowEndpoint(t, server)
	request := followRequest("res-1")
	request.MaxLines = tail
	reply := make(chan error, 1)
	go func() {
		frame, err := client.Read(ctx)
		if err != nil {
			reply <- err
			return
		}
		for i := 0; i < tail; i++ {
			chunk := protocol.OutputChunk{Lines: []string{"line"}, ObservedAtMS: 1000}
			if err := client.SendFrame(ctx, Frame{Type: FrameOutputChunk, ProtocolVersion: ProtocolVersion, RequestID: frame.RequestID, OutputChunk: &chunk}); err != nil {
				reply <- err
				return
			}
		}
		end := protocol.OutputEnd{ObservedAtMS: 2000}
		reply <- client.SendFrame(ctx, Frame{Type: FrameOutputEnd, ProtocolVersion: ProtocolVersion, RequestID: frame.RequestID, OutputEnd: &end})
	}()
	events, err := server.RequestFollow(ctx, "endpoint-1", request)
	if err != nil {
		t.Fatalf("request follow: %v", err)
	}
	if err := <-reply; err != nil {
		t.Fatalf("endpoint reply: %v", err)
	}
	chunks := 0
	var end *protocol.OutputEnd
	for event := range events {
		if event.End != nil {
			end = event.End
			break
		}
		chunks++
		// A consumer that pays one HTTP write plus flush per record.
		time.Sleep(200 * time.Microsecond)
	}
	if end == nil {
		t.Fatal("the stream did not terminate")
	}
	if end.ErrorCode != "" {
		t.Fatalf("a healthy consumer was reported as %q after %d of %d records", end.ErrorCode, chunks, tail)
	}
	if chunks != tail {
		t.Fatalf("chunks=%d want=%d", chunks, tail)
	}
}
