package server

import (
	"context"
	"testing"

	serverstorage "topsailai_agent_cluster/internal/storage/server"
)

func TestEventBrokerManifestPreservesRevisionEntries(t *testing.T) {
	broker := NewEventBroker(1)
	entries := []ManifestEntry{{EndpointID: "e1", SnapshotRevision: 7}}
	manifest := broker.Manifest((*serverstorage.Store)(nil), entries)
	if manifest.ServerInstanceID == "" || len(manifest.Entries) != 1 || manifest.Entries[0] != entries[0] {
		t.Fatalf("manifest=%#v", manifest)
	}
	_ = context.Background()
}
