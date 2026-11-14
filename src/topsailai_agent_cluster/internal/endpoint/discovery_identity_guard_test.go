package endpoint

import (
	"context"
	"testing"
	"time"

	"topsailai_agent_cluster/internal/adapter"
	"topsailai_agent_cluster/internal/protocol"
	endpointstorage "topsailai_agent_cluster/internal/storage/endpoint"
)

// discoveryKeyAdapter reports one session whose provider-private key is read
// from key on every cycle, so a test can change the key between rounds.
type discoveryKeyAdapter struct {
	key *string
}

// Describe returns an empty descriptor because discovery identity does not
// depend on the advertised capabilities.
func (d discoveryKeyAdapter) Describe(context.Context) (adapter.Descriptor, error) {
	return adapter.Descriptor{}, nil
}

// Discover reports one complete session carrying the current provider key.
func (d discoveryKeyAdapter) Discover(context.Context, adapter.DiscoverRequest) (adapter.DiscoverResult, error) {
	return adapter.DiscoverResult{
		Complete:         true,
		CollectionStatus: protocol.CollectionSucceeded,
		Sessions:         []protocol.Session{{ClusterSessionID: *d.key}},
	}, nil
}

// Inspect is unsupported because this adapter only exercises discovery.
func (d discoveryKeyAdapter) Inspect(context.Context, adapter.InspectRequest) (adapter.InspectResult, error) {
	return adapter.InspectResult{}, nil
}

// Execute is unsupported because this adapter only exercises discovery.
func (d discoveryKeyAdapter) Execute(context.Context, adapter.ExecuteRequest) (adapter.ExecuteResult, error) {
	return adapter.ExecuteResult{}, adapter.ErrUnsupported
}

// ReadOutput is unsupported because this adapter only exercises discovery.
func (d discoveryKeyAdapter) ReadOutput(context.Context, adapter.OutputRequest) (adapter.OutputResult, error) {
	return adapter.OutputResult{}, adapter.ErrUnsupported
}

// QueryCommand is unsupported because this adapter only exercises discovery.
func (d discoveryKeyAdapter) QueryCommand(context.Context, adapter.CommandQuery) (adapter.CommandResult, error) {
	return adapter.CommandResult{}, adapter.ErrUnsupported
}

// Watch is unsupported because this adapter only exercises discovery.
func (d discoveryKeyAdapter) Watch(context.Context) (<-chan adapter.Event, error) {
	return nil, adapter.ErrUnsupported
}

// Close releases nothing because the adapter holds no resources.
func (d discoveryKeyAdapter) Close() error { return nil }

// openIdentityStore opens a store in a temporary directory for one test.
func openIdentityStore(t *testing.T) (*endpointstorage.Store, string) {
	t.Helper()
	path := t.TempDir() + "/endpoint.sqlite"
	store, err := endpointstorage.Open(context.Background(), path)
	if err != nil {
		t.Fatal(err)
	}
	return store, path
}

// TestRepeatedDiscoveryKeepsTheClusterSessionID verifies that a second
// discovery cycle over the same provider session key republishes the same
// Cluster session ID.
//
// The existing restart test works at the store layer with a fixed key and never
// runs a discovery cycle, so it cannot see a collector that mints a new identity
// on every cycle. This test drives the collector twice through the same store.
func TestRepeatedDiscoveryKeepsTheClusterSessionID(t *testing.T) {
	ctx := context.Background()
	store, _ := openIdentityStore(t)
	defer store.Close()

	key := "provider-session-1"
	collector, err := NewCollector(ctx, []Binding{{AdapterID: "a", ProviderType: "fixture", Adapter: discoveryKeyAdapter{key: &key}}}, time.Second, store)
	if err != nil {
		t.Fatal(err)
	}

	first, err := collector.Collect(ctx, 100)
	if err != nil {
		t.Fatal(err)
	}
	second, err := collector.Collect(ctx, 200)
	if err != nil {
		t.Fatal(err)
	}
	if len(first.Sessions) != 1 || len(second.Sessions) != 1 {
		t.Fatalf("sessions=%d then %d, want one each", len(first.Sessions), len(second.Sessions))
	}
	if first.Sessions[0].ClusterSessionID != second.Sessions[0].ClusterSessionID {
		t.Fatalf("repeated discovery changed the Cluster session ID: %q then %q", first.Sessions[0].ClusterSessionID, second.Sessions[0].ClusterSessionID)
	}
}

