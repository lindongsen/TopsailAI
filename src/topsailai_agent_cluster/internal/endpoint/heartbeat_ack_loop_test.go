package endpoint

import (
	"context"
	"errors"
	"sync"
	"testing"
	"time"

	"topsailai_agent_cluster/internal/channel"
	endpointstorage "topsailai_agent_cluster/internal/storage/endpoint"
)

// ackRecordingChannel is a channel client that also reports heartbeat
// acknowledgements, so a test can observe whether the channel loop recorded one.
//
// It exists because the acknowledgement has two possible paths to the same
// method: the channel loop records it when the Server's frame arrives, and the
// heartbeat sender waits for it. A scenario that asserts on the unhealthy
// decision therefore cannot prove the loop path exists, because the sender path
// reaches the same decision on its own. Only a test that drives the loop with a
// real acknowledgement frame can prove the loop records it.
type ackRecordingChannel struct {
	mu     sync.Mutex
	acks   int
	frames chan channel.Frame
	closed chan struct{}
	once   sync.Once
}

func newAckRecordingChannel() *ackRecordingChannel {
	return &ackRecordingChannel{frames: make(chan channel.Frame, 1), closed: make(chan struct{})}
}

func (c *ackRecordingChannel) Read(ctx context.Context) (channel.Frame, error) {
	select {
	case frame := <-c.frames:
		return frame, nil
	case <-c.closed:
		return channel.Frame{}, errors.New("closed")
	case <-ctx.Done():
		return channel.Frame{}, ctx.Err()
	}
}

func (c *ackRecordingChannel) SendFrame(context.Context, channel.Frame) error { return nil }

func (c *ackRecordingChannel) Close() error {
	c.once.Do(func() { close(c.closed) })
	return nil
}

func (c *ackRecordingChannel) AcknowledgeHeartbeat() {
	c.mu.Lock()
	c.acks++
	c.mu.Unlock()
}

func (c *ackRecordingChannel) acknowledgementCount() int {
	c.mu.Lock()
	defer c.mu.Unlock()
	return c.acks
}

// TestChannelLoopRecordsHeartbeatAcknowledgement pins the loop half of the
// liveness rule.
//
// The channel loop is the single reader of the connection, so it is the only
// place an acknowledgement frame can be observed. If this case is removed the
// heartbeat sender never learns that the Server answered, every beat looks
// unacknowledged, and a healthy Server is declared unhealthy after one window.
// No BDD scenario covers this, because those scenarios assert on the unhealthy
// decision, which the sender reaches on its own.
func TestChannelLoopRecordsHeartbeatAcknowledgement(t *testing.T) {
	store, err := endpointstorage.Open(context.Background(), t.TempDir()+"/endpoint.sqlite")
	if err != nil {
		t.Fatalf("open endpoint storage: %v", err)
	}
	defer store.Close()

	transport := newAckRecordingChannel()
	service, err := NewService(ServiceDeps{Collector: &serviceCollector{}, Channel: transport, Storage: store, CollectionDelay: time.Hour})
	if err != nil {
		t.Fatalf("construct service: %v", err)
	}

	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	service.wg.Add(1)
	go service.channelLoop(ctx)

	transport.frames <- channel.Frame{Type: channel.FrameHeartbeatAck}

	deadline := time.After(2 * time.Second)
	for transport.acknowledgementCount() < 1 {
		select {
		case <-deadline:
			t.Fatal("the channel loop did not record the heartbeat acknowledgement, so a healthy Server would be declared unhealthy after one window")
		default:
			time.Sleep(time.Millisecond)
		}
	}

	cancel()
	service.wg.Wait()
}

// TestChannelLoopIgnoresOtherFramesForAcknowledgement pins that the loop records
// an acknowledgement only for an acknowledgement frame. Without this the case
// could be widened to every frame and the test above would still pass, while a
// Server that answered nothing but kept sending inventory would look alive.
func TestChannelLoopIgnoresOtherFramesForAcknowledgement(t *testing.T) {
	store, err := endpointstorage.Open(context.Background(), t.TempDir()+"/endpoint.sqlite")
	if err != nil {
		t.Fatalf("open endpoint storage: %v", err)
	}
	defer store.Close()

	transport := newAckRecordingChannel()
	service, err := NewService(ServiceDeps{Collector: &serviceCollector{}, Channel: transport, Storage: store, CollectionDelay: time.Hour})
	if err != nil {
		t.Fatalf("construct service: %v", err)
	}

	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	service.wg.Add(1)
	go service.channelLoop(ctx)

	transport.frames <- channel.Frame{Type: channel.FrameInventoryAck, SnapshotRevision: 1}

	// One second is far longer than the loop needs to consume one frame, so a
	// zero count here means the frame was handled without recording an
	// acknowledgement rather than that the loop had not run yet.
	time.Sleep(time.Second)
	if count := transport.acknowledgementCount(); count != 0 {
		t.Fatalf("acknowledgements=%d after an inventory acknowledgement, want 0", count)
	}

	cancel()
	service.wg.Wait()
}
