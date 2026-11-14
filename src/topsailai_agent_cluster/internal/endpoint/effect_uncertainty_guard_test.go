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

// uncertaintyAdapter returns a decoded receipt together with an error, which is
// what a provider does when it reports an unconfirmed outcome on a non-zero exit.
type uncertaintyAdapter struct {
	adapter.Adapter
	receipt adapter.ExecuteResult
	err     error
}

func (a uncertaintyAdapter) Describe(context.Context) (adapter.Descriptor, error) {
	return adapter.Descriptor{AdapterID: "a1", Capabilities: protocol.CapabilityDescriptor{Revision: "v1", Capabilities: []protocol.Capability{{Name: "agent.start", Version: "v1"}}}}, nil
}

func (a uncertaintyAdapter) Inspect(context.Context, adapter.InspectRequest) (adapter.InspectResult, error) {
	return adapter.InspectResult{Found: true, ProviderGeneration: "g1"}, nil
}

func (a uncertaintyAdapter) Execute(context.Context, adapter.ExecuteRequest) (adapter.ExecuteResult, error) {
	return a.receipt, a.err
}

// newUncertaintyExecutor builds an executor whose only adapter is the fixture.
func newUncertaintyExecutor(t *testing.T, fixture uncertaintyAdapter) *Executor {
	t.Helper()
	store, err := endpointstorage.Open(context.Background(), t.TempDir()+"/endpoint.db")
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { store.Close() })
	registry := adapter.NewRegistry()
	if err := registry.RegisterType("fixture", func(context.Context, adapter.Config) (adapter.Adapter, error) {
		return fixture, nil
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
	return executor
}

// uncertaintyIntent builds an intent that passes admission for the fixture.
func uncertaintyIntent(commandID string) protocol.ImmutableIntent {
	return protocol.ImmutableIntent{
		HashVersion: "v1", CommandID: commandID, EndpointID: "e1",
		Operation: "agent.start", LaunchProfileID: "a1", OperationVersion: "v1",
		CapabilityRevision: "v1", PayloadSchemaVersion: "v1", Payload: []byte(`{"x":1}`),
		ExecuteBeforeAtMS: time.Now().Add(time.Minute).UnixMilli(),
		Budget:            protocol.Budget{CLITimeoutMS: 5000},
		ProfileRevision:   "v1",
	}
}

// TestDeadlineFailurePreservesUnknownEffect proves a deadline that fires while
// the adapter is working leaves the effect unknown rather than flattening it to
// a definite failure. An unknown effect is the only honest answer: the provider
// may or may not have applied the change.
func TestDeadlineFailurePreservesUnknownEffect(t *testing.T) {
	executor := newUncertaintyExecutor(t, uncertaintyAdapter{err: context.DeadlineExceeded})
	receipt, err := executor.Execute(context.Background(), uncertaintyIntent("deadline-unknown"), "hash")
	if err == nil {
		t.Fatal("a deadline failure returned no error")
	}
	if receipt.EffectCertainty != protocol.EffectUnknown {
		t.Fatalf("effect certainty=%q, want %q", receipt.EffectCertainty, protocol.EffectUnknown)
	}
	if receipt.Outcome != "failed" {
		t.Fatalf("outcome=%q, want failed", receipt.Outcome)
	}
	if receipt.Phase != protocol.PhaseReceiptRecorded {
		t.Fatalf("phase=%q, want %q", receipt.Phase, protocol.PhaseReceiptRecorded)
	}
}

// TestCancellationFailurePreservesUnknownEffect proves cancellation is treated
// the same way as a deadline: the effect stays unknown.
func TestCancellationFailurePreservesUnknownEffect(t *testing.T) {
	executor := newUncertaintyExecutor(t, uncertaintyAdapter{err: context.Canceled})
	receipt, err := executor.Execute(context.Background(), uncertaintyIntent("cancel-unknown"), "hash")
	if err == nil {
		t.Fatal("a cancellation returned no error")
	}
	if receipt.EffectCertainty != protocol.EffectUnknown {
		t.Fatalf("effect certainty=%q, want %q", receipt.EffectCertainty, protocol.EffectUnknown)
	}
}

// TestAdapterEvidenceIsNotFlattened proves the executor only fills in what the
// adapter left empty. An adapter that already determined the effect keeps its
// answer, so a decoded provider document is not overwritten by a generic
// failure.
func TestAdapterEvidenceIsNotFlattened(t *testing.T) {
	fixture := uncertaintyAdapter{
		receipt: adapter.ExecuteResult{Receipt: protocol.ExecutionReceipt{
			Outcome:          "unconfirmed",
			EffectCertainty:  protocol.EffectAcknowledged,
			DeliveryBoundary: protocol.DeliverySignalSent,
		}},
		err: errors.New("provider reported an unconfirmed outcome"),
	}
	executor := newUncertaintyExecutor(t, fixture)
	receipt, err := executor.Execute(context.Background(), uncertaintyIntent("evidence-kept"), "hash")
	if err == nil {
		t.Fatal("an adapter error returned no error")
	}
	if receipt.EffectCertainty != protocol.EffectAcknowledged {
		t.Fatalf("effect certainty=%q, want the adapter's %q to survive", receipt.EffectCertainty, protocol.EffectAcknowledged)
	}
	if receipt.Outcome != "unconfirmed" {
		t.Fatalf("outcome=%q, want the adapter's unconfirmed to survive", receipt.Outcome)
	}
	if receipt.DeliveryBoundary != protocol.DeliverySignalSent {
		t.Fatalf("delivery boundary=%q, want the adapter's %q to survive", receipt.DeliveryBoundary, protocol.DeliverySignalSent)
	}
}

// TestSuccessKeepsTheAdapterCertainty proves the fill-in path does not run on a
// successful invocation, so a definite acknowledgement is never rewritten.
func TestSuccessKeepsTheAdapterCertainty(t *testing.T) {
	fixture := uncertaintyAdapter{
		receipt: adapter.ExecuteResult{Receipt: protocol.ExecutionReceipt{
			Outcome:          "succeeded",
			EffectCertainty:  protocol.EffectAcknowledged,
			DeliveryBoundary: protocol.DeliverySubmitted,
		}},
	}
	executor := newUncertaintyExecutor(t, fixture)
	receipt, err := executor.Execute(context.Background(), uncertaintyIntent("success-kept"), "hash")
	if err != nil {
		t.Fatalf("a successful invocation returned %v", err)
	}
	if receipt.EffectCertainty != protocol.EffectAcknowledged {
		t.Fatalf("effect certainty=%q, want %q", receipt.EffectCertainty, protocol.EffectAcknowledged)
	}
}
