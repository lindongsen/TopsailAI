package endpoint

import (
	"context"
	"errors"
	"strings"
	"testing"
	"time"

	"topsailai_agent_cluster/internal/adapter"
	"topsailai_agent_cluster/internal/protocol"
	endpointstorage "topsailai_agent_cluster/internal/storage/endpoint"
)

// successfulSessionAdapter returns one session so a cycle that actually runs
// would create a resource mapping and persist a source snapshot.
func successfulSessionAdapter() fakeAdapter {
	return fakeAdapter{result: adapter.DiscoverResult{
		Complete:         true,
		CollectionStatus: protocol.CollectionSucceeded,
		Sessions:         []protocol.Session{{ClusterSessionID: "provider-session-1"}},
	}}
}

// TestCollectAbortsCancelledCycleWithoutTouchingStore verifies that a cancelled
// cycle is abandoned instead of being applied.
//
// Before the context was threaded into the resource-mapping store calls, apply
// used context.Background(), so a cancelled cycle still resolved mappings and
// persisted a snapshot and Collect returned a successful report. The assertion
// that matters is therefore the returned error: a cancelled cycle must not
// produce a report describing work the Endpoint had already abandoned.
func TestCollectAbortsCancelledCycleWithoutTouchingStore(t *testing.T) {
	store, err := endpointstorage.Open(context.Background(), t.TempDir()+"/endpoint.sqlite")
	if err != nil {
		t.Fatal(err)
	}
	defer store.Close()

	collector, err := NewCollector(context.Background(), []Binding{{AdapterID: "a", ProviderType: "fixture", Adapter: successfulSessionAdapter()}}, time.Second, store)
	if err != nil {
		t.Fatal(err)
	}

	ctx, cancel := context.WithCancel(context.Background())
	cancel()

	report, err := collector.Collect(ctx, 100)
	if !errors.Is(err, context.Canceled) {
		t.Fatalf("Collect error=%v, want context.Canceled", err)
	}
	if report.SnapshotRevision != 0 || len(report.Sessions) != 0 {
		t.Fatalf("cancelled cycle returned a report: %#v", report)
	}
	if len(collector.sources) != 0 {
		t.Fatalf("cancelled cycle mutated the source cache: %#v", collector.sources)
	}
	snapshots, err := store.ListSourceSnapshots(context.Background())
	if err != nil {
		t.Fatal(err)
	}
	if len(snapshots) != 0 {
		t.Fatalf("cancelled cycle persisted %d source snapshots", len(snapshots))
	}
}

// TestCollectResolvesMappingsOnHealthyCycle verifies that threading the context
// did not change the healthy path: mappings are still created and the provider
// session ID is still replaced by the opaque cluster resource ID.
func TestCollectResolvesMappingsOnHealthyCycle(t *testing.T) {
	store, err := endpointstorage.Open(context.Background(), t.TempDir()+"/endpoint.sqlite")
	if err != nil {
		t.Fatal(err)
	}
	defer store.Close()

	collector, err := NewCollector(context.Background(), []Binding{{AdapterID: "a", ProviderType: "fixture", Adapter: successfulSessionAdapter()}}, time.Second, store)
	if err != nil {
		t.Fatal(err)
	}

	report, err := collector.Collect(context.Background(), 100)
	if err != nil {
		t.Fatal(err)
	}
	if len(report.Sessions) != 1 {
		t.Fatalf("sessions=%#v, want one session", report.Sessions)
	}
	if !strings.HasPrefix(report.Sessions[0].ClusterSessionID, "res_") {
		t.Fatalf("session ID=%q, want an opaque resource ID", report.Sessions[0].ClusterSessionID)
	}
	if report.Sessions[0].AdapterID != "a" {
		t.Fatalf("adapter ID=%q, want a", report.Sessions[0].AdapterID)
	}
	snapshots, err := store.ListSourceSnapshots(context.Background())
	if err != nil {
		t.Fatal(err)
	}
	if len(snapshots) != 1 {
		t.Fatalf("persisted %d source snapshots, want 1", len(snapshots))
	}
}

