package endpoint

import (
	"context"
	"errors"
	"testing"
	"time"

	"topsailai_agent_cluster/internal/adapter"
	"topsailai_agent_cluster/internal/protocol"
	endpointstorage "topsailai_agent_cluster/internal/storage/endpoint"
)

// handleResolvingAdapter is a fixture adapter that accepts a provider session
// handle and records how often it was asked to resolve one.
type handleResolvingAdapter struct {
	countingExecuteAdapter
	resolutions int
	handle      string
	// mapper is the same durable mapper the Endpoint resolves targets through.
	// In production the adapter's mapper IS the Endpoint store, so resolution
	// persists the mapping and the later lookup finds it. A fixture that returned
	// a mapping without persisting it would fail the lookup for a reason the real
	// adapter never has.
	mapper adapter.ResourceMapper
}

// Inspect mirrors the real adapter's contract: Live is derived from the
// generation, because a record without a generation is listed but unverified.
// The embedded fixture leaves Live false, which would make the resume liveness
// gate untestable and let a live target pass.
func (a *handleResolvingAdapter) Inspect(_ context.Context, _ adapter.InspectRequest) (adapter.InspectResult, error) {
	a.inspections++
	return adapter.InspectResult{Found: a.found, Live: a.generation != "", ProviderGeneration: a.generation}, nil
}

func (a *handleResolvingAdapter) ResolveProviderSessionHandle(ctx context.Context, handle string) (adapter.ResourceMapping, error) {
	a.resolutions++
	a.handle = handle
	if a.mapper == nil {
		return adapter.ResourceMapping{}, errors.New("fixture mapper is required")
	}
	return a.mapper.GetOrCreateResourceID(ctx, "a1", "session-row:"+handle, time.Now().UnixMilli())
}

// newHandleExecutor builds an executor whose registry holds the supplied adapter
// under one configured instance.
func newHandleExecutor(t *testing.T, instance adapter.Adapter) (*Executor, *endpointstorage.Store) {
	t.Helper()
	store, err := endpointstorage.Open(context.Background(), t.TempDir()+"/endpoint.db")
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = store.Close() })
	if resolving, ok := instance.(*handleResolvingAdapter); ok {
		resolving.mapper = store
	}
	registry := adapter.NewRegistry()
	if err := registry.RegisterType("fixture", func(context.Context, adapter.Config) (adapter.Adapter, error) {
		return instance, nil
	}); err != nil {
		t.Fatal(err)
	}
	if _, err := registry.Configure(context.Background(), adapter.Config{AdapterID: "a1", ProviderType: "fixture"}); err != nil {
		t.Fatal(err)
	}
	executor, err := NewExecutor(store, registry)
	if err != nil {
		t.Fatal(err)
	}
	return executor, store
}

// handleIntent builds one resume intent that names its target by provider session
// handle and carries no resource ID, which is the shape the client sends.
func handleIntent(commandID, handle string) protocol.ImmutableIntent {
	return protocol.ImmutableIntent{
		CommandID:         commandID,
		EndpointID:        "e1",
		Operation:         protocol.OperationAgentResume,
		OperationVersion:  "v1",
		Target:            &protocol.CommandTarget{Kind: "session", ProviderSessionHandle: handle},
		ExecuteBeforeAtMS: time.Now().Add(time.Minute).UnixMilli(),
	}
}

// TestExecuteResolvesProviderSessionHandleWithoutDiscovery proves a handle target
// is resolved locally and reaches the adapter. The operator named the session, so
// the Endpoint must mint the mapping instead of rejecting a session it has not
// discovered yet.
func TestExecuteResolvesProviderSessionHandleWithoutDiscovery(t *testing.T) {
	instance := &handleResolvingAdapter{countingExecuteAdapter: countingExecuteAdapter{found: true}}
	executor, _ := newHandleExecutor(t, instance)
	receipt, err := executor.Execute(context.Background(), handleIntent("handle-resume", "wa-1"), "hash")
	if err != nil {
		t.Fatalf("a handle target must not be an infrastructure failure: %v", err)
	}
	if receipt.ErrorCode != "" {
		t.Fatalf("error code=%q, want none", receipt.ErrorCode)
	}
	if instance.resolutions != 1 {
		t.Fatalf("resolutions=%d, want 1", instance.resolutions)
	}
	if instance.handle != "wa-1" {
		t.Fatalf("resolved handle=%q, want wa-1", instance.handle)
	}
	if instance.executions != 1 {
		t.Fatalf("executions=%d, want 1", instance.executions)
	}
}

