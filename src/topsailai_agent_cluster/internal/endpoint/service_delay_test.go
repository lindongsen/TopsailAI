package endpoint

import (
	"context"
	"sync"
	"testing"
	"time"

	"topsailai_agent_cluster/internal/protocol"
	endpointstorage "topsailai_agent_cluster/internal/storage/endpoint"
)

// slowCollector records when each collection starts and finishes, and can be
// told to occupy the collector for a fixed duration.
type slowCollector struct {
	mu       sync.Mutex
	starts   []time.Time
	finishes []time.Time
	duration time.Duration
}

func (c *slowCollector) Collect(context.Context, int64) (protocol.InventoryReport, error) {
	c.mu.Lock()
	c.starts = append(c.starts, time.Now())
	revision := int64(len(c.starts))
	c.mu.Unlock()
	time.Sleep(c.duration)
	c.mu.Lock()
	c.finishes = append(c.finishes, time.Now())
	c.mu.Unlock()
	return protocol.InventoryReport{SchemaVersion: "v1", SourceGeneration: "g1", SnapshotRevision: revision, ObservedAtMS: time.Now().UnixMilli(), ReportComplete: true, CollectionStatus: protocol.CollectionSucceeded}, nil
}

func (c *slowCollector) snapshot() ([]time.Time, []time.Time) {
	c.mu.Lock()
	defer c.mu.Unlock()
	return append([]time.Time(nil), c.starts...), append([]time.Time(nil), c.finishes...)
}

// TestCollectionDelayStartsAfterPreviousCycleFinishes proves the configured
// delay is measured from the end of the previous collection, not from its start.
// A fixed ticker drops ticks while a slow collection is still running, so the
// effective period silently becomes the collection duration and the configured
// delay stops meaning anything.
func TestCollectionDelayStartsAfterPreviousCycleFinishes(t *testing.T) {
	store, err := endpointstorage.Open(context.Background(), t.TempDir()+"/endpoint.sqlite")
	if err != nil {
		t.Fatal(err)
	}
	defer store.Close()
	const collectionDuration = 120 * time.Millisecond
	const delay = 60 * time.Millisecond
	collector := &slowCollector{duration: collectionDuration}
	service, err := NewService(ServiceDeps{Collector: collector, Channel: newServiceChannel(), Storage: store, CollectionDelay: delay})
	if err != nil {
		t.Fatal(err)
	}
	ctx, cancel := context.WithCancel(context.Background())
	done := make(chan error, 1)
	go func() { done <- service.Run(ctx) }()
	deadline := time.Now().Add(2 * time.Second)
	for {
		starts, _ := collector.snapshot()
		if len(starts) >= 3 {
			break
		}
		if time.Now().After(deadline) {
			cancel()
			<-done
			t.Fatalf("only %d collection cycles started", len(starts))
		}
		time.Sleep(5 * time.Millisecond)
	}
	cancel()
	select {
	case <-done:
	case <-time.After(time.Second):
		t.Fatal("service did not stop")
	}
	if err := service.Close(); err != nil {
		t.Fatal(err)
	}
	starts, finishes := collector.snapshot()
	if len(starts) < 3 || len(finishes) < 3 {
		t.Fatalf("starts=%d finishes=%d", len(starts), len(finishes))
	}
	// Every cycle after the first must begin at least one delay after the
	// previous cycle finished. Allow a small scheduling tolerance.
	for i := 1; i < len(starts); i++ {
		gap := starts[i].Sub(finishes[i-1])
		if gap < delay-20*time.Millisecond {
			t.Fatalf("cycle %d started %s after the previous finished, want at least %s", i, gap, delay)
		}
	}
	// A ticker would have produced a start roughly every collectionDuration,
	// i.e. before the previous cycle finished. Prove cycles never overlap.
	for i := 1; i < len(starts); i++ {
		if starts[i].Before(finishes[i-1]) {
			t.Fatalf("cycle %d started before cycle %d finished: overlapping collections", i, i-1)
		}
	}
}

// TestCollectionDelayDefaultsToFiveSeconds proves the documented default is
// applied when no delay is configured.
func TestCollectionDelayDefaultsToFiveSeconds(t *testing.T) {
	if defaultCollectionDelay != 5*time.Second {
		t.Fatalf("defaultCollectionDelay=%s, want 5s", defaultCollectionDelay)
	}
	store, err := endpointstorage.Open(context.Background(), t.TempDir()+"/endpoint.sqlite")
	if err != nil {
		t.Fatal(err)
	}
	defer store.Close()
	service, err := NewService(ServiceDeps{Collector: &slowCollector{}, Channel: newServiceChannel(), Storage: store})
	if err != nil {
		t.Fatal(err)
	}
	if service.collectionDelay != 5*time.Second {
		t.Fatalf("collectionDelay=%s, want 5s", service.collectionDelay)
	}
}
