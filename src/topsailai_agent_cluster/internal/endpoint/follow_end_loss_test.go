package endpoint

import (
	"bytes"
	"context"
	"errors"
	"log/slog"
	"strings"
	"sync"
	"testing"
	"time"

	"topsailai_agent_cluster/internal/channel"
	"topsailai_agent_cluster/internal/protocol"
)

// offlineFollowChannel is a transport that refuses every frame while offline and
// records what it accepted once it is back. It lets a test prove that a terminal
// frame lost during a disconnect is never replayed, which is the best-effort
// contract this Endpoint implements.
type offlineFollowChannel struct {
	mu      sync.Mutex
	offline bool
	frames  []channel.Frame
	closed  chan struct{}
	once    sync.Once
}

func newOfflineFollowChannel() *offlineFollowChannel {
	return &offlineFollowChannel{offline: true, closed: make(chan struct{})}
}

func (c *offlineFollowChannel) Read(ctx context.Context) (channel.Frame, error) {
	select {
	case <-c.closed:
		return channel.Frame{}, errors.New("closed")
	case <-ctx.Done():
		return channel.Frame{}, ctx.Err()
	}
}

func (c *offlineFollowChannel) SendFrame(_ context.Context, frame channel.Frame) error {
	c.mu.Lock()
	defer c.mu.Unlock()
	if c.offline {
		return channel.ErrOffline
	}
	c.frames = append(c.frames, frame)
	return nil
}

func (c *offlineFollowChannel) Close() error {
	c.once.Do(func() { close(c.closed) })
	return nil
}

// setOffline flips the transport state so a test can reconnect it.
func (c *offlineFollowChannel) setOffline(offline bool) {
	c.mu.Lock()
	c.offline = offline
	c.mu.Unlock()
}

// count returns how many frames of one kind were accepted.
func (c *offlineFollowChannel) count(kind string) int {
	c.mu.Lock()
	defer c.mu.Unlock()
	count := 0
	for _, frame := range c.frames {
		if frame.Type == kind {
			count++
		}
	}
	return count
}

// newFollowEndLossService builds a Service over the offline transport with a log
// buffer, so a test can assert both the frame outcome and the diagnostic.
func newFollowEndLossService(t *testing.T, executor CommandExecutor) (*Service, *offlineFollowChannel, *bytes.Buffer) {
	t.Helper()
	store := openCoverageStore(t)
	t.Cleanup(func() { _ = store.Close() })
	transport := newOfflineFollowChannel()
	service, err := NewService(ServiceDeps{Collector: &serviceCollector{}, Channel: transport, Storage: store, Executor: executor})
	if err != nil {
		t.Fatal(err)
	}
	var logs bytes.Buffer
	service.logger = slog.New(slog.NewTextHandler(&logs, nil))
	return service, transport, &logs
}

// TestSendFollowEndRecordsLossWhenChannelOffline proves a terminal frame that
// cannot be sent is recorded as a contract event with the request ID and the code
// that was never delivered.
//
// The previous behaviour logged "deferred until the channel is ready", which was
// false: no retry exists, so the frame was lost rather than deferred. An operator
// reading that line would believe the Server eventually learned how the stream
// ended, when in fact it only learned that the Endpoint disconnected.
func TestSendFollowEndRecordsLossWhenChannelOffline(t *testing.T) {
	service, transport, logs := newFollowEndLossService(t, coverageExecutor{})

	service.sendFollowEnd(context.Background(), "req-lost", "cancelled", false)

	if got := transport.count(channel.FrameOutputEnd); got != 0 {
		t.Fatalf("end frames=%d, want none while offline", got)
	}
	output := logs.String()
	if !strings.Contains(output, "output follow terminal frame lost") {
		t.Fatalf("log=%q, want an explicit loss message", output)
	}
	if !strings.Contains(output, "request_id=req-lost") {
		t.Fatalf("log=%q, want the request ID so the loss is traceable", output)
	}
	if !strings.Contains(output, "error_code=cancelled") {
		t.Fatalf("log=%q, want the undelivered code", output)
	}
	if !strings.Contains(output, "level=WARN") {
		t.Fatalf("log=%q, want WARN for an offline channel", output)
	}
	if strings.Contains(output, "deferred") {
		t.Fatalf("log=%q, want no deferred wording because no retry exists", output)
	}
}

// TestSendFollowEndRecordsErrorForNonOfflineFailure proves a genuine transport
// failure is not downgraded to a connectivity warning.
func TestSendFollowEndRecordsErrorForNonOfflineFailure(t *testing.T) {
	store := openCoverageStore(t)
	t.Cleanup(func() { _ = store.Close() })
	transport := &readyCoverageChannel{serviceChannel: newServiceChannel(), ready: true, sendErr: errors.New("marshal failed")}
	service, err := NewService(ServiceDeps{Collector: &serviceCollector{}, Channel: transport, Storage: store})
	if err != nil {
		t.Fatal(err)
	}
	var logs bytes.Buffer
	service.logger = slog.New(slog.NewTextHandler(&logs, nil))

	service.sendFollowEnd(context.Background(), "req-broken", "provider_error", false)

	output := logs.String()
	if !strings.Contains(output, "level=ERROR") {
		t.Fatalf("log=%q, want ERROR for a real transport failure", output)
	}
	if !strings.Contains(output, "output follow terminal frame lost") {
		t.Fatalf("log=%q, want the loss message", output)
	}
}

