package endpoint

import (
	"context"
	"testing"
	"time"

	"topsailai_agent_cluster/internal/adapter"
	"topsailai_agent_cluster/internal/protocol"
	endpointstorage "topsailai_agent_cluster/internal/storage/endpoint"
)

func TestLocalAPIDelegatesToExecutor(t *testing.T) {
	if NewLocalAPI(nil).executor != nil {
		t.Fatal("nil executor changed")
	}
	_ = context.Background()
	_ = protocol.ImmutableIntent{}
}

func TestLocalAPIExecutesThroughConfiguredExecutor(t *testing.T) {
	store, err := endpointstorage.Open(context.Background(), t.TempDir()+"/endpoint.db")
	if err != nil {
		t.Fatal(err)
	}
	defer store.Close()
	registry := adapter.NewRegistry()
	configured := &coverageAdapter{}
	if err := registry.RegisterType("fixture", func(context.Context, adapter.Config) (adapter.Adapter, error) { return configured, nil }); err != nil {
		t.Fatal(err)
	}
	if _, err := registry.Configure(context.Background(), adapter.Config{AdapterID: "a", ProviderType: "fixture"}); err != nil {
		t.Fatal(err)
	}
	executor, err := NewExecutor(store, registry)
	if err != nil {
		t.Fatal(err)
	}
	api := NewLocalAPI(executor)
	intent := protocol.ImmutableIntent{
		HashVersion: "v1", CommandID: "local-command", EndpointID: "endpoint-1",
		LaunchProfileID: "a", ProfileRevision: "rev-1", Operation: "agent.start",
		OperationVersion: "v1", CapabilityRevision: "rev-1", PayloadSchemaVersion: "v1",
		Payload: []byte(`{"name":"demo"}`), ExecuteBeforeAtMS: time.Now().Add(time.Minute).UnixMilli(),
	}
	receipt, err := api.Execute(context.Background(), intent, "request-hash")
	if err != nil {
		t.Fatalf("execute through local API: %v", err)
	}
	if configured.executeCalls != 1 {
		t.Fatalf("executor calls=%d, want 1", configured.executeCalls)
	}
	if configured.lastIntent.CommandID != intent.CommandID || string(configured.lastIntent.Payload) != string(intent.Payload) {
		t.Fatalf("executor intent=%#v, want command and payload from local API", configured.lastIntent)
	}
	if receipt.CommandID != intent.CommandID || receipt.RequestHash != "request-hash" || receipt.Phase != protocol.PhaseReceiptRecorded || receipt.Outcome != "accepted" {
		t.Fatalf("receipt=%#v, want delegated execution evidence", receipt)
	}
}
