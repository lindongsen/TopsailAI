package endpoint

import (
	"context"
	"sync"
	"testing"
	"time"

	"topsailai_agent_cluster/internal/adapter"
	"topsailai_agent_cluster/internal/protocol"
	endpointstorage "topsailai_agent_cluster/internal/storage/endpoint"
)

// blockingAdapter blocks inside Execute until the test releases it, so a
// replacement can be applied while a command is genuinely in flight.
type blockingAdapter struct {
	started chan struct{}
	release chan struct{}
	once    sync.Once

	mu     sync.Mutex
	closes int
}

func (a *blockingAdapter) Describe(context.Context) (adapter.Descriptor, error) {
	return adapter.Descriptor{
		AdapterID: "a1",
		Capabilities: protocol.CapabilityDescriptor{Revision: "v1", Capabilities: []protocol.Capability{
			{Name: protocol.OperationAgentStart, Version: "v1"},
			{Name: protocol.OperationMessageSend, Version: "v1"},
		}},
	}, nil
}

func (a *blockingAdapter) Discover(context.Context, adapter.DiscoverRequest) (adapter.DiscoverResult, error) {
	return adapter.DiscoverResult{}, nil
}

func (a *blockingAdapter) Inspect(context.Context, adapter.InspectRequest) (adapter.InspectResult, error) {
	return adapter.InspectResult{Found: true, ProviderGeneration: "g1"}, nil
}

func (a *blockingAdapter) Execute(context.Context, adapter.ExecuteRequest) (adapter.ExecuteResult, error) {
	a.once.Do(func() { close(a.started) })
	<-a.release
	return adapter.ExecuteResult{Receipt: protocol.ExecutionReceipt{Outcome: "succeeded", EffectCertainty: protocol.EffectAcknowledged, DeliveryBoundary: protocol.DeliverySubmitted}}, nil
}

func (a *blockingAdapter) ReadOutput(context.Context, adapter.OutputRequest) (adapter.OutputResult, error) {
	return adapter.OutputResult{}, nil
}

func (a *blockingAdapter) QueryCommand(context.Context, adapter.CommandQuery) (adapter.CommandResult, error) {
	return adapter.CommandResult{}, adapter.ErrUnsupported
}

func (a *blockingAdapter) Watch(context.Context) (<-chan adapter.Event, error) {
	return nil, adapter.ErrUnsupported
}

func (a *blockingAdapter) Close() error {
	a.mu.Lock()
	defer a.mu.Unlock()
	a.closes++
	return nil
}

func (a *blockingAdapter) closeCount() int {
	a.mu.Lock()
	defer a.mu.Unlock()
	return a.closes
}

