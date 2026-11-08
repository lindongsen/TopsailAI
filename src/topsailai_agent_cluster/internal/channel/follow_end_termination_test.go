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
func TestFollowEventChannelIsAlwaysBuffered(t *testing.T) {
	if followChunkBuffer <= 0 {
		t.Fatalf("followChunkBuffer=%d, an unbuffered follow channel would make deliverFollowEnd spin", followChunkBuffer)
	}
	server := NewServer(nil)
	_, ctx, _ := dialFollowEndpoint(t, server)
	events, err := server.RequestFollow(ctx, "endpoint-1", followRequest("res-1"))
	if err != nil {
		t.Fatalf("request follow: %v", err)
	}
	if cap(events) != followChunkBuffer {
		t.Fatalf("follow channel capacity=%d, want %d", cap(events), followChunkBuffer)
	}
}
