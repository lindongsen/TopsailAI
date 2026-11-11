package serverstorage

import (
	"context"
	"database/sql"
	"errors"
	"path/filepath"
	"strings"
	"testing"

	"topsailai_agent_cluster/internal/protocol"
)

func TestReplaceInventoryAcceptsSessionWithIdentityAndAdapter(t *testing.T) {
	ctx := context.Background()
	store, err := Open(ctx, filepath.Join(t.TempDir(), "server.db"))
	if err != nil {
		t.Fatal(err)
	}
	defer store.Close()
	if err := store.UpsertEndpoint(ctx, protocol.Endpoint{EndpointID: "endpoint-1", InstanceID: "instance-1", DisplayName: "endpoint-1", ConnectionState: "online", ObservedAtMS: 1, CapabilityRevision: "unknown"}, 1); err != nil {
		t.Fatal(err)
	}

	report := protocol.InventoryReport{
		SchemaVersion:    "v1",
		SourceGeneration: "endpoint-local",
		SnapshotRevision: 1,
		ObservedAtMS:     1,
		ReportComplete:   true,
		CollectionStatus: protocol.CollectionSucceeded,
		Adapters:         []protocol.AdapterSummary{{AdapterID: "fixture-main", ProviderType: "fixture"}},
		Sessions:         []protocol.Session{{ClusterSessionID: "fixture-session", AdapterID: "fixture-main"}},
	}
	if err := store.ReplaceInventory(ctx, "endpoint-1", report, 2); err != nil {
		t.Fatalf("valid inventory rejected: %v", err)
	}
}

func TestReplaceInventoryRejectsSessionWithoutIdentity(t *testing.T) {
	store, err := Open(context.Background(), filepath.Join(t.TempDir(), "server.db"))
	if err != nil {
		t.Fatal(err)
	}
	defer store.Close()

	report := protocol.InventoryReport{
		SchemaVersion:    "v1",
		SourceGeneration: "endpoint-local",
		SnapshotRevision: 1,
		ObservedAtMS:     1,
		ReportComplete:   true,
		CollectionStatus: protocol.CollectionSucceeded,
		Adapters:         []protocol.AdapterSummary{{AdapterID: "fixture-main", ProviderType: "fixture"}},
		Sessions:         []protocol.Session{{AdapterID: "fixture-main"}},
	}
	if err := store.ReplaceInventory(context.Background(), "endpoint-1", report, 2); err == nil || !strings.Contains(err.Error(), "session identity and adapter are required") {
		t.Fatalf("missing session identity was not rejected specifically: %v", err)
	}
}

func TestCommandConstraintHelpers(t *testing.T) {
	if isConstraint(nil) || !isConstraint(sql.ErrNoRows) || !isConstraint(errors.New("UNIQUE constraint failed")) {
		t.Fatal("constraint errors were not classified")
	}
	if isConstraint(errors.New("temporary failure")) {
		t.Fatal("non-constraint error was misclassified")
	}
	for _, tc := range []struct {
		value, fragment string
		want            bool
	}{{"abc", "b", true}, {"abc", "", true}, {"abc", "z", false}, {"abc", "abcd", false}} {
		if got := contains(tc.value, tc.fragment); got != tc.want {
			t.Fatalf("contains(%q, %q)=%v want %v", tc.value, tc.fragment, got, tc.want)
		}
	}
}

func TestReplaceInventoryAcceptsRestartedEndpointWithLowerRevision(t *testing.T) {
	ctx := context.Background()
	store, err := Open(ctx, filepath.Join(t.TempDir(), "server.db"))
	if err != nil {
		t.Fatal(err)
	}
	defer store.Close()
	if err := store.UpsertEndpoint(ctx, protocol.Endpoint{EndpointID: "endpoint-1", InstanceID: "instance-1", DisplayName: "endpoint-1", ConnectionState: "online", ObservedAtMS: 1, CapabilityRevision: "unknown"}, 1); err != nil {
		t.Fatal(err)
	}
	oldReport := protocol.InventoryReport{
		SchemaVersion: "v1", SourceGeneration: "endpoint-local", SnapshotRevision: 70,
		ObservedAtMS: 100, ReportComplete: false, CollectionStatus: protocol.CollectionUnknown,
		Adapters: []protocol.AdapterSummary{{AdapterID: "fixture-main", ProviderType: "fixture"}},
	}
	newReport := protocol.InventoryReport{
		SchemaVersion: "v1", SourceGeneration: "endpoint-local", SnapshotRevision: 1,
		ObservedAtMS: 200, ReportComplete: true, CollectionStatus: protocol.CollectionSucceeded,
		Adapters: []protocol.AdapterSummary{{AdapterID: "fixture-main", ProviderType: "fixture"}},
		Sessions: []protocol.Session{{ClusterSessionID: "restarted-session", AdapterID: "fixture-main"}},
	}
	if err := store.ReplaceInventory(ctx, "endpoint-1", oldReport, 101); err != nil {
		t.Fatal(err)
	}
	if err := store.ReplaceInventory(ctx, "endpoint-1", newReport, 201); err != nil {
		t.Fatal(err)
	}
	got, err := store.GetInventory(ctx, "endpoint-1")
	if err != nil {
		t.Fatal(err)
	}
	if got.SnapshotRevision != 1 || got.ObservedAtMS != 200 || got.CollectionStatus != protocol.CollectionSucceeded || !got.ReportComplete || len(got.Sessions) != 1 || got.Sessions[0].ClusterSessionID != "restarted-session" {
		t.Fatalf("restarted report was not retained: %#v", got)
	}
}

