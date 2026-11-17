package endpoint

import (
	"context"
	"errors"
	"sync"
	"testing"
	"time"

	"topsailai_agent_cluster/internal/channel"
	"topsailai_agent_cluster/internal/protocol"
	endpointstorage "topsailai_agent_cluster/internal/storage/endpoint"
)

// blockingExecutor holds every Execute call until the test releases it, so a
// scenario can observe what the channel read loop does while one command is in
// flight.
type blockingExecutor struct {
	started chan struct{}
	release chan struct{}
	once    sync.Once
}

func newBlockingExecutor() *blockingExecutor {
	return &blockingExecutor{started: make(chan struct{}), release: make(chan struct{})}
}

func (e *blockingExecutor) Execute(ctx context.Context, intent protocol.ImmutableIntent, _ string) (protocol.ExecutionReceipt, error) {
	e.once.Do(func() { close(e.started) })
	select {
	case <-e.release:
	case <-ctx.Done():
		return protocol.ExecutionReceipt{}, ctx.Err()
	}
	return protocol.ExecutionReceipt{CommandID: intent.CommandID}, nil
}

// independenceChannel delivers queued frames and records acknowledgements, so a
// scenario can prove the read loop kept consuming frames while a command ran.
type independenceChannel struct {
	mu     sync.Mutex
	frames chan channel.Frame
	acks   int
	closed chan struct{}
	once   sync.Once
}

func newIndependenceChannel() *independenceChannel {
	return &independenceChannel{frames: make(chan channel.Frame, 8), closed: make(chan struct{})}
}

func (c *independenceChannel) Read(ctx context.Context) (channel.Frame, error) {
	select {
	case frame := <-c.frames:
		return frame, nil
	case <-c.closed:
		return channel.Frame{}, errors.New("closed")
	case <-ctx.Done():
		return channel.Frame{}, ctx.Err()
	}
}

func (c *independenceChannel) SendFrame(context.Context, channel.Frame) error { return nil }

func (c *independenceChannel) Close() error {
	c.once.Do(func() { close(c.closed) })
	return nil
}

func (c *independenceChannel) AcknowledgeHeartbeat() {
	c.mu.Lock()
	c.acks++
	c.mu.Unlock()
}

func (c *independenceChannel) ackCount() int {
	c.mu.Lock()
	defer c.mu.Unlock()
	return c.acks
}

func (c *independenceChannel) push(frame channel.Frame) {
	c.frames <- frame
}

// TestChannelLoopConsumesHeartbeatAckWhileCommandRuns proves liveness and
// business work are independent.
//
// The read loop is the only reader of the connection, so a command executed
// inline delays the heartbeat acknowledgement behind the whole provider
// invocation. The acknowledgement wait is 3s and the unhealthy window is 30s,
// while a Provider CLI invocation may run for 120s, so an inline command made a
// healthy Endpoint declare the Server unhealthy and tear the link down. This
// scenario holds one command open and requires the loop to keep recording
// acknowledgements, which is exactly what the inline version could not do.
func TestChannelLoopConsumesHeartbeatAckWhileCommandRuns(t *testing.T) {
	store, err := endpointstorage.Open(context.Background(), t.TempDir()+"/endpoint.sqlite")
	if err != nil {
		t.Fatal(err)
	}
	defer store.Close()

	executor := newBlockingExecutor()
	transport := newIndependenceChannel()
	service, err := NewService(ServiceDeps{
		Collector:         &serviceCollector{},
		Executor:          executor,
		Channel:           transport,
		Storage:           store,
		CollectionDelay:   time.Hour,
		HeartbeatInterval: time.Hour,
	})
	if err != nil {
		t.Fatal(err)
	}

	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	service.wg.Add(1)
	go service.channelLoop(ctx)

	intent := protocol.ImmutableIntent{
		HashVersion:          "v1",
		CommandID:            "cmd-1",
		EndpointID:           "ep-1",
		Operation:            "agent.start",
		OperationVersion:     "v1",
		CapabilityRevision:   "rev-1",
		PayloadSchemaVersion: "v1",
		Payload:              []byte(`{}`),
	}
	transport.push(channel.Frame{Type: channel.FrameCommand, FrameID: "cmd-1", Intent: &intent})

	select {
	case <-executor.started:
	case <-time.After(2 * time.Second):
		t.Fatal("command never started")
	}

	// The command is still held open. A read loop that ran it inline would be
	// blocked here and could not consume the acknowledgements below.
	for i := 0; i < 3; i++ {
		transport.push(channel.Frame{Type: channel.FrameHeartbeatAck})
	}
	deadline := time.After(2 * time.Second)
	for transport.ackCount() < 3 {
		select {
		case <-deadline:
			t.Fatalf("read loop consumed %d of 3 heartbeat acknowledgements while a command was running", transport.ackCount())
		case <-time.After(5 * time.Millisecond):
		}
	}

	close(executor.release)
	cancel()
	service.wg.Wait()
}

// TestChannelLoopKeepsReadingAfterBusinessHandlerReturns proves the loop is not
// consumed by one dispatch: a second frame must still be delivered after the
// first handler finished.
func TestChannelLoopKeepsReadingAfterBusinessHandlerReturns(t *testing.T) {
	store, err := endpointstorage.Open(context.Background(), t.TempDir()+"/endpoint.sqlite")
	if err != nil {
		t.Fatal(err)
	}
	defer store.Close()

	transport := newIndependenceChannel()
	service, err := NewService(ServiceDeps{
		Collector:         &serviceCollector{},
		Channel:           transport,
		Storage:           store,
		CollectionDelay:   time.Hour,
		HeartbeatInterval: time.Hour,
	})
	if err != nil {
		t.Fatal(err)
	}

	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	service.wg.Add(1)
	go service.channelLoop(ctx)

	transport.push(channel.Frame{Type: channel.FrameHeartbeatAck})
	transport.push(channel.Frame{Type: channel.FrameHeartbeatAck})

	deadline := time.After(2 * time.Second)
	for transport.ackCount() < 2 {
		select {
		case <-deadline:
			t.Fatalf("read loop consumed %d of 2 heartbeat acknowledgements", transport.ackCount())
		case <-time.After(5 * time.Millisecond):
		}
	}

	cancel()
	service.wg.Wait()
}