// TestCollectReportsStoreFailureThatIsNotCancellation verifies that a genuine
// store failure is still reported as a collection failure. Only a cancellation
// aborts the cycle; a broken store is a real defect the operator must see.
func TestCollectReportsStoreFailureThatIsNotCancellation(t *testing.T) {
	store, err := endpointstorage.Open(context.Background(), t.TempDir()+"/endpoint.sqlite")
	if err != nil {
		t.Fatal(err)
	}

	collector, err := NewCollector(context.Background(), []Binding{{AdapterID: "a", ProviderType: "fixture", Adapter: successfulSessionAdapter()}}, time.Second, store)
	if err != nil {
		t.Fatal(err)
	}
	// Closing the store makes every mapping call fail without cancelling the
	// context, which is exactly the non-cancellation failure this test needs.
	if err := store.Close(); err != nil {
		t.Fatal(err)
	}

	report, err := collector.Collect(context.Background(), 100)
	if err != nil {
		t.Fatalf("Collect error=%v, want a degraded report instead", err)
	}
	if report.CollectionStatus == protocol.CollectionSucceeded {
		t.Fatalf("collection status=%q, want a failed status", report.CollectionStatus)
	}
	if len(report.Sessions) != 0 {
		t.Fatalf("failed mapping still published sessions: %#v", report.Sessions)
	}
}

func TestNewCollectorRestoresOnlyConfiguredAdapters(t *testing.T) {
	store, err := endpointstorage.Open(context.Background(), t.TempDir()+"/endpoint.sqlite")
	if err != nil {
		t.Fatal(err)
	}
	defer store.Close()
	for _, adapterID := range []string{"old", "current"} {
		snapshot := endpointstorage.SourceSnapshot{AdapterID: adapterID, ProviderType: "fixture", DisplayName: adapterID, Health: "healthy", CollectionStatus: protocol.CollectionSucceeded, LastAttemptAtMS: 100, LastSuccessAtMS: ptrInt64(100), DataKnown: true, ReportComplete: true, Sessions: []protocol.Session{{ClusterSessionID: adapterID + "-session", AdapterID: adapterID}}}
		if err := store.ApplySourceSnapshot(context.Background(), snapshot, 100); err != nil {
			t.Fatal(err)
		}
	}
	collector, err := NewCollector(context.Background(), []Binding{{AdapterID: "current", ProviderType: "fixture", Adapter: fakeAdapter{err: errors.New("offline")}}}, time.Second, store)
	if err != nil {
		t.Fatal(err)
	}
	if _, ok := collector.sources["old"]; ok {
		t.Fatalf("unconfigured adapter was restored: %#v", collector.sources)
	}
	if _, ok := collector.sources["current"]; !ok {
		t.Fatalf("configured adapter was not restored: %#v", collector.sources)
	}
}

func TestCollectExpiresCacheBeforeFailedDiscovery(t *testing.T) {
	store, err := endpointstorage.Open(context.Background(), t.TempDir()+"/endpoint.sqlite")
	if err != nil {
		t.Fatal(err)
	}
	defer store.Close()
	lastSuccess := int64(100)
	snapshot := endpointstorage.SourceSnapshot{AdapterID: "current", ProviderType: "fixture", DisplayName: "current", Health: "healthy", CollectionStatus: protocol.CollectionSucceeded, LastAttemptAtMS: 100, LastSuccessAtMS: &lastSuccess, DataKnown: true, ReportComplete: true, Sessions: []protocol.Session{{ClusterSessionID: "expired-session", AdapterID: "current"}}}
	if err := store.ApplySourceSnapshot(context.Background(), snapshot, 100); err != nil {
		t.Fatal(err)
	}
	var deleted []string
	collector, err := NewCollectorWithOptions(context.Background(), []Binding{{AdapterID: "current", ProviderType: "fixture", Adapter: fakeAdapter{err: errors.New("offline")}}}, time.Second, store, CollectorOptions{SourceCacheExpiry: 500 * time.Millisecond, LogCacheDeletion: func(adapterID string) { deleted = append(deleted, adapterID) }})
	if err != nil {
		t.Fatal(err)
	}
	report, err := collector.Collect(context.Background(), 1000)
	if err != nil {
		t.Fatal(err)
	}
	if len(report.Sessions) != 0 {
		t.Fatalf("expired sessions were retained after failed discovery: %#v", report.Sessions)
	}
	if len(deleted) != 1 || deleted[0] != "current" {
		t.Fatalf("deletion log=%v, want [current]", deleted)
	}
	snapshots, err := store.ListSourceSnapshots(context.Background())
	if err != nil {
		t.Fatal(err)
	}
	if len(snapshots) != 1 || snapshots[0].DataKnown {
		t.Fatalf("failed current observation was not persisted as unknown: %#v", snapshots)
	}
}

func ptrInt64(value int64) *int64 { return &value }
