package serverstorage

import (
	"context"
	"path/filepath"
	"testing"

	"topsailai_agent_cluster/internal/protocol"
)

// TestMarkEndpointOfflineRequiresMatchingInstanceAndNewerObservation verifies the
// disconnect write is fenced by both instance identity and observation time.
func TestMarkEndpointOfflineRequiresMatchingInstanceAndNewerObservation(t *testing.T) {
	ctx := context.Background()
	store, err := Open(ctx, filepath.Join(t.TempDir(), "server.db"))
	if err != nil {
		t.Fatal(err)
	}
	defer store.Close()
	endpoint := protocol.Endpoint{EndpointID: "e1", InstanceID: "i1", DisplayName: "test", ConnectionState: "online", ObservedAtMS: 100, CapabilityRevision: "c1"}
	if err := store.UpsertEndpoint(ctx, endpoint, 100); err != nil {
		t.Fatal(err)
	}

	applied, err := store.MarkEndpointOffline(ctx, "e1", "other-instance", 200)
	if err != nil {
		t.Fatal(err)
	}
	if applied {
		t.Fatal("disconnect from a non-matching instance must not be applied")
	}
	if state := endpointConnectionState(t, store, "e1"); state != "online" {
		t.Fatalf("connection_state=%q, want online", state)
	}

	applied, err = store.MarkEndpointOffline(ctx, "e1", "i1", 100)
	if err != nil {
		t.Fatal(err)
	}
	if !applied {
		t.Fatal("disconnect from the matching instance must be applied")
	}
	if state := endpointConnectionState(t, store, "e1"); state != "offline" {
		t.Fatalf("connection_state=%q, want offline", state)
	}

	// A reconnect publishes a newer observation; a late disconnect must not win.
	reconnected := endpoint
	reconnected.ObservedAtMS = 300
	if err := store.UpsertEndpoint(ctx, reconnected, 300); err != nil {
		t.Fatal(err)
	}
	applied, err = store.MarkEndpointOffline(ctx, "e1", "i1", 200)
	if err != nil {
		t.Fatal(err)
	}
	if applied {
		t.Fatal("a stale disconnect must not overwrite a newer observation")
	}
	if state := endpointConnectionState(t, store, "e1"); state != "online" {
		t.Fatalf("connection_state=%q, want online after reconnect", state)
	}
}

// TestMarkEndpointOfflineRejectsMissingIdentity verifies identity validation.
func TestMarkEndpointOfflineRejectsMissingIdentity(t *testing.T) {
	ctx := context.Background()
	store, err := Open(ctx, filepath.Join(t.TempDir(), "server.db"))
	if err != nil {
		t.Fatal(err)
	}
	defer store.Close()
	if _, err := store.MarkEndpointOffline(ctx, "", "i1", 1); err == nil {
		t.Fatal("missing endpoint id must be rejected")
	}
	if _, err := store.MarkEndpointOffline(ctx, "e1", "", 1); err == nil {
		t.Fatal("missing instance id must be rejected")
	}
}

// endpointConnectionState reads the persisted connection state for one endpoint.
func endpointConnectionState(t *testing.T, store *Store, endpointID string) string {
	t.Helper()
	var state string
	if err := store.DB().QueryRowContext(context.Background(), `SELECT connection_state FROM endpoints WHERE endpoint_id = ?`, endpointID).Scan(&state); err != nil {
		t.Fatal(err)
	}
	return state
}
