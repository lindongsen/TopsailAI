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
	if _, err := e.Execute(context.Background(), intent, "hash"); err == nil {
		t.Fatal("missing target must be rejected")
	}
}

type testAdapterForCoverage struct{ adapter.Adapter }

func (testAdapterForCoverage) Describe(context.Context) (adapter.Descriptor, error) {
	return adapter.Descriptor{Capabilities: protocol.CapabilityDescriptor{Capabilities: []protocol.Capability{{Name: "send", Version: "v1"}}}}, nil
}
