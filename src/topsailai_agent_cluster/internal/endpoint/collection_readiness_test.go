package endpoint

import (
	"bytes"
	"context"
	"log/slog"
	"strings"
	"sync"
	"testing"
	"time"

	"topsailai_agent_cluster/internal/channel"
)

// readinessChannel is a transport whose readiness can be flipped by the test, so
// the initial-publish gate can be observed without a real TLS handshake.
type readinessChannel struct {
	*serviceChannel
	mu    sync.Mutex
	ready bool
}

func newReadinessChannel() *readinessChannel {
	return &readinessChannel{serviceChannel: newServiceChannel()}
}

func (c *readinessChannel) Ready() bool {
	c.mu.Lock()
	defer c.mu.Unlock()
	return c.ready
}

func (c *readinessChannel) setReady(ready bool) {
	c.mu.Lock()
	c.ready = ready
	c.mu.Unlock()
}

// syncBuffer collects log output written by a concurrently running loop.
type syncBuffer struct {
	mu  sync.Mutex
	buf bytes.Buffer
}

func (b *syncBuffer) Write(p []byte) (int, error) {
	b.mu.Lock()
	defer b.mu.Unlock()
	return b.buf.Write(p)
}

func (b *syncBuffer) String() string {
	b.mu.Lock()
	defer b.mu.Unlock()
	return b.buf.String()
}

// TestCollectionLoopWaitsForChannelBeforeInitialPublish proves that a publish is
// not attempted while the transport is not ready, so startup does not log an
// ErrOffline ERROR that is indistinguishable from a real publish failure.
func TestCollectionLoopWaitsForChannelBeforeInitialPublish(t *testing.T) {
	store := openCoverageStore(t)
	defer store.Close()
	transport := newReadinessChannel()
	logs := &syncBuffer{}
	service, err := NewService(ServiceDeps{
		Collector:       &serviceCollector{},
		Channel:         transport,
		Storage:         store,
		Logger:          slog.New(slog.NewTextHandler(logs, nil)),
		CollectionDelay: time.Hour,
	})
	if err != nil {
		t.Fatal(err)
	}
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	service.wg.Add(1)
	go service.collectionLoop(ctx)

	// The transport stays unready long enough for the loop to reach the gate.
	time.Sleep(50 * time.Millisecond)
	if got := transport.count(channel.FrameInventory); got != 0 {
		t.Fatalf("inventory published before the channel was ready: %d", got)
	}
	if strings.Contains(logs.String(), "publish inventory") {
		t.Fatalf("startup logged a publish error before the channel was ready: %s", logs.String())
	}

	transport.setReady(true)
	deadline := time.After(2 * time.Second)
	for transport.count(channel.FrameInventory) < 1 {
		select {
		case <-deadline:
			t.Fatal("initial inventory was not published after the channel became ready")
		default:
			time.Sleep(time.Millisecond)
		}
	}
	if strings.Contains(logs.String(), "publish inventory") {
		t.Fatalf("publish error logged after readiness: %s", logs.String())
	}
}

// TestCollectionLoopStopsBeforeReadyOnCancellation proves that cancelling before
// readiness returns without publishing and without logging an ERROR.
func TestCollectionLoopStopsBeforeReadyOnCancellation(t *testing.T) {
	store := openCoverageStore(t)
	defer store.Close()
	transport := newReadinessChannel()
	logs := &syncBuffer{}
	service, err := NewService(ServiceDeps{
		Collector:       &serviceCollector{},
		Channel:         transport,
		Storage:         store,
		Logger:          slog.New(slog.NewTextHandler(logs, nil)),
		CollectionDelay: time.Hour,
	})
	if err != nil {
		t.Fatal(err)
	}
	ctx, cancel := context.WithCancel(context.Background())
	service.wg.Add(1)
	done := make(chan struct{})
	go func() {
		service.collectionLoop(ctx)
		close(done)
	}()
	time.Sleep(20 * time.Millisecond)
	cancel()
	select {
	case <-done:
	case <-time.After(2 * time.Second):
		t.Fatal("collection loop did not stop after cancellation")
	}
	if got := transport.count(channel.FrameInventory); got != 0 {
		t.Fatalf("inventory published after cancellation before readiness: %d", got)
	}
	if strings.Contains(logs.String(), "level=ERROR") {
		t.Fatalf("cancellation before readiness logged an error: %s", logs.String())
	}
}

// TestCollectionLoopWithoutReadinessSeamPublishesImmediately proves that a
// transport without the ReadyChannel seam keeps the previous behaviour.
func TestCollectionLoopWithoutReadinessSeamPublishesImmediately(t *testing.T) {
	store := openCoverageStore(t)
	defer store.Close()
	transport := newServiceChannel()
	service, err := NewService(ServiceDeps{
		Collector:       &serviceCollector{},
		Channel:         transport,
		Storage:         store,
		CollectionDelay: time.Hour,
	})
	if err != nil {
		t.Fatal(err)
	}
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	service.wg.Add(1)
	go service.collectionLoop(ctx)
	deadline := time.After(2 * time.Second)
	for transport.count(channel.FrameInventory) < 1 {
		select {
		case <-deadline:
			t.Fatal("initial inventory was not published without a readiness seam")
		default:
			time.Sleep(time.Millisecond)
		}
	}
}

// TestCollectionLoopKeepsPublishingTicksAfterReadiness proves that the gate only
// delays the initial publish and does not suppress later ticks.
func TestCollectionLoopKeepsPublishingTicksAfterReadiness(t *testing.T) {
	store := openCoverageStore(t)
	defer store.Close()
	transport := newReadinessChannel()
	transport.setReady(true)
	service, err := NewService(ServiceDeps{
		Collector:       &serviceCollector{},
		Channel:         transport,
		Storage:         store,
		CollectionDelay: 10 * time.Millisecond,
	})
	if err != nil {
		t.Fatal(err)
	}
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	service.wg.Add(1)
	go service.collectionLoop(ctx)
	deadline := time.After(2 * time.Second)
	for transport.count(channel.FrameInventory) < 2 {
		select {
		case <-deadline:
			t.Fatalf("later ticks were suppressed: frames=%d", transport.count(channel.FrameInventory))
		default:
			time.Sleep(time.Millisecond)
		}
	}
}
