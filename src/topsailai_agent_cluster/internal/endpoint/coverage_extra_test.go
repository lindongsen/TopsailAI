package endpoint

import (
	"context"
	"testing"
	"time"

	"topsailai_agent_cluster/internal/adapter"
	"topsailai_agent_cluster/internal/protocol"
	endpointstorage "topsailai_agent_cluster/internal/storage/endpoint"
)

func TestExecutorValidationAndHelperBranches(t *testing.T) {
	if _, err := NewExecutor(nil, nil); err == nil {
		t.Fatal("nil dependencies must fail")
	}
	caps := protocol.CapabilityDescriptor{Capabilities: []protocol.Capability{{Name: "send", Version: "v1"}}}
	if supports(caps, "send", "v2") || supports(caps, "missing", "v1") || !supports(caps, "send", "v1") {
		t.Fatal("capability matching is incorrect")
	}
	if got := targetKey(protocol.ImmutableIntent{LaunchProfileID: "profile"}); got != "profile" {
		t.Fatalf("start key=%q", got)
	}
	if got := targetKey(protocol.ImmutableIntent{EndpointID: "e", Target: &protocol.CommandTarget{Kind: "session", ResourceID: "r"}}); got != "e:session:r" {
		t.Fatalf("target key=%q", got)
	}
	r := unknownReceipt(protocol.ImmutableIntent{CommandID: "c"}, "h", "x")
	if r.ErrorCode != "x" {
		t.Fatal("unknown receipt code missing")
	}
	if _, err := decodeReceipt(""); err == nil {
		t.Fatal("empty receipt must fail")
	}
	if _, err := decodeReceipt("not-json"); err == nil {
		t.Fatal("invalid receipt must fail")
	}
}

func TestExecutorRejectsMissingTargetBeforeProvider(t *testing.T) {
	store, err := endpointstorage.Open(context.Background(), t.TempDir()+"/endpoint.db")
	if err != nil {
		t.Fatal(err)
	}
	defer store.Close()
	registry := adapter.NewRegistry()
	if err := registry.RegisterType("fixture", func(context.Context, adapter.Config) (adapter.Adapter, error) { return testAdapterForCoverage{}, nil }); err != nil {
		t.Fatal(err)
	}
	if _, err := registry.Configure(context.Background(), adapter.Config{AdapterID: "a", ProviderType: "fixture"}); err == nil {
		_ = err
	}
	e, err := NewExecutor(store, registry)
	if err != nil {
		t.Fatal(err)
	}
	intent := protocol.ImmutableIntent{CommandID: "missing-target", EndpointID: "e", Operation: "send", OperationVersion: "v1", ExecuteBeforeAtMS: time.Now().Add(time.Minute).UnixMilli()}
	receipt, err := e.Execute(context.Background(), intent, "hash")
	if err != nil {
		t.Fatalf("a missing target is a decision, not an infrastructure failure: %v", err)
	}
	if receipt.ErrorCode != "target_required" {
		t.Fatalf("error code=%q, want target_required", receipt.ErrorCode)
	}
	if receipt.EffectCertainty != protocol.EffectNotApplied {
		t.Fatalf("effect certainty=%q, want not_applied", receipt.EffectCertainty)
	}
	if receipt.Outcome != "rejected" {
		t.Fatalf("outcome=%q, want rejected", receipt.Outcome)
	}
	entry, err := store.GetJournal(context.Background(), intent.CommandID)
	if err != nil {
		t.Fatalf("the rejection must be durable: %v", err)
	}
	if entry.Phase != protocol.PhaseReceiptRecorded {
		t.Fatalf("journal phase=%q, want %q", entry.Phase, protocol.PhaseReceiptRecorded)
	}
}

type testAdapterForCoverage struct{ adapter.Adapter }

func (testAdapterForCoverage) Describe(context.Context) (adapter.Descriptor, error) {
	return adapter.Descriptor{Capabilities: protocol.CapabilityDescriptor{Capabilities: []protocol.Capability{{Name: "send", Version: "v1"}}}}, nil
}

func TestCollectorRejectsInvalidTimeoutAndObservationTime(t *testing.T) {
	if _, err := NewCollector(context.Background(), nil, 0, nil); err == nil {
		t.Fatal("zero timeout was accepted")
	}
	collector, err := NewCollector(context.Background(), nil, time.Second, nil)
	if err != nil {
		t.Fatal(err)
	}
	if _, err := collector.Collect(context.Background(), 0); err == nil || err.Error() != "observation time must be positive" {
		t.Fatalf("invalid observation result=%v", err)
	}
}