func TestReplaceInventoryRejectsOlderObservedReport(t *testing.T) {
	ctx := context.Background()
	store, err := Open(ctx, filepath.Join(t.TempDir(), "server.db"))
	if err != nil {
		t.Fatal(err)
	}
	defer store.Close()
	if err := store.UpsertEndpoint(ctx, protocol.Endpoint{EndpointID: "endpoint-1", InstanceID: "instance-1", DisplayName: "endpoint-1", ConnectionState: "online", ObservedAtMS: 1, CapabilityRevision: "unknown"}, 1); err != nil {
		t.Fatal(err)
	}
	latest := protocol.InventoryReport{
		SchemaVersion: "v1", SourceGeneration: "endpoint-local", SnapshotRevision: 2,
		ObservedAtMS: 200, ReportComplete: true, CollectionStatus: protocol.CollectionSucceeded,
		Adapters: []protocol.AdapterSummary{{AdapterID: "fixture-main", ProviderType: "fixture"}},
		Sessions: []protocol.Session{{ClusterSessionID: "latest-session", AdapterID: "fixture-main"}},
	}
	stale := latest
	stale.SnapshotRevision = 99
	stale.ObservedAtMS = 199
	stale.Sessions = []protocol.Session{{ClusterSessionID: "stale-session", AdapterID: "fixture-main"}}
	if err := store.ReplaceInventory(ctx, "endpoint-1", latest, 201); err != nil {
		t.Fatal(err)
	}
	if err := store.ReplaceInventory(ctx, "endpoint-1", stale, 202); err != nil {
		t.Fatal(err)
	}
	got, err := store.GetInventory(ctx, "endpoint-1")
	if err != nil {
		t.Fatal(err)
	}
	if got.SnapshotRevision != 2 || got.ObservedAtMS != 200 || len(got.Sessions) != 1 || got.Sessions[0].ClusterSessionID != "latest-session" {
		t.Fatalf("stale report replaced latest report: %#v", got)
	}
}

func TestReplaceInventoryCommittedReturnsRepresentedRevision(t *testing.T) {
	ctx := context.Background()
	store, err := Open(ctx, filepath.Join(t.TempDir(), "server.db"))
	if err != nil {
		t.Fatal(err)
	}
	defer store.Close()
	if err := store.UpsertEndpoint(ctx, protocol.Endpoint{EndpointID: "endpoint-1", InstanceID: "instance-1", DisplayName: "endpoint-1", ConnectionState: "online", ObservedAtMS: 1, CapabilityRevision: "unknown"}, 1); err != nil {
		t.Fatal(err)
	}
	latest := protocol.InventoryReport{SchemaVersion: "v1", SourceGeneration: "endpoint-local", SnapshotRevision: 7, ObservedAtMS: 200, ReportComplete: true, CollectionStatus: protocol.CollectionSucceeded, Adapters: []protocol.AdapterSummary{{AdapterID: "fixture-main", ProviderType: "fixture"}}}
	committed, changed, represented, err := store.ReplaceInventoryCommitted(ctx, "endpoint-1", latest, 201)
	if err != nil {
		t.Fatal(err)
	}
	if committed != 7 || !changed || !represented {
		t.Fatalf("committed revision=%d changed=%t represented=%t, want 7, true, true", committed, changed, represented)
	}
	staleByTime := latest
	staleByTime.SnapshotRevision = 99
	staleByTime.ObservedAtMS = 199
	committed, changed, represented, err = store.ReplaceInventoryCommitted(ctx, "endpoint-1", staleByTime, 202)
	if err != nil {
		t.Fatal(err)
	}
	if committed != 7 || changed || represented {
		t.Fatalf("committed revision=%d changed=%t represented=%t after stale report, want 7, false, false", committed, changed, represented)
	}
	committed, changed, represented, err = store.ReplaceInventoryCommitted(ctx, "endpoint-1", latest, 203)
	if err != nil {
		t.Fatal(err)
	}
	if committed != 7 || changed || !represented {
		t.Fatalf("committed revision=%d changed=%t represented=%t after retry, want 7, false, true", committed, changed, represented)
	}
	different := latest
	different.Adapters[0].DisplayName = "different"
	committed, changed, represented, err = store.ReplaceInventoryCommitted(ctx, "endpoint-1", different, 204)
	if err != nil {
		t.Fatal(err)
	}
	if committed != 7 || changed || represented {
		t.Fatalf("committed revision=%d changed=%t represented=%t for conflicting retry, want 7, false, false", committed, changed, represented)
	}
	newer := latest
	newer.SnapshotRevision = 8
	newer.ObservedAtMS = 201
	committed, changed, represented, err = store.ReplaceInventoryCommitted(ctx, "endpoint-1", newer, 205)
	if err != nil {
		t.Fatal(err)
	}
	if committed != 8 || !changed || !represented {
		t.Fatalf("committed revision=%d changed=%t represented=%t for newer report, want 8, true, true", committed, changed, represented)
	}
	committed, changed, represented, err = store.ReplaceInventoryCommitted(ctx, "endpoint-1", latest, 206)
	if err != nil {
		t.Fatal(err)
	}
	if committed != 8 || changed || !represented {
		t.Fatalf("committed revision=%d changed=%t represented=%t for superseded retry, want 8, false, true", committed, changed, represented)
	}
}
