package endpointstorage

import (
	"regexp"
	"strings"
	"testing"

	"topsailai_agent_cluster/internal/protocol"
)

// mappingPrimaryKeyColumns reads the PRIMARY KEY declaration from the embedded
// migration that creates resource_mapping. The guard derives the identity from
// the schema text instead of restating a column list, so a migration that drops
// a column fails here rather than silently changing the identity.
func mappingPrimaryKeyColumns(t *testing.T) []string {
	t.Helper()
	document, err := migrationFS.ReadFile("internal/migrations/001_initial.sql")
	if err != nil {
		t.Fatalf("read the initial migration: %v", err)
	}
	pattern := regexp.MustCompile(`(?s)CREATE TABLE IF NOT EXISTS resource_mapping\s*\((.*?)\n\);`)
	match := pattern.FindStringSubmatch(string(document))
	if match == nil {
		t.Fatal("the initial migration no longer declares resource_mapping, so this guard checked nothing")
	}
	keyPattern := regexp.MustCompile(`PRIMARY KEY\s*\(([^)]*)\)`)
	key := keyPattern.FindStringSubmatch(match[1])
	if key == nil {
		t.Fatal("resource_mapping declares no PRIMARY KEY, so the mapping identity is undefined")
	}
	columns := []string{}
	for _, column := range strings.Split(key[1], ",") {
		columns = append(columns, strings.TrimSpace(column))
	}
	return columns
}

// TestResourceMappingIdentityIsTheAdapterKindKeyTriple pins the mapping identity
// to exactly the three columns the contract names. A primary key that loses a
// column collapses two distinct resources onto one Cluster ID.
func TestResourceMappingIdentityIsTheAdapterKindKeyTriple(t *testing.T) {
	columns := mappingPrimaryKeyColumns(t)
	want := []string{"adapter_id", "resource_kind", "provider_resource_key"}
	if len(columns) != len(want) {
		t.Fatalf("resource_mapping primary key=%v, want %v", columns, want)
	}
	for index, column := range want {
		if columns[index] != column {
			t.Fatalf("resource_mapping primary key=%v, want %v", columns, want)
		}
	}
}

// TestResourceMappingSeparatesAdapters proves the adapter dimension is real: two
// adapters that report the same provider key must receive different Cluster IDs,
// because the key is only unique inside one adapter.
func TestResourceMappingSeparatesAdapters(t *testing.T) {
	store, ctx := openTestStore(t)
	first, err := store.GetOrCreateResourceID(ctx, "adapter-a", protocol.ResourceSession, "shared-key", 100)
	if err != nil {
		t.Fatal(err)
	}
	second, err := store.GetOrCreateResourceID(ctx, "adapter-b", protocol.ResourceSession, "shared-key", 101)
	if err != nil {
		t.Fatal(err)
	}
	if first.ResourceID == second.ResourceID {
		t.Fatalf("two adapters shared resource ID %q for the same provider key", first.ResourceID)
	}
	if first.AdapterID != "adapter-a" || second.AdapterID != "adapter-b" {
		t.Fatalf("adapter IDs first=%q second=%q", first.AdapterID, second.AdapterID)
	}
	repeated, err := store.GetOrCreateResourceID(ctx, "adapter-a", protocol.ResourceSession, "shared-key", 102)
	if err != nil {
		t.Fatal(err)
	}
	if repeated != first {
		t.Fatalf("repeated mapping=%#v want=%#v", repeated, first)
	}
}

// TestResourceMappingIdentityCoversEveryDimension proves all three dimensions are
// independent: changing any one of them yields a new Cluster ID, and changing
// none of them returns the same one.
func TestResourceMappingIdentityCoversEveryDimension(t *testing.T) {
	store, ctx := openTestStore(t)
	base, err := store.GetOrCreateResourceID(ctx, "adapter-a", protocol.ResourceSession, "key", 100)
	if err != nil {
		t.Fatal(err)
	}
	variants := []struct {
		name       string
		adapterID  string
		kind       string
		providerID string
	}{
		{name: "other adapter", adapterID: "adapter-b", kind: protocol.ResourceSession, providerID: "key"},
		{name: "other kind", adapterID: "adapter-a", kind: protocol.ResourceTask, providerID: "key"},
		{name: "other key", adapterID: "adapter-a", kind: protocol.ResourceSession, providerID: "other-key"},
	}
	seen := map[string]string{base.ResourceID: "base"}
	for _, variant := range variants {
		t.Run(variant.name, func(t *testing.T) {
			mapping, err := store.GetOrCreateResourceID(ctx, variant.adapterID, variant.kind, variant.providerID, 200)
			if err != nil {
				t.Fatal(err)
			}
			if previous, exists := seen[mapping.ResourceID]; exists {
				t.Fatalf("changing the %s reused the Cluster ID of %s", variant.name, previous)
			}
			seen[mapping.ResourceID] = variant.name
		})
	}
}

// TestResourceMappingRejectsAnEmptyAdapterID proves the adapter dimension cannot
// be silently omitted by a caller: an empty adapter ID is rejected rather than
// stored as a shared empty-string bucket.
func TestResourceMappingRejectsAnEmptyAdapterID(t *testing.T) {
	store, ctx := openTestStore(t)
	if _, err := store.GetOrCreateResourceID(ctx, "", protocol.ResourceSession, "key", 100); err == nil {
		t.Fatal("an empty adapter ID was accepted, so every adapter would share one bucket")
	}
}

// TestResourceMappingConcurrentCreationConverges proves the insert path is safe
// under concurrency: the primary key rejects the loser and the retry returns the
// winner's row, so two callers never observe two Cluster IDs for one identity.
func TestResourceMappingConcurrentCreationConverges(t *testing.T) {
	store, ctx := openTestStore(t)
	const callers = 8
	results := make(chan ResourceMapping, callers)
	errorsSeen := make(chan error, callers)
	for index := 0; index < callers; index++ {
		go func() {
			mapping, err := store.GetOrCreateResourceID(ctx, "adapter-a", protocol.ResourceSession, "contended", 100)
			if err != nil {
				errorsSeen <- err
				return
			}
			results <- mapping
		}()
	}
	identities := map[string]bool{}
	for index := 0; index < callers; index++ {
		select {
		case err := <-errorsSeen:
			t.Fatalf("concurrent creation failed: %v", err)
		case mapping := <-results:
			identities[mapping.ResourceID] = true
		}
	}
	if len(identities) != 1 {
		t.Fatalf("concurrent creation produced %d Cluster IDs, want exactly 1", len(identities))
	}
}
