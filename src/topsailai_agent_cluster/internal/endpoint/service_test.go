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

type serviceCollector struct {
	mu    sync.Mutex
	calls int
}

func (c *serviceCollector) Collect(context.Context, int64) (protocol.InventoryReport, error) {
	c.mu.Lock()
	defer c.mu.Unlock()
	c.calls++
	return protocol.InventoryReport{SchemaVersion: "v1", SourceGeneration: "g1", SnapshotRevision: int64(c.calls), ObservedAtMS: time.Now().UnixMilli(), ReportComplete: true, CollectionStatus: protocol.CollectionSucceeded}, nil
}

type serviceChannel struct {
	mu      sync.Mutex
	frames  []channel.Frame
	refresh chan channel.Frame
	closed  chan struct{}
	once    sync.Once
}

func newServiceChannel() *serviceChannel {
	return &serviceChannel{refresh: make(chan channel.Frame, 1), closed: make(chan struct{})}
}
func (c *serviceChannel) Read(ctx context.Context) (channel.Frame, error) {
	select {
	case frame := <-c.refresh:
		return frame, nil
	case <-c.closed:
		return channel.Frame{}, errors.New("closed")
	case <-ctx.Done():
		return channel.Frame{}, ctx.Err()
	}
}
func (c *serviceChannel) SendFrame(_ context.Context, frame channel.Frame) error {
	c.mu.Lock()
	c.frames = append(c.frames, frame)
	c.mu.Unlock()
	return nil
}
func (c *serviceChannel) Close() error {
	c.once.Do(func() { close(c.closed) })
	return nil
}
func (c *serviceChannel) count(kind string) int {
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

func TestServiceCollectsRefreshesAndStops(t *testing.T) {
	store, err := endpointstorage.Open(context.Background(), t.TempDir()+"/endpoint.sqlite")
	if err != nil {
		t.Fatal(err)
	}
	defer store.Close()
	collector := &serviceCollector{}
	transport := newServiceChannel()
	service, err := NewService(ServiceDeps{Collector: collector, Channel: transport, Storage: store, CollectionDelay: 10 * time.Millisecond})
	if err != nil {
		t.Fatal(err)
	}
	ctx, cancel := context.WithCancel(context.Background())
	done := make(chan error, 1)
	go func() { done <- service.Run(ctx) }()
	deadline := time.After(500 * time.Millisecond)
	for transport.count(channel.FrameInventory) < 1 {
		select {
		case <-deadline:
			t.Fatal("initial inventory was not published")
		default:
			time.Sleep(time.Millisecond)
		}
	}
	transport.refresh <- channel.Frame{Type: channel.FrameInventoryRefresh, RequestID: "refresh-1"}
	for transport.count(channel.FrameInventory) < 2 {
		select {
		case <-deadline:
			t.Fatal("refresh inventory was not published")
		default:
			time.Sleep(time.Millisecond)
		}
	}
	cancel()
	select {
	case err := <-done:
		if err != nil {
			t.Fatal(err)
		}
	case <-time.After(500 * time.Millisecond):
		t.Fatal("service did not stop")
	}
	if err := service.Close(); err != nil {
		t.Fatal(err)
	}
}
