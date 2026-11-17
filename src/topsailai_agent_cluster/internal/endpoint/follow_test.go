package endpoint

import (
	"context"
	"errors"
	"fmt"
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
	service.startFollow(context.Background(), channel.Frame{Type: channel.FrameOutputFollowRequest, RequestID: "req-1", OutputFollowRequest: &protocol.OutputFollowRequest{ResourceID: "r", ProviderGeneration: "g"}})
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

// TestStartFollowReportsCapacityAsRetryable proves a capacity refusal ends the
// stream with a retryable code instead of provider_error. The adapter was never
// invoked, so the refusal proves nothing about the provider: reporting it as a
// provider failure sent the operator to investigate a provider that was never
// called, while the same follow may succeed unchanged once the competing
// invocation finishes.
func TestStartFollowReportsCapacityAsRetryable(t *testing.T) {
	executor := &followExecutor{followErr: fmt.Errorf("%w: discovery", adapter.ErrBusy)}
	service, transport := newFollowService(t, executor)
	service.startFollow(context.Background(), channel.Frame{Type: channel.FrameOutputFollowRequest, RequestID: "req-busy", OutputFollowRequest: &protocol.OutputFollowRequest{ResourceID: "r"}})
	waitForFrames(t, transport, channel.FrameOutputEnd, 1)
	transport.mu.Lock()
	end := transport.frames[len(transport.frames)-1].OutputEnd
	transport.mu.Unlock()
	if end == nil || end.ErrorCode != protocol.AdapterBusy {
		t.Fatalf("end=%#v want %s", end, protocol.AdapterBusy)
	}
}

// TestStartFollowReportsOutputLimitAsLocalBound proves a local byte budget ends the
// stream with output_limit instead of provider_error. The provider wrote valid
// frames and the Endpoint refused to buffer more of them, so reporting a provider
// failure sent the operator to investigate a component that behaved correctly.
func TestStartFollowReportsOutputLimitAsLocalBound(t *testing.T) {
	executor := &followExecutor{followErr: fmt.Errorf("provider stream: %w", adapter.ErrOutputLimit)}
	service, transport := newFollowService(t, executor)
	service.startFollow(context.Background(), channel.Frame{Type: channel.FrameOutputFollowRequest, RequestID: "req-limit", OutputFollowRequest: &protocol.OutputFollowRequest{ResourceID: "r"}})
	waitForFrames(t, transport, channel.FrameOutputEnd, 1)
	transport.mu.Lock()
	end := transport.frames[len(transport.frames)-1].OutputEnd
	transport.mu.Unlock()
	if end == nil || end.ErrorCode != protocol.OutputLimit {
		t.Fatalf("end=%#v want %s", end, protocol.OutputLimit)
	}
}

// TestCancelFollowReleasesSlot proves a cancel frame from the Server stops the
// follow and releases its concurrency slot.
//
// This is the property the operator depends on: stopping `logf` in the REPL must
// free the Endpoint's follow capacity immediately. Without the cancel the follow
// would keep its slot until the adapter deadline expired, which is two minutes in
// the deployed configuration, so two abandoned follows were enough to make the
// next follow wait for capacity it could not see.
func TestCancelFollowReleasesSlot(t *testing.T) {
	executor := &followExecutor{block: true, started: make(chan struct{})}
	service, transport := newFollowService(t, executor)
	service.startFollow(context.Background(), channel.Frame{Type: channel.FrameOutputFollowRequest, RequestID: "req-cancel", OutputFollowRequest: &protocol.OutputFollowRequest{ResourceID: "r"}})
	<-executor.started
	service.cancelFollow("req-cancel")
	waitForFrames(t, transport, channel.FrameOutputEnd, 1)
	transport.mu.Lock()
	end := transport.frames[len(transport.frames)-1].OutputEnd
	transport.mu.Unlock()
	if end == nil || end.ErrorCode != "cancelled" {
		t.Fatalf("end=%#v want cancelled", end)
	}
	// The slot must be free again, so a later follow is admitted rather than
	// refused. Asserting the slot directly is what distinguishes "the stream
	// stopped" from "the capacity came back", and only the second one is the
	// defect being fixed.
	deadline := time.Now().Add(2 * time.Second)
	for time.Now().Before(deadline) {
		if len(service.followSlots) == 0 {
			break
		}
		time.Sleep(5 * time.Millisecond)
	}
	if held := len(service.followSlots); held != 0 {
		t.Fatalf("follow slots still held=%d want 0", held)
	}
	service.followMu.Lock()
	active := len(service.activeFollows)
	service.followMu.Unlock()
	if active != 0 {
		t.Fatalf("active follows=%d want 0", active)
	}
}

// TestCancelFollowIgnoresUnknownRequest proves a cancel for a follow that already
// finished is a no-op. The Server sends the cancel only when it believes the
// Endpoint is still streaming, so this race is a correct sequence and must not be
// reported as a failure.
func TestCancelFollowIgnoresUnknownRequest(t *testing.T) {
	service, _ := newFollowService(t, &followExecutor{})
	service.cancelFollow("never-started")
	service.followMu.Lock()
	active := len(service.activeFollows)
	service.followMu.Unlock()
	if active != 0 {
		t.Fatalf("active follows=%d want 0", active)
	}
}
