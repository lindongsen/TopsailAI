package serverstorage

import (
	"context"
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
		Sessions:         []protocol.Session{{SessionID: "fixture-session", AdapterID: "fixture-main"}},
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
