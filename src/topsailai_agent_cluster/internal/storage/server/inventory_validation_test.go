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