// TestExecuteRejectsHandleWhenNoAdapterAcceptsIt proves an Endpoint with no
// handle-capable adapter reports a durable terminal rejection instead of leaving
// the command in flight.
func TestExecuteRejectsHandleWhenNoAdapterAcceptsIt(t *testing.T) {
	executor, store := newHandleExecutor(t, &countingExecuteAdapter{found: true})
	receipt, err := executor.Execute(context.Background(), handleIntent("handle-unowned", "wa-1"), "hash")
	if err != nil {
		t.Fatalf("an unowned handle is a decision, not an infrastructure failure: %v", err)
	}
	if receipt.ErrorCode != "target_not_found" {
		t.Fatalf("error code=%q, want target_not_found", receipt.ErrorCode)
	}
	assertTerminalRejection(t, store, "handle-unowned", "target_not_found")
}

// TestExecuteRejectsAmbiguousHandleTarget proves a target carrying both a resource
// ID and a handle is refused. Accepting it would leave the Endpoint choosing which
// identity to trust, and the two could name different sessions.
func TestExecuteRejectsAmbiguousHandleTarget(t *testing.T) {
	instance := &handleResolvingAdapter{countingExecuteAdapter: countingExecuteAdapter{found: true}}
	executor, store := newHandleExecutor(t, instance)
	intent := handleIntent("handle-ambiguous", "wa-1")
	intent.Target.ResourceID = "res_other"
	receipt, err := executor.Execute(context.Background(), intent, "hash")
	if err != nil {
		t.Fatalf("an ambiguous target is a decision, not an infrastructure failure: %v", err)
	}
	if receipt.ErrorCode != "target_ambiguous" {
		t.Fatalf("error code=%q, want target_ambiguous", receipt.ErrorCode)
	}
	if instance.resolutions != 0 {
		t.Fatalf("resolutions=%d, want 0 because the target was refused first", instance.resolutions)
	}
	assertTerminalRejection(t, store, "handle-ambiguous", "target_ambiguous")
}

// TestExecuteRejectsHandleWhenTwoAdaptersAcceptIt proves the Endpoint refuses to
// guess which adapter owns a handle. Guessing would address a session on an
// adapter the operator never named.
func TestExecuteRejectsHandleWhenTwoAdaptersAcceptIt(t *testing.T) {
	store, err := endpointstorage.Open(context.Background(), t.TempDir()+"/endpoint.db")
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = store.Close() })
	registry := adapter.NewRegistry()
	if err := registry.RegisterType("fixture", func(context.Context, adapter.Config) (adapter.Adapter, error) {
		return &handleResolvingAdapter{countingExecuteAdapter: countingExecuteAdapter{found: true}}, nil
	}); err != nil {
		t.Fatal(err)
	}
	for _, id := range []string{"a1", "a2"} {
		if _, err := registry.Configure(context.Background(), adapter.Config{AdapterID: id, ProviderType: "fixture"}); err != nil {
			t.Fatal(err)
		}
	}
	executor, err := NewExecutor(store, registry)
	if err != nil {
		t.Fatal(err)
	}
	receipt, err := executor.Execute(context.Background(), handleIntent("handle-two-owners", "wa-1"), "hash")
	if err != nil {
		t.Fatalf("an ambiguous owner is a decision, not an infrastructure failure: %v", err)
	}
	if receipt.ErrorCode != "target_ambiguous" {
		t.Fatalf("error code=%q, want target_ambiguous", receipt.ErrorCode)
	}
	assertTerminalRejection(t, store, "handle-two-owners", "target_ambiguous")
}

// TestExecuteStillRejectsLiveHandleTarget proves resolution does not weaken the
// liveness gate. A resolved handle whose session is still running must still be
// refused, because resume exists only for a stopped session.
func TestExecuteStillRejectsLiveHandleTarget(t *testing.T) {
	instance := &handleResolvingAdapter{countingExecuteAdapter: countingExecuteAdapter{found: true, generation: "g7"}}
	executor, store := newHandleExecutor(t, instance)
	receipt, err := executor.Execute(context.Background(), handleIntent("handle-live", "wa-1"), "hash")
	if err != nil {
		t.Fatalf("a live target is a decision, not an infrastructure failure: %v", err)
	}
	if receipt.ErrorCode != "target_still_active" {
		t.Fatalf("error code=%q, want target_still_active", receipt.ErrorCode)
	}
	if instance.executions != 0 {
		t.Fatalf("executions=%d, want 0 because a live target must not be resumed", instance.executions)
	}
	assertTerminalRejection(t, store, "handle-live", "target_still_active")
}
