package endpoint

import (
	"context"
	"errors"
	"sync"
	"testing"
	"time"

	"topsailai_agent_cluster/internal/adapter"
	"topsailai_agent_cluster/internal/channel"
	"topsailai_agent_cluster/internal/protocol"
)

// followExecutor is a CommandExecutor that also streams output. It lets a test
// drive chunk delivery and termination without a provider child process.
type followExecutor struct {
	coverageExecutor
	chunks    []protocol.OutputChunk
	followErr error
	block     bool
	started   chan struct{}
	once      sync.Once
}

func (e *followExecutor) FollowOutput(ctx context.Context, _ protocol.OutputFollowRequest, emit func(protocol.OutputChunk) error) error {
	if e.started != nil {
		e.once.Do(func() { close(e.started) })
	}
	for _, chunk := range e.chunks {
		if err := emit(chunk); err != nil {
			return err
		}
	}
	if e.block {
		<-ctx.Done()
		return ctx.Err()
	}
	return e.followErr
}

// waitForFrames polls until the transport holds at least count frames of kind.
func waitForFrames(t *testing.T, transport *serviceChannel, kind string, count int) {
	t.Helper()
	deadline := time.Now().Add(2 * time.Second)
	for time.Now().Before(deadline) {
		if transport.count(kind) >= count {
			return
		}
		time.Sleep(5 * time.Millisecond)
	}
	t.Fatalf("timed out waiting for %d %s frames, got %d", count, kind, transport.count(kind))
}

func newFollowService(t *testing.T, executor CommandExecutor) (*Service, *serviceChannel) {
	t.Helper()
	store := openCoverageStore(t)
	t.Cleanup(func() { store.Close() })
	transport := newServiceChannel()
	service, err := NewService(ServiceDeps{Collector: &serviceCollector{}, Channel: transport, Storage: store, Executor: executor})
	if err != nil {
		t.Fatal(err)
	}
	return service, transport
}

func TestStartFollowStreamsChunksAndOneEnd(t *testing.T) {
	executor := &followExecutor{chunks: []protocol.OutputChunk{{Lines: []string{"a"}}, {Lines: []string{"b"}}}}
	service, transport := newFollowService(t, executor)
	service.startFollow(context.Background(), channel.Frame{Type: channel.FrameOutputFollowRequest, RequestID: "req-1", OutputFollowRequest: &protocol.OutputFollowRequest{ResourceID: "r", Generation: "g"}})
	waitForFrames(t, transport, channel.FrameOutputEnd, 1)
	if got := transport.count(channel.FrameOutputChunk); got != 2 {
		t.Fatalf("chunks=%d want 2", got)
	}
	transport.mu.Lock()
	last := transport.frames[len(transport.frames)-1]
	transport.mu.Unlock()
	if last.Type != channel.FrameOutputEnd {
		t.Fatalf("last frame type=%q want end", last.Type)
	}
	if last.OutputEnd == nil || last.OutputEnd.ErrorCode != "" {
		t.Fatalf("end=%#v want clean termination", last.OutputEnd)
	}
	if last.RequestID != "req-1" {
		t.Fatalf("request id=%q", last.RequestID)
	}
}

func TestStartFollowRejectsUnsupportedAndInvalid(t *testing.T) {
	service, transport := newFollowService(t, coverageExecutor{})
	service.startFollow(context.Background(), channel.Frame{Type: channel.FrameOutputFollowRequest, RequestID: "nil"})
	service.startFollow(context.Background(), channel.Frame{Type: channel.FrameOutputFollowRequest, RequestID: "unsupported", OutputFollowRequest: &protocol.OutputFollowRequest{ResourceID: "r"}})
	waitForFrames(t, transport, channel.FrameOutputEnd, 2)
	transport.mu.Lock()
	codes := make([]string, 0, len(transport.frames))
	for _, frame := range transport.frames {
		if frame.OutputEnd != nil {
			codes = append(codes, frame.OutputEnd.ErrorCode)
		}
	}
	transport.mu.Unlock()
	if len(codes) != 2 || codes[0] != "invalid_request" || codes[1] != "unsupported" {
		t.Fatalf("end codes=%v", codes)
	}
}

func TestStartFollowReportsProviderError(t *testing.T) {
	executor := &followExecutor{followErr: errors.New("provider stream failed")}
	service, transport := newFollowService(t, executor)
	service.startFollow(context.Background(), channel.Frame{Type: channel.FrameOutputFollowRequest, RequestID: "req-err", OutputFollowRequest: &protocol.OutputFollowRequest{ResourceID: "r"}})
	waitForFrames(t, transport, channel.FrameOutputEnd, 1)
	transport.mu.Lock()
	end := transport.frames[len(transport.frames)-1].OutputEnd
	transport.mu.Unlock()
	if end == nil || end.ErrorCode != "provider_error" {
		t.Fatalf("end=%#v want provider_error", end)
	}
}

