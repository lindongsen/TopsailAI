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

	"topsailai_agent_cluster/internal/protocol"
)

// cancelAwareCollector succeeds while the context is alive and reports the
// context error once it is cancelled, which is what the real collector does when
// a cycle is abandoned.
type cancelAwareCollector struct{}

func (cancelAwareCollector) Collect(ctx context.Context, _ int64) (protocol.InventoryReport, error) {
	if err := ctx.Err(); err != nil {
		return protocol.InventoryReport{}, err
	}
	return protocol.InventoryReport{SchemaVersion: "v1", SourceGeneration: "g1", SnapshotRevision: 1, ObservedAtMS: time.Now().UnixMilli(), ReportComplete: true, CollectionStatus: protocol.CollectionSucceeded}, nil
}

// failingCollector reports a genuine collection failure that is not a
// cancellation, so the ERROR path stays covered.
type failingCollector struct{}

func (failingCollector) Collect(context.Context, int64) (protocol.InventoryReport, error) {
	return protocol.InventoryReport{}, errors.New("provider discovery failed")
}

// newAbortLogService builds a Service whose logger writes into the returned
// buffer, so tests can assert the severity of an aborted collection.
func newAbortLogService(t *testing.T, collector ReportCollector) (*Service, *bytes.Buffer) {
	t.Helper()
	store := openCoverageStore(t)
	t.Cleanup(func() { _ = store.Close() })
	service, err := NewService(ServiceDeps{Collector: collector, Channel: newServiceChannel(), Storage: store})
	if err != nil {
		t.Fatal(err)
	}
	var logs bytes.Buffer
	service.logger = slog.New(slog.NewTextHandler(&logs, nil))
	return service, &logs
}

// TestPublishRefreshLogsAbortedCollectionAsInfo verifies that a cancelled forced
// collection is reported as an aborted cycle instead of an ERROR.
//
// The Server correlates the refresh reply by request ID and fails the request on
// its own deadline, so an ERROR here would only make a healthy shutdown look
// broken while telling the operator nothing actionable.
func TestPublishRefreshLogsAbortedCollectionAsInfo(t *testing.T) {
	service, logs := newAbortLogService(t, cancelAwareCollector{})

	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	service.publishRefresh(ctx, "refresh-1")

	output := logs.String()
	if strings.Contains(output, "level=ERROR") {
		t.Fatalf("aborted refresh log=%q, want no ERROR level", output)
	}
	if !strings.Contains(output, "refresh inventory aborted") {
		t.Fatalf("aborted refresh log=%q, want the aborted message", output)
	}
}

// TestPublishRefreshKeepsErrorForGenuineFailure verifies that a real collection
// failure is still reported at ERROR. Only cancellation is downgraded.
func TestPublishRefreshKeepsErrorForGenuineFailure(t *testing.T) {
	service, logs := newAbortLogService(t, failingCollector{})

	service.publishRefresh(context.Background(), "refresh-1")

	output := logs.String()
	if !strings.Contains(output, "level=ERROR") {
		t.Fatalf("genuine failure log=%q, want ERROR level", output)
	}
	if strings.Contains(output, "aborted") {
		t.Fatalf("genuine failure log=%q, want no aborted wording", output)
	}
}

// blockingCollector blocks inside Collect until the context is cancelled and
// then reports the context error. Cancelling between cycles never reaches the
// aborted branch, because the loop checks ctx.Done() before publishing; the
// branch is only reachable when cancellation happens during a collection.
type blockingCollector struct {
	entered chan struct{}
	once    sync.Once
}

func (b *blockingCollector) Collect(ctx context.Context, _ int64) (protocol.InventoryReport, error) {
	b.once.Do(func() { close(b.entered) })
	<-ctx.Done()
	return protocol.InventoryReport{}, ctx.Err()
}

// TestCollectionLoopAbortsCancelledCycleWithoutError drives the periodic publish
// path with a ready channel and a collection that is cancelled while it runs, so
// the aborted branch is exercised rather than the readiness gate or the
// between-cycles check.
func TestCollectionLoopAbortsCancelledCycleWithoutError(t *testing.T) {
	store := openCoverageStore(t)
	t.Cleanup(func() { _ = store.Close() })
	transport := &readyCoverageChannel{serviceChannel: newServiceChannel(), ready: true}
	collector := &blockingCollector{entered: make(chan struct{})}
	service, err := NewService(ServiceDeps{Collector: collector, Channel: transport, Storage: store, CollectionDelay: time.Millisecond})
	if err != nil {
		t.Fatal(err)
	}
	var logs bytes.Buffer
	service.logger = slog.New(slog.NewTextHandler(&logs, nil))

	ctx, cancel := context.WithCancel(context.Background())
	service.wg.Add(1)
	done := make(chan struct{})
	go func() {
		service.collectionLoop(ctx)
		close(done)
	}()
	select {
	case <-collector.entered:
	case <-time.After(2 * time.Second):
		t.Fatal("collection did not start")
	}
	cancel()
	select {
	case <-done:
	case <-time.After(2 * time.Second):
		t.Fatal("collection loop did not stop")
	}

	output := logs.String()
	if strings.Contains(output, "level=ERROR") {
		t.Fatalf("aborted collection log=%q, want no ERROR level", output)
	}
	if !strings.Contains(output, "inventory collection aborted") {
		t.Fatalf("aborted collection log=%q, want the aborted message", output)
	}
}

// TestCollectionLoopKeepsErrorForGenuineFailure verifies the periodic path still
// reports a real collection failure at ERROR, so the abort rule did not silence
// genuine defects.
func TestCollectionLoopKeepsErrorForGenuineFailure(t *testing.T) {
	store := openCoverageStore(t)
	t.Cleanup(func() { _ = store.Close() })
	transport := &readyCoverageChannel{serviceChannel: newServiceChannel(), ready: true}
	service, err := NewService(ServiceDeps{Collector: failingCollector{}, Channel: transport, Storage: store, CollectionDelay: time.Hour})
	if err != nil {
		t.Fatal(err)
	}
	var logs bytes.Buffer
	service.logger = slog.New(slog.NewTextHandler(&logs, nil))

	ctx, cancel := context.WithCancel(context.Background())
	service.wg.Add(1)
	done := make(chan struct{})
	go func() {
		service.collectionLoop(ctx)
		close(done)
	}()
	deadline := time.After(2 * time.Second)
	for !strings.Contains(logs.String(), "collect inventory") {
		select {
		case <-deadline:
			t.Fatal("genuine failure was not logged")
		default:
			time.Sleep(time.Millisecond)
		}
	}
	cancel()
	select {
	case <-done:
	case <-time.After(2 * time.Second):
		t.Fatal("collection loop did not stop")
	}

	output := logs.String()
	if !strings.Contains(output, "level=ERROR") {
		t.Fatalf("genuine failure log=%q, want ERROR level", output)
	}
	if strings.Contains(output, "aborted") {
		t.Fatalf("genuine failure log=%q, want no aborted wording", output)
	}
}