// TestSendFollowEndIsNotReplayedAfterReconnect proves the terminal frame is
// best-effort: once the channel returns, the lost frame is not sent.
//
// This is the behaviour the contract now states. A test that asserted delivery
// after reconnect would describe the guaranteed option instead, which was
// explicitly rejected as a larger change than the contract requires.
func TestSendFollowEndIsNotReplayedAfterReconnect(t *testing.T) {
	service, transport, logs := newFollowEndLossService(t, coverageExecutor{})

	service.sendFollowEnd(context.Background(), "req-gone", "cancelled", false)
	if !strings.Contains(logs.String(), "output follow terminal frame lost") {
		t.Fatalf("log=%q, want the loss recorded while offline", logs.String())
	}

	transport.setOffline(false)
	// Give any hypothetical replay a chance to run before asserting its absence.
	time.Sleep(50 * time.Millisecond)

	if got := transport.count(channel.FrameOutputEnd); got != 0 {
		t.Fatalf("end frames=%d after reconnect, want none because delivery is best-effort", got)
	}
}

// TestRunFollowStillSendsExactlyOneEndOnNormalStop is the regression guard: the
// disconnect handling must not change the ordinary path, which still delivers
// exactly one terminal frame with a clean code.
func TestRunFollowStillSendsExactlyOneEndOnNormalStop(t *testing.T) {
	executor := &followExecutor{chunks: []protocol.OutputChunk{{Lines: []string{"a"}}, {Lines: []string{"b"}}}}
	service, transport := newFollowService(t, executor)

	service.startFollow(context.Background(), channel.Frame{
		Type:                channel.FrameOutputFollowRequest,
		RequestID:           "req-normal",
		OutputFollowRequest: &protocol.OutputFollowRequest{ResourceID: "r", ProviderGeneration: "g"},
	})
	waitForFrames(t, transport, channel.FrameOutputEnd, 1)

	if got := transport.count(channel.FrameOutputEnd); got != 1 {
		t.Fatalf("end frames=%d, want exactly one", got)
	}
	transport.mu.Lock()
	last := transport.frames[len(transport.frames)-1]
	transport.mu.Unlock()
	if last.Type != channel.FrameOutputEnd {
		t.Fatalf("last frame type=%q, want end", last.Type)
	}
	if last.OutputEnd == nil || last.OutputEnd.ErrorCode != "" {
		t.Fatalf("end=%#v, want a clean termination", last.OutputEnd)
	}
	if last.RequestID != "req-normal" {
		t.Fatalf("request id=%q, want req-normal", last.RequestID)
	}
}

// TestRunFollowRecordsLossWhenChannelDropsMidStream proves the loss is recorded
// on the real follow path, not only when sendFollowEnd is called directly.
//
// The adapter streams one chunk and then blocks, the channel goes offline, and
// the follow is cancelled. The terminal frame cannot be sent, so the loss must be
// recorded with the cancelled code.
func TestRunFollowRecordsLossWhenChannelDropsMidStream(t *testing.T) {
	executor := &followExecutor{block: true, started: make(chan struct{})}
	service, transport, logs := newFollowEndLossService(t, executor)

	service.startFollow(context.Background(), channel.Frame{
		Type:                channel.FrameOutputFollowRequest,
		RequestID:           "req-drop",
		OutputFollowRequest: &protocol.OutputFollowRequest{ResourceID: "r", ProviderGeneration: "g"},
	})
	<-executor.started
	service.stopFollows()
	service.wg.Wait()

	if got := transport.count(channel.FrameOutputEnd); got != 0 {
		t.Fatalf("end frames=%d, want none because the channel was offline", got)
	}
	output := logs.String()
	if !strings.Contains(output, "output follow terminal frame lost") {
		t.Fatalf("log=%q, want the loss recorded on the real follow path", output)
	}
	if !strings.Contains(output, "request_id=req-drop") {
		t.Fatalf("log=%q, want the request ID", output)
	}
	if !strings.Contains(output, "error_code=cancelled") {
		t.Fatalf("log=%q, want the cancelled code", output)
	}
}

// TestSendFollowEndWithoutLoggerDoesNotPanic proves a Service built without a
// logger still reports the loss safely. The Endpoint is constructed with an
// optional logger, so a nil logger must not turn a lost terminal frame into a
// crash on the shutdown path.
func TestSendFollowEndWithoutLoggerDoesNotPanic(t *testing.T) {
	store := openCoverageStore(t)
	t.Cleanup(func() { _ = store.Close() })
	transport := newOfflineFollowChannel()
	service, err := NewService(ServiceDeps{Collector: &serviceCollector{}, Channel: transport, Storage: store})
	if err != nil {
		t.Fatal(err)
	}
	if service.logger != nil {
		t.Fatal("test requires a Service without a logger")
	}

	service.sendFollowEnd(context.Background(), "req-nolog", "cancelled", false)

	if got := transport.count(channel.FrameOutputEnd); got != 0 {
		t.Fatalf("end frames=%d, want none while offline", got)
	}
}