// TestStartFollowReportsUnsupportedWhenAdapterCannotStream proves an adapter that
// reports ErrUnsupported ends the stream with "unsupported" rather than
// "provider_error", because a missing capability is not a provider failure.
func TestStartFollowReportsUnsupportedWhenAdapterCannotStream(t *testing.T) {
	executor := &followExecutor{followErr: adapter.ErrUnsupported}
	service, transport := newFollowService(t, executor)
	service.startFollow(context.Background(), channel.Frame{Type: channel.FrameOutputFollowRequest, RequestID: "req-unsup", OutputFollowRequest: &protocol.OutputFollowRequest{ResourceID: "r"}})
	waitForFrames(t, transport, channel.FrameOutputEnd, 1)
	transport.mu.Lock()
	end := transport.frames[len(transport.frames)-1].OutputEnd
	transport.mu.Unlock()
	if end == nil || end.ErrorCode != "unsupported" {
		t.Fatalf("end=%#v want unsupported", end)
	}
}

func TestStartFollowRejectsBeyondConcurrencyBound(t *testing.T) {
	executor := &followExecutor{block: true, started: make(chan struct{})}
	service, transport := newFollowService(t, executor)
	for i := 0; i < maxConcurrentFollows; i++ {
		service.startFollow(context.Background(), channel.Frame{Type: channel.FrameOutputFollowRequest, RequestID: "req-" + string(rune('a'+i)), OutputFollowRequest: &protocol.OutputFollowRequest{ResourceID: "r"}})
	}
	<-executor.started
	service.startFollow(context.Background(), channel.Frame{Type: channel.FrameOutputFollowRequest, RequestID: "overflow", OutputFollowRequest: &protocol.OutputFollowRequest{ResourceID: "r"}})
	waitForFrames(t, transport, channel.FrameOutputEnd, 1)
	transport.mu.Lock()
	end := transport.frames[len(transport.frames)-1].OutputEnd
	transport.mu.Unlock()
	if end == nil || end.ErrorCode != "too_many_follows" {
		t.Fatalf("end=%#v want too_many_follows", end)
	}
	service.stopFollows()
}

func TestStartFollowRejectsDuplicateRequest(t *testing.T) {
	executor := &followExecutor{block: true, started: make(chan struct{})}
	service, transport := newFollowService(t, executor)
	frame := channel.Frame{Type: channel.FrameOutputFollowRequest, RequestID: "dup", OutputFollowRequest: &protocol.OutputFollowRequest{ResourceID: "r"}}
	service.startFollow(context.Background(), frame)
	<-executor.started
	service.startFollow(context.Background(), frame)
	waitForFrames(t, transport, channel.FrameOutputEnd, 1)
	transport.mu.Lock()
	end := transport.frames[len(transport.frames)-1].OutputEnd
	transport.mu.Unlock()
	if end == nil || end.ErrorCode != "duplicate_request" {
		t.Fatalf("end=%#v want duplicate_request", end)
	}
	service.stopFollows()
}

func TestStopFollowsCancelsActiveStream(t *testing.T) {
	executor := &followExecutor{block: true, started: make(chan struct{})}
	service, transport := newFollowService(t, executor)
	service.startFollow(context.Background(), channel.Frame{Type: channel.FrameOutputFollowRequest, RequestID: "cancel", OutputFollowRequest: &protocol.OutputFollowRequest{ResourceID: "r"}})
	<-executor.started
	service.stopFollows()
	waitForFrames(t, transport, channel.FrameOutputEnd, 1)
	transport.mu.Lock()
	end := transport.frames[len(transport.frames)-1].OutputEnd
	transport.mu.Unlock()
	if end == nil || end.ErrorCode != "cancelled" {
		t.Fatalf("end=%#v want cancelled", end)
	}
}

func TestRunFollowStampsObservationTime(t *testing.T) {
	executor := &followExecutor{chunks: []protocol.OutputChunk{{Lines: []string{"x"}}}}
	service, transport := newFollowService(t, executor)
	service.startFollow(context.Background(), channel.Frame{Type: channel.FrameOutputFollowRequest, RequestID: "stamp", OutputFollowRequest: &protocol.OutputFollowRequest{ResourceID: "r"}})
	waitForFrames(t, transport, channel.FrameOutputEnd, 1)
	transport.mu.Lock()
	chunk := transport.frames[0].OutputChunk
	transport.mu.Unlock()
	if chunk == nil || chunk.ObservedAtMS == 0 {
		t.Fatalf("chunk=%#v want observation time", chunk)
	}
}
