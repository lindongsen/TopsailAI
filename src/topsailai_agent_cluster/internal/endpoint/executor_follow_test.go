package endpoint

import (
	"context"
	"errors"
	"testing"

	"topsailai_agent_cluster/internal/adapter"
	"topsailai_agent_cluster/internal/protocol"
	endpointstorage "topsailai_agent_cluster/internal/storage/endpoint"
)

// followTestAdapter is an adapter that can stream output records. It embeds the
// Adapter interface so the methods a follow does not use stay unimplemented, and
// it records the request it received so a test can prove the Endpoint forwarded
// the caller's budgets instead of substituting its own.
type followTestAdapter struct {
	adapter.Adapter
	chunks   []protocol.OutputChunk
	err      error
	received *protocol.OutputFollowRequest
}

// Inspect reports the resource as present at generation g1, which is the
// generation every test in this file requests.
func (a *followTestAdapter) Inspect(context.Context, adapter.InspectRequest) (adapter.InspectResult, error) {
	return adapter.InspectResult{Found: true, Generation: "g1"}, nil
}

// FollowOutput emits the configured chunks and then returns the configured error.
func (a *followTestAdapter) FollowOutput(_ context.Context, request protocol.OutputFollowRequest, emit func(protocol.OutputChunk) error) error {
	if a.received != nil {
		*a.received = request
	}
	for _, chunk := range a.chunks {
		if err := emit(chunk); err != nil {
			return err
		}
	}
	return a.err
}

// newFollowExecutor builds an executor whose registry holds one configured
// adapter of the supplied instance, plus the resource mapping that adapter owns.
func newFollowExecutor(t *testing.T, instance adapter.Adapter) (*Executor, string) {
	t.Helper()
	store, err := endpointstorage.Open(context.Background(), t.TempDir()+"/endpoint.db")
	if err != nil {
		t.Fatalf("open store: %v", err)
	}
	t.Cleanup(func() { _ = store.Close() })
	registry := adapter.NewRegistry()
	if err := registry.RegisterType("fixture", func(context.Context, adapter.Config) (adapter.Adapter, error) {
		return instance, nil
	}); err != nil {
		t.Fatalf("register type: %v", err)
	}
	if _, err := registry.Configure(context.Background(), adapter.Config{AdapterID: "a1", ProviderType: "fixture"}); err != nil {
		t.Fatalf("configure adapter: %v", err)
	}
	mapping, err := store.GetOrCreateResourceID(context.Background(), "a1", "provider", 1)
	if err != nil {
		t.Fatalf("create mapping: %v", err)
	}
	executor, err := NewExecutor(store, registry)
	if err != nil {
		t.Fatalf("new executor: %v", err)
	}
	return executor, mapping.ResourceID
}

// TestFollowOutputStreamsChunks proves the executor delegates to the adapter and
// forwards every chunk to the caller in order.
func TestFollowOutputStreamsChunks(t *testing.T) {
	instance := &followTestAdapter{chunks: []protocol.OutputChunk{
		{Lines: []string{"first"}, ObservedAtMS: 1},
		{Lines: []string{"second"}, ObservedAtMS: 2},
	}}
	executor, resourceID := newFollowExecutor(t, instance)
	var lines []string
	err := executor.FollowOutput(context.Background(), protocol.OutputFollowRequest{ResourceID: resourceID, Generation: "g1"}, func(chunk protocol.OutputChunk) error {
		lines = append(lines, chunk.Lines...)
		return nil
	})
	if err != nil {
		t.Fatalf("follow: %v", err)
	}
	if len(lines) != 2 || lines[0] != "first" || lines[1] != "second" {
		t.Fatalf("lines=%v", lines)
	}
}