// TestRepeatedDiscoveryAcrossStoreReopenKeepsTheClusterSessionID verifies that
// the identity survives a store restart in the middle of a discovery sequence,
// which is the shape a Provider restart takes from the Endpoint's point of view.
func TestRepeatedDiscoveryAcrossStoreReopenKeepsTheClusterSessionID(t *testing.T) {
	ctx := context.Background()
	store, path := openIdentityStore(t)

	key := "provider-session-1"
	collector, err := NewCollector(ctx, []Binding{{AdapterID: "a", ProviderType: "fixture", Adapter: discoveryKeyAdapter{key: &key}}}, time.Second, store)
	if err != nil {
		t.Fatal(err)
	}
	first, err := collector.Collect(ctx, 100)
	if err != nil {
		t.Fatal(err)
	}
	if err := store.Close(); err != nil {
		t.Fatal(err)
	}

	reopened, err := endpointstorage.Open(ctx, path)
	if err != nil {
		t.Fatal(err)
	}
	defer reopened.Close()
	secondCollector, err := NewCollector(ctx, []Binding{{AdapterID: "a", ProviderType: "fixture", Adapter: discoveryKeyAdapter{key: &key}}}, time.Second, reopened)
	if err != nil {
		t.Fatal(err)
	}
	second, err := secondCollector.Collect(ctx, 200)
	if err != nil {
		t.Fatal(err)
	}
	if len(first.Sessions) != 1 || len(second.Sessions) != 1 {
		t.Fatalf("sessions=%d then %d, want one each", len(first.Sessions), len(second.Sessions))
	}
	if first.Sessions[0].ClusterSessionID != second.Sessions[0].ClusterSessionID {
		t.Fatalf("reopening the store changed the Cluster session ID: %q then %q", first.Sessions[0].ClusterSessionID, second.Sessions[0].ClusterSessionID)
	}
}

// TestProviderKeyChangeYieldsANewClusterSessionID pins the boundary of the
// guarantee: the Cluster recognises a resource by its provider key alone, so a
// changed key is a different resource and must receive a different ID.
//
// This is deliberately the opposite assertion to the idempotency tests. Without
// it, an implementation that ignored the key entirely would satisfy every
// "the ID did not change" test while collapsing unrelated sessions together.
func TestProviderKeyChangeYieldsANewClusterSessionID(t *testing.T) {
	ctx := context.Background()
	store, _ := openIdentityStore(t)
	defer store.Close()

	key := "provider-session-1"
	collector, err := NewCollector(ctx, []Binding{{AdapterID: "a", ProviderType: "fixture", Adapter: discoveryKeyAdapter{key: &key}}}, time.Second, store)
	if err != nil {
		t.Fatal(err)
	}
	first, err := collector.Collect(ctx, 100)
	if err != nil {
		t.Fatal(err)
	}

	key = "provider-session-2"
	second, err := collector.Collect(ctx, 200)
	if err != nil {
		t.Fatal(err)
	}
	if len(first.Sessions) != 1 || len(second.Sessions) != 1 {
		t.Fatalf("sessions=%d then %d, want one each", len(first.Sessions), len(second.Sessions))
	}
	if first.Sessions[0].ClusterSessionID == second.Sessions[0].ClusterSessionID {
		t.Fatalf("a changed provider key reused Cluster session ID %q", first.Sessions[0].ClusterSessionID)
	}
}

// TestClusterDoesNotRewriteTheProviderKey verifies that the stored provider key
// is the value the provider reported, byte for byte.
//
// The Cluster mints randomness only for the public resource ID. If it also
// rewrote the private key, every discovery cycle would look like a new resource
// and no restart could ever preserve an identity.
func TestClusterDoesNotRewriteTheProviderKey(t *testing.T) {
	ctx := context.Background()
	store, _ := openIdentityStore(t)
	defer store.Close()

	key := "provider-session-1"
	collector, err := NewCollector(ctx, []Binding{{AdapterID: "a", ProviderType: "fixture", Adapter: discoveryKeyAdapter{key: &key}}}, time.Second, store)
	if err != nil {
		t.Fatal(err)
	}
	report, err := collector.Collect(ctx, 100)
	if err != nil {
		t.Fatal(err)
	}
	if len(report.Sessions) != 1 {
		t.Fatalf("sessions=%#v, want one session", report.Sessions)
	}
	mapping, err := store.LookupResourceID(ctx, report.Sessions[0].ClusterSessionID)
	if err != nil {
		t.Fatal(err)
	}
	if mapping.ProviderResourceKey != key {
		t.Fatalf("stored provider key=%q, want the reported key %q", mapping.ProviderResourceKey, key)
	}
	if mapping.AdapterID != "a" || mapping.ResourceKind != protocol.ResourceSession {
		t.Fatalf("mapping=%#v, want adapter a and kind %q", mapping, protocol.ResourceSession)
	}
}
