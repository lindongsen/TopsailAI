package endpoint

import (
	"context"
	"sync"
	"testing"
	"time"

	"topsailai_agent_cluster/internal/channel"
	"topsailai_agent_cluster/internal/protocol"
)

// writeContextChannel records whether the context handed to SendFrame was already
// cancelled at the moment of the write.
//
// The channel is one websocket shared by every follow, heartbeat, inventory report
// and response, and the websocket library closes the whole connection on any error
// from any method, including a context expiration. A follow frame written with the
// follow's own cancelled context therefore destroyed the entire link, and every
// request in the reconnect window was reported as endpoint_offline on a healthy
// Endpoint. Recording the context state is the only way to observe that defect from
// a test: the frame still arrives, so counting frames proves nothing.
type writeContextChannel struct {
	mu sync.Mutex
	// cancelledWrites counts writes whose context was already cancelled.
	cancelledWrites int
	// liveWrites counts writes whose context was still usable.
	liveWrites int
	// deadlineWrites counts writes whose context carried a deadline.
	deadlineWrites int
	frames         []channel.Frame
	closed         chan struct{}
	once           sync.Once
}

func newWriteContextChannel() *writeContextChannel {
	return &writeContextChannel{closed: make(chan struct{})}
}

func (c *writeContextChannel) Read(ctx context.Context) (channel.Frame, error) {
	select {
	case <-c.closed:
		return channel.Frame{}, context.Canceled
	case <-ctx.Done():
		return channel.Frame{}, ctx.Err()
	}
}

func (c *writeContextChannel) SendFrame(ctx context.Context, frame channel.Frame) error {
	c.mu.Lock()
	defer c.mu.Unlock()
	if ctx.Err() != nil {
		c.cancelledWrites++
	} else {
		c.liveWrites++
	}
	if _, ok := ctx.Deadline(); ok {
		c.deadlineWrites++
	}
	c.frames = append(c.frames, frame)
	return nil
}

func (c *writeContextChannel) Close() error {
	c.once.Do(func() { close(c.closed) })
	return nil
}

func (c *writeContextChannel) snapshot() (cancelled, live, deadline int) {
	c.mu.Lock()
	defer c.mu.Unlock()
	return c.cancelledWrites, c.liveWrites, c.deadlineWrites
}

// TestFollowWriteSurvivesFollowCancellation proves a cancelled follow does not
// cancel the write of its own frames.
//
// This is the regression test for the second cause of endpoint_offline. The
// Endpoint writes follow frames onto the connection that carries every other
// frame, so a write performed with the follow's context made one follow's
// cancellation fail the write, and the websocket library then closed the whole
// connection. The test cancels the follow context before the terminal frame is
// written and asserts that no write ever saw a cancelled context.
//
// It fails when the write is performed with the follow's own context, because the
// terminal frame is then written after cancellation and is counted as a cancelled
// write.
func TestFollowWriteSurvivesFollowCancellation(t *testing.T) {
	store := openCoverageStore(t)
	t.Cleanup(func() { store.Close() })
	transport := newWriteContextChannel()
	service, err := NewService(ServiceDeps{Collector: &serviceCollector{}, Channel: transport, Storage: store, Executor: &followExecutor{}})
	if err != nil {
		t.Fatal(err)
	}

	ctx, cancel := context.WithCancel(context.Background())
	// Cancel before the follow runs, so every write it performs happens with a
	// context that is already cancelled. This is the strongest form of the
	// condition: a single follow whose lifetime ended before it wrote anything.
	cancel()
	service.runFollow(ctx, "req-cancelled", &followExecutor{}, protocol.OutputFollowRequest{ResourceID: "r", ProviderGeneration: "g"})

	cancelled, live, _ := transport.snapshot()
	if cancelled != 0 {
		t.Fatalf("writes with a cancelled context = %d, want 0: a follow write must not inherit the follow's cancellation", cancelled)
	}
	if live == 0 {
		t.Fatal("no live writes recorded, so the assertion proved nothing")
	}
}

// TestFollowWriteIsBounded proves each follow write carries its own deadline.
//
// Detaching the context must not make the write unbounded. The connection's write
// lock is shared, so an unbounded write would delay every heartbeat, inventory
// report and response on the same link. The deadline is the property that keeps a
// detached write from becoming a stall.
func TestFollowWriteIsBounded(t *testing.T) {
	store := openCoverageStore(t)
	t.Cleanup(func() { store.Close() })
	transport := newWriteContextChannel()
	service, err := NewService(ServiceDeps{Collector: &serviceCollector{}, Channel: transport, Storage: store, Executor: &followExecutor{}})
	if err != nil {
		t.Fatal(err)
	}

	service.runFollow(context.Background(), "req-bounded", &followExecutor{chunks: []protocol.OutputChunk{{Lines: []string{"a"}}}}, protocol.OutputFollowRequest{ResourceID: "r", ProviderGeneration: "g"})

	_, live, deadline := transport.snapshot()
	if live == 0 {
		t.Fatal("no writes recorded, so the assertion proved nothing")
	}
	if deadline != live {
		t.Fatalf("writes with a deadline = %d of %d, want every write bounded", deadline, live)
	}
}

// TestFollowWriteKeepsChunksAndEndOrder proves detaching the context does not
// change the stream contract.
//
// The fix must not reorder or drop frames: a consumer relies on chunks arriving
// before exactly one terminal frame. This test guards the contract while the
// context handling changes underneath it.
func TestFollowWriteKeepsChunksAndEndOrder(t *testing.T) {
	store := openCoverageStore(t)
	t.Cleanup(func() { store.Close() })
	transport := newWriteContextChannel()
	service, err := NewService(ServiceDeps{Collector: &serviceCollector{}, Channel: transport, Storage: store, Executor: &followExecutor{}})
	if err != nil {
		t.Fatal(err)
	}

	executor := &followExecutor{chunks: []protocol.OutputChunk{{Lines: []string{"a"}}, {Lines: []string{"b"}}}}
	service.runFollow(context.Background(), "req-order", executor, protocol.OutputFollowRequest{ResourceID: "r", ProviderGeneration: "g"})

	transport.mu.Lock()
	defer transport.mu.Unlock()
	if len(transport.frames) != 3 {
		t.Fatalf("frames=%d want 3 (two chunks and one end)", len(transport.frames))
	}
	if transport.frames[0].Type != channel.FrameOutputChunk || transport.frames[1].Type != channel.FrameOutputChunk {
		t.Fatalf("first frames = %q,%q want chunk,chunk", transport.frames[0].Type, transport.frames[1].Type)
	}
	if transport.frames[2].Type != channel.FrameOutputEnd {
		t.Fatalf("last frame = %q want end", transport.frames[2].Type)
	}
}

// TestFollowWriteTimeoutIsPositive guards the budget against a zero value.
//
// A zero timeout would make every follow write fail immediately, which would look
// like a transport fault on a healthy connection. The constant is asserted rather
// than trusted because it is the only thing standing between a detached context
// and an unbounded write.
func TestFollowWriteTimeoutIsPositive(t *testing.T) {
	if followWriteTimeout <= 0 {
		t.Fatalf("followWriteTimeout = %v, want a positive budget", followWriteTimeout)
	}
	if followWriteTimeout > 30*time.Second {
		t.Fatalf("followWriteTimeout = %v, want a budget below the heartbeat window", followWriteTimeout)
	}
}