// TestFollowOutputForwardsBudgets proves the executor passes the caller's own
// request through unchanged, so a budget the Server set is never silently
// replaced by an Endpoint default.
func TestFollowOutputForwardsBudgets(t *testing.T) {
	var received protocol.OutputFollowRequest
	instance := &followTestAdapter{received: &received}
	executor, resourceID := newFollowExecutor(t, instance)
	request := protocol.OutputFollowRequest{ResourceID: resourceID, Generation: "g1", MaxBytes: 4096, MaxLines: 7}
	if err := executor.FollowOutput(context.Background(), request, func(protocol.OutputChunk) error { return nil }); err != nil {
		t.Fatalf("follow: %v", err)
	}
	if received.MaxBytes != 4096 || received.MaxLines != 7 || received.ResourceID != resourceID {
		t.Fatalf("received=%#v", received)
	}
}

// TestFollowOutputUnsupportedWhenAdapterCannotStream proves an adapter without
// the streaming capability reports ErrUnsupported rather than a provider failure,
// so the Endpoint can answer "unsupported" honestly.
func TestFollowOutputUnsupportedWhenAdapterCannotStream(t *testing.T) {
	executor, resourceID := newFollowExecutor(t, outputTestAdapter{})
	err := executor.FollowOutput(context.Background(), protocol.OutputFollowRequest{ResourceID: resourceID, Generation: "g1"}, func(protocol.OutputChunk) error { return nil })
	if !errors.Is(err, adapter.ErrUnsupported) {
		t.Fatalf("err=%v", err)
	}
}

// TestFollowOutputRejectsIncompleteTarget proves a request without a resource ID
// or generation is refused before any adapter is consulted.
func TestFollowOutputRejectsIncompleteTarget(t *testing.T) {
	instance := &followTestAdapter{}
	executor, resourceID := newFollowExecutor(t, instance)
	cases := []protocol.OutputFollowRequest{
		{Generation: "g1"},
		{ResourceID: resourceID},
	}
	for _, request := range cases {
		if err := executor.FollowOutput(context.Background(), request, func(protocol.OutputChunk) error { return nil }); err == nil {
			t.Fatalf("request=%#v was accepted", request)
		}
	}
}

// TestFollowOutputRejectsUnknownResource proves an unmapped resource ID fails
// instead of reaching an arbitrary adapter.
func TestFollowOutputRejectsUnknownResource(t *testing.T) {
	executor, _ := newFollowExecutor(t, &followTestAdapter{})
	err := executor.FollowOutput(context.Background(), protocol.OutputFollowRequest{ResourceID: "res_missing", Generation: "g1"}, func(protocol.OutputChunk) error { return nil })
	if err == nil {
		t.Fatal("unknown resource was accepted")
	}
}

// TestFollowOutputRejectsGenerationMismatch proves a stale generation is refused
// before the provider child is started, so a follow never attaches to a
// replacement session that reused the resource ID.
func TestFollowOutputRejectsGenerationMismatch(t *testing.T) {
	executor, resourceID := newFollowExecutor(t, &followTestAdapter{})
	err := executor.FollowOutput(context.Background(), protocol.OutputFollowRequest{ResourceID: resourceID, Generation: "g2"}, func(protocol.OutputChunk) error { return nil })
	if err == nil {
		t.Fatal("generation mismatch was accepted")
	}
}

// TestFollowOutputPropagatesConsumerStop proves a consumer that stops the stream
// ends the follow with that error instead of being reported as a provider
// failure, because stopping is a normal termination.
func TestFollowOutputPropagatesConsumerStop(t *testing.T) {
	instance := &followTestAdapter{chunks: []protocol.OutputChunk{{Lines: []string{"first"}}}}
	executor, resourceID := newFollowExecutor(t, instance)
	err := executor.FollowOutput(context.Background(), protocol.OutputFollowRequest{ResourceID: resourceID, Generation: "g1"}, func(protocol.OutputChunk) error {
		return adapter.ErrFollowStopped
	})
	if !errors.Is(err, adapter.ErrFollowStopped) {
		t.Fatalf("err=%v", err)
	}
}