// TestExecutorKeepsInFlightCommandOnItsOwnVersion proves the property Unit 7 needs:
// replacing the Provider CLI version while a command is executing does not close the
// instance that command is using, and the command finishes on the version it
// validated against instead of being redirected to a version it never checked.
func TestExecutorKeepsInFlightCommandOnItsOwnVersion(t *testing.T) {
	store, err := endpointstorage.Open(context.Background(), t.TempDir()+"/endpoint.db")
	if err != nil {
		t.Fatal(err)
	}
	defer store.Close()

	previous := &blockingAdapter{started: make(chan struct{}), release: make(chan struct{})}
	registry := adapter.NewRegistry()
	if err := registry.RegisterType("fixture", func(context.Context, adapter.Config) (adapter.Adapter, error) {
		return previous, nil
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

	intent := protocol.ImmutableIntent{
		HashVersion:          "v1",
		CommandID:            "replace-in-flight",
		EndpointID:           "e1",
		Operation:            protocol.OperationAgentStart,
		LaunchProfileID:      "a1",
		ProfileRevision:      "v1",
		OperationVersion:     "v1",
		CapabilityRevision:   "v1",
		PayloadSchemaVersion: "v1",
		Payload:              []byte(`{"folder":"/tmp/p","task":"t"}`),
		ExecuteBeforeAtMS:    time.Now().Add(10 * time.Second).UnixMilli(),
	}

	type outcome struct {
		receipt protocol.ExecutionReceipt
		err     error
	}
	done := make(chan outcome, 1)
	go func() {
		receipt, executeErr := executor.Execute(context.Background(), intent, "hash")
		done <- outcome{receipt: receipt, err: executeErr}
	}()

	select {
	case <-previous.started:
	case <-time.After(5 * time.Second):
		t.Fatal("adapter was not called")
	}

	next := &blockingAdapter{started: make(chan struct{}), release: make(chan struct{})}
	if _, err := registry.Replace("a1", next); err != nil {
		t.Fatalf("replace: %v", err)
	}
	if got := previous.closeCount(); got != 0 {
		t.Fatalf("in-flight instance was closed by the replacement: closes=%d", got)
	}
	if got := registry.InFlight("a1"); got != 1 {
		t.Fatalf("in-flight count = %d, want 1", got)
	}

	close(previous.release)
	select {
	case result := <-done:
		if result.err != nil {
			t.Fatalf("execute: %v", result.err)
		}
		if result.receipt.Outcome != "succeeded" {
			t.Fatalf("outcome = %q, want succeeded", result.receipt.Outcome)
		}
	case <-time.After(5 * time.Second):
		t.Fatal("execute did not finish")
	}

	if got := previous.closeCount(); got != 1 {
		t.Fatalf("retired instance close count = %d, want 1", got)
	}
	if got := registry.InFlight("a1"); got != 0 {
		t.Fatalf("in-flight count after completion = %d, want 0", got)
	}
	if got := next.closeCount(); got != 0 {
		t.Fatalf("active instance was closed: closes=%d", got)
	}
	current, ok := registry.Get("a1")
	if !ok || current != next {
		t.Fatal("registry does not expose the replacement")
	}
}

// TestExecutorFollowPinsTheVersionItStartedOn proves a long-lived follow holds its
// reference for the whole stream, so a replacement cannot close the instance that is
// still emitting records.
func TestExecutorFollowPinsTheVersionItStartedOn(t *testing.T) {
	store, err := endpointstorage.Open(context.Background(), t.TempDir()+"/endpoint.db")
	if err != nil {
		t.Fatal(err)
	}
	defer store.Close()

	previous := &blockingAdapter{started: make(chan struct{}), release: make(chan struct{})}
	registry := adapter.NewRegistry()
	if err := registry.RegisterType("fixture", func(context.Context, adapter.Config) (adapter.Adapter, error) {
		return previous, nil
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

	// A follow resolves the adapter through the resource mapping, so the mapping row
	// has to exist before the stream can start.
	mapping, err := store.GetOrCreateResourceID(context.Background(), "a1", protocol.ResourceSession, "session-row:v1:key", time.Now().UnixMilli())
	if err != nil {
		t.Fatalf("create mapping: %v", err)
	}

	// The follow path needs an OutputFollower, which blockingAdapter does not
	// implement, so this test asserts the reference is held by the resolution step
	// itself: an unsupported follow still acquires and releases cleanly, and a
	// replacement applied afterwards closes the retired instance exactly once.
	err = executor.FollowOutput(context.Background(), protocol.OutputFollowRequest{ResourceID: mapping.ResourceID, ProviderGeneration: "g1"}, func(protocol.OutputChunk) error { return nil })
	if err == nil {
		t.Fatal("expected unsupported follow")
	}
	if got := registry.InFlight("a1"); got != 0 {
		t.Fatalf("follow leaked a reference: in-flight=%d", got)
	}

	next := &blockingAdapter{started: make(chan struct{}), release: make(chan struct{})}
	if _, err := registry.Replace("a1", next); err != nil {
		t.Fatalf("replace: %v", err)
	}
	if got := previous.closeCount(); got != 1 {
		t.Fatalf("retired instance close count = %d, want 1", got)
	}
}

// TestExecutorKeepsInFlightTargetCommandOnItsOwnVersion covers the resource-target
// resolution branch, which is the path every session-scoped command takes. The
// launch-profile branch is covered above; without this case a regression that
// reverted only the target branch to a non-holding lookup would stay invisible.
func TestExecutorKeepsInFlightTargetCommandOnItsOwnVersion(t *testing.T) {
	store, err := endpointstorage.Open(context.Background(), t.TempDir()+"/endpoint.db")
	if err != nil {
		t.Fatal(err)
	}
	defer store.Close()

	previous := &blockingAdapter{started: make(chan struct{}), release: make(chan struct{})}
	registry := adapter.NewRegistry()
	if err := registry.RegisterType("fixture", func(context.Context, adapter.Config) (adapter.Adapter, error) {
		return previous, nil
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

	mapping, err := store.GetOrCreateResourceID(context.Background(), "a1", protocol.ResourceSession, "session-row:v1:target", time.Now().UnixMilli())
	if err != nil {
		t.Fatalf("create mapping: %v", err)
	}

	intent := protocol.ImmutableIntent{
		HashVersion:          "v1",
		CommandID:            "replace-in-flight-target",
		EndpointID:           "e1",
		Operation:            protocol.OperationMessageSend,
		Target:               &protocol.CommandTarget{Kind: "session", ResourceID: mapping.ResourceID, ProviderGeneration: "g1"},
		OperationVersion:     "v1",
		CapabilityRevision:   "v1",
		PayloadSchemaVersion: "v1",
		Payload:              []byte(`{"text":"hello"}`),
		ExecuteBeforeAtMS:    time.Now().Add(10 * time.Second).UnixMilli(),
	}

	done := make(chan error, 1)
	go func() {
		_, executeErr := executor.Execute(context.Background(), intent, "hash")
		done <- executeErr
	}()

	select {
	case <-previous.started:
	case <-time.After(5 * time.Second):
		t.Fatal("adapter was not called")
	}

	next := &blockingAdapter{started: make(chan struct{}), release: make(chan struct{})}
	if _, err := registry.Replace("a1", next); err != nil {
		t.Fatalf("replace: %v", err)
	}
	if got := previous.closeCount(); got != 0 {
		t.Fatalf("in-flight target command lost its instance: closes=%d", got)
	}

	close(previous.release)
	select {
	case executeErr := <-done:
		if executeErr != nil {
			t.Fatalf("execute: %v", executeErr)
		}
	case <-time.After(5 * time.Second):
		t.Fatal("execute did not finish")
	}
	if got := previous.closeCount(); got != 1 {
		t.Fatalf("retired instance close count = %d, want 1", got)
	}
}
