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

type descriptorServiceCollector struct {
	serviceCollector
	mu            sync.Mutex
	refreshCalls  int
	refreshReport protocol.InventoryReport
	refreshErr    error
}

func (c *descriptorServiceCollector) RefreshDescriptors(context.Context, string, int64) (protocol.InventoryReport, error) {
	c.mu.Lock()
	defer c.mu.Unlock()
	c.refreshCalls++
	return c.refreshReport, c.refreshErr
}

func TestServicePublishesDescriptorRefreshAndKeepsNewerPendingInventory(t *testing.T) {
	store, err := endpointstorage.Open(context.Background(), t.TempDir()+"/endpoint.sqlite")
	if err != nil {
		t.Fatal(err)
	}
	defer store.Close()
	collector := &descriptorServiceCollector{refreshReport: protocol.InventoryReport{SchemaVersion: "v1", SourceGeneration: "g1", SnapshotRevision: 2, ObservedAtMS: 2, ReportComplete: true, CollectionStatus: protocol.CollectionSucceeded}}
	transport := newServiceChannel()
	service, err := NewService(ServiceDeps{Collector: collector, Channel: transport, Storage: store, CollectionDelay: time.Hour})
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
	if err := service.RefreshDescriptors(ctx, "fixture"); err != nil {
		t.Fatal(err)
	}
	for transport.count(channel.FrameInventory) < 2 {
		select {
		case <-deadline:
			t.Fatal("descriptor inventory was not published")
		default:
			time.Sleep(time.Millisecond)
		}
	}
	transport.refresh <- channel.Frame{Type: channel.FrameInventoryAck, SnapshotRevision: 1}
	time.Sleep(10 * time.Millisecond)
	service.inventoryMu.Lock()
	pending := service.pendingInventory
	service.inventoryMu.Unlock()
	if pending == nil || pending.SnapshotRevision != 2 {
		t.Fatalf("old acknowledgement cleared newer inventory: %#v", pending)
	}
	transport.refresh <- channel.Frame{Type: channel.FrameInventoryAck, SnapshotRevision: 2}
	for {
		service.inventoryMu.Lock()
		pending = service.pendingInventory
		service.inventoryMu.Unlock()
		if pending == nil {
			break
		}
		select {
		case <-deadline:
			t.Fatalf("matching acknowledgement did not clear inventory: %#v", pending)
		default:
			time.Sleep(time.Millisecond)
		}
	}
	collector.mu.Lock()
	refreshCalls := collector.refreshCalls
	collector.mu.Unlock()
	if refreshCalls != 1 {
		t.Fatalf("refresh calls=%d, want 1", refreshCalls)
	}
	cancel()
	if err := <-done; err != nil {
		t.Fatal(err)
	}
}

func TestRefreshDescriptorsFailureKeepsPendingInventoryAndDoesNotTriggerPublish(t *testing.T) {
	store, err := endpointstorage.Open(context.Background(), t.TempDir()+"/endpoint.sqlite")
	if err != nil {
		t.Fatal(err)
	}
	defer store.Close()
	collector := &descriptorServiceCollector{refreshErr: errors.New("reload failed")}
	service, err := NewService(ServiceDeps{Collector: collector, Channel: newServiceChannel(), Storage: store, CollectionDelay: time.Hour})
	if err != nil {
		t.Fatal(err)
	}
	original := protocol.InventoryReport{SnapshotRevision: 4}
	service.rememberInventory(original)
	if err := service.RefreshDescriptors(context.Background(), "fixture"); err == nil {
		t.Fatal("descriptor refresh failure was not returned")
	}
	service.inventoryMu.Lock()
	pending := service.pendingInventory
	service.inventoryMu.Unlock()
	if pending == nil || pending.SnapshotRevision != 4 {
		t.Fatalf("failed refresh changed pending inventory: %#v", pending)
	}
	if len(service.inventoryTrigger) != 0 {
		t.Fatalf("failed refresh queued %d publication triggers", len(service.inventoryTrigger))
	}
}

func TestRefreshDescriptorsCoalescesTriggersAndKeepsLatestRevision(t *testing.T) {
	store, err := endpointstorage.Open(context.Background(), t.TempDir()+"/endpoint.sqlite")
	if err != nil {
		t.Fatal(err)
	}
	defer store.Close()
	collector := &descriptorServiceCollector{refreshReport: protocol.InventoryReport{SnapshotRevision: 2}}
	service, err := NewService(ServiceDeps{Collector: collector, Channel: newServiceChannel(), Storage: store, CollectionDelay: time.Hour})
	if err != nil {
		t.Fatal(err)
	}
	if err := service.RefreshDescriptors(context.Background(), "fixture"); err != nil {
		t.Fatal(err)
	}
	collector.mu.Lock()
	collector.refreshReport.SnapshotRevision = 3
	collector.mu.Unlock()
	if err := service.RefreshDescriptors(context.Background(), "fixture"); err != nil {
		t.Fatal(err)
	}
	service.inventoryMu.Lock()
	pending := service.pendingInventory
	service.inventoryMu.Unlock()
	if pending == nil || pending.SnapshotRevision != 3 {
		t.Fatalf("pending inventory=%#v, want revision 3", pending)
	}
	if len(service.inventoryTrigger) != 1 {
		t.Fatalf("publication triggers=%d, want 1", len(service.inventoryTrigger))
	}
}

type reconnectInventoryChannel struct {
	mu         sync.Mutex
	readFailed bool
	frames     []channel.Frame
}

func (c *reconnectInventoryChannel) Read(ctx context.Context) (channel.Frame, error) {
	c.mu.Lock()
	if !c.readFailed {
		c.readFailed = true
		c.mu.Unlock()
		return channel.Frame{}, channel.ErrOffline
	}
	c.mu.Unlock()
	<-ctx.Done()
	return channel.Frame{}, ctx.Err()
}

func (c *reconnectInventoryChannel) SendFrame(_ context.Context, frame channel.Frame) error {
	c.mu.Lock()
	c.frames = append(c.frames, frame)
	c.mu.Unlock()
	return nil
}

func (c *reconnectInventoryChannel) Reconnect(context.Context) error { return nil }
func (c *reconnectInventoryChannel) Close() error                    { return nil }
func (c *reconnectInventoryChannel) count(kind string) int {
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

func TestChannelLoopResendsPendingInventoryAfterReconnect(t *testing.T) {
	store, err := endpointstorage.Open(context.Background(), t.TempDir()+"/endpoint.sqlite")
	if err != nil {
		t.Fatal(err)
	}
	defer store.Close()
	transport := &reconnectInventoryChannel{}
	service := &Service{channel: transport, storage: store, inventoryTrigger: make(chan struct{}, 1)}
	service.rememberInventory(protocol.InventoryReport{SnapshotRevision: 9})
	ctx, cancel := context.WithCancel(context.Background())
	service.wg.Add(1)
	go service.channelLoop(ctx)
	deadline := time.After(2 * time.Second)
	for transport.count(channel.FrameInventory) == 0 {
		select {
		case <-deadline:
			cancel()
			service.wg.Wait()
			t.Fatal("pending inventory was not resent after reconnect")
		default:
			time.Sleep(time.Millisecond)
		}
	}
	cancel()
	service.wg.Wait()
}
