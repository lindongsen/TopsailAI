package endpoint

import (
	"context"
	"encoding/json"
	"testing"
	"time"

	"topsailai_agent_cluster/internal/adapter"
	"topsailai_agent_cluster/internal/protocol"
	endpointstorage "topsailai_agent_cluster/internal/storage/endpoint"
)

type modelSetAdapter struct {
	adapter.Adapter
	id    string
	calls *int
}

func (a modelSetAdapter) Describe(context.Context) (adapter.Descriptor, error) {
	return adapter.Descriptor{AdapterID: a.id, Capabilities: protocol.CapabilityDescriptor{Revision: "v1", Capabilities: []protocol.Capability{{Name: protocol.OperationAgentModelSet, Version: protocol.ModelSetPayloadVersion}}}}, nil
}
func (a modelSetAdapter) Execute(_ context.Context, request adapter.ExecuteRequest) (adapter.ExecuteResult, error) {
	*a.calls++
	return adapter.ExecuteResult{Receipt: protocol.ExecutionReceipt{Outcome: "set", EffectCertainty: protocol.EffectAcknowledged, DeliveryBoundary: protocol.DeliverySubmitted}}, nil
}

func modelSetExecutor(t *testing.T, ids ...string) (*Executor, *endpointstorage.Store, map[string]*int) {
	t.Helper()
	store, err := endpointstorage.Open(context.Background(), t.TempDir()+"/endpoint.db")
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = store.Close() })
	registry := adapter.NewRegistry()
	calls := make(map[string]*int)
	for _, id := range ids {
		id := id
		count := new(int)
		calls[id] = count
		kind := "fixture-" + id
		if err := registry.RegisterType(kind, func(context.Context, adapter.Config) (adapter.Adapter, error) {
			return modelSetAdapter{id: id, calls: count}, nil
		}); err != nil {
			t.Fatal(err)
		}
		if _, err := registry.Configure(context.Background(), adapter.Config{AdapterID: id, ProviderType: kind}); err != nil {
			t.Fatal(err)
		}
	}
	executor, err := NewExecutor(store, registry)
	if err != nil {
		t.Fatal(err)
	}
	return executor, store, calls
}

func modelSetIntent(id, profileID string) protocol.ImmutableIntent {
	payload, _ := json.Marshal(protocol.ModelSetPayload{ModelProfileID: profileID})
	return protocol.ImmutableIntent{HashVersion: "v1", CommandID: id, EndpointID: "e1", Operation: protocol.OperationAgentModelSet, OperationVersion: protocol.ModelSetPayloadVersion, PayloadSchemaVersion: protocol.ModelSetPayloadVersion, CapabilityRevision: "v1", Payload: payload, ExecuteBeforeAtMS: time.Now().Add(time.Minute).UnixMilli()}
}

func TestModelSetRoutesByOpaqueProfileMappingWithSeveralAdapters(t *testing.T) {
	executor, store, calls := modelSetExecutor(t, "a1", "a2")
	mapping, err := store.GetOrCreateResourceID(context.Background(), "a2", protocol.ResourceModelProfile, "provider-model", 1)
	if err != nil {
		t.Fatal(err)
	}
	receipt, err := executor.Execute(context.Background(), modelSetIntent("set-model", mapping.ResourceID), "hash")
	if err != nil {
		t.Fatalf("execute: %v", err)
	}
	if receipt.Outcome != "set" || *calls["a1"] != 0 || *calls["a2"] != 1 {
		t.Fatalf("receipt=%+v calls a1=%d a2=%d", receipt, *calls["a1"], *calls["a2"])
	}
}

func TestModelSetRejectsUnknownAndWrongKindProfiles(t *testing.T) {
	tests := []struct {
		name, profile string
		seedKind      string
	}{
		{name: "unknown", profile: "res_missing"},
		{name: "wrong kind", seedKind: protocol.ResourceSession},
	}
	for _, test := range tests {
		t.Run(test.name, func(t *testing.T) {
			executor, store, calls := modelSetExecutor(t, "a1")
			profile := test.profile
			if test.seedKind != "" {
				mapping, err := store.GetOrCreateResourceID(context.Background(), "a1", test.seedKind, "provider", 1)
				if err != nil {
					t.Fatal(err)
				}
				profile = mapping.ResourceID
			}
			receipt, err := executor.Execute(context.Background(), modelSetIntent("reject-"+test.name, profile), "hash")
			if err != nil {
				t.Fatalf("execute: %v", err)
			}
			if receipt.ErrorCode != protocol.ModelSetUnknownProfile || *calls["a1"] != 0 {
				t.Fatalf("receipt=%+v calls=%d", receipt, *calls["a1"])
			}
		})
	}
}

func TestTargetKeySerializesModelSetPerEndpoint(t *testing.T) {
	key := targetKey(modelSetIntent("set", "profile"))
	if key != "e1:endpoint:agent.model.set" {
		t.Fatalf("target key=%q", key)
	}
}
