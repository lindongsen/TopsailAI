package endpoint

import (
	"context"
	"testing"
	"time"

	"topsailai_agent_cluster/internal/adapter"
	"topsailai_agent_cluster/internal/protocol"
	endpointstorage "topsailai_agent_cluster/internal/storage/endpoint"
)

// endpointCommandAdapter records whether the Endpoint-native command path reached
// the adapter, so a test can prove the command was refused before any execution.
type endpointCommandAdapter struct {
	adapter.Adapter
	executed chan struct{}
}

func (a endpointCommandAdapter) Describe(context.Context) (adapter.Descriptor, error) {
	return adapter.Descriptor{
		AdapterID: "a1",
		Capabilities: protocol.CapabilityDescriptor{
			Revision:     "v1",
			Capabilities: []protocol.Capability{{Name: protocol.OperationCommandExec, Version: protocol.CommandExecPayloadVersion}},
		},
	}, nil
}

func (a endpointCommandAdapter) Execute(context.Context, adapter.ExecuteRequest) (adapter.ExecuteResult, error) {
	if a.executed != nil {
		close(a.executed)
	}
	return adapter.ExecuteResult{}, nil
}

// newEndpointCommandExecutor builds an executor with the given number of
// configured adapters, so the zero/one/several resolution rule can be exercised.
func newEndpointCommandExecutor(t *testing.T, adapters int) (*Executor, chan struct{}) {
	t.Helper()
	store, err := endpointstorage.Open(context.Background(), t.TempDir()+"/endpoint.db")
	if err != nil {
		t.Fatalf("open store: %v", err)
	}
	t.Cleanup(func() { _ = store.Close() })
	registry := adapter.NewRegistry()
	executed := make(chan struct{}, 1)
	if err := registry.RegisterType("fixture", func(context.Context, adapter.Config) (adapter.Adapter, error) {
		return endpointCommandAdapter{executed: executed}, nil
	}); err != nil {
		t.Fatalf("register type: %v", err)
	}
	for index := 0; index < adapters; index++ {
		id := "a1"
		if index > 0 {
			id = "a" + string(rune('1'+index))
		}
		if _, err := registry.Configure(context.Background(), adapter.Config{AdapterID: id, ProviderType: "fixture"}); err != nil {
			t.Fatalf("configure adapter %s: %v", id, err)
		}
	}
	executor, err := NewExecutor(store, registry)
	if err != nil {
		t.Fatalf("new executor: %v", err)
	}
	return executor, executed
}

// endpointCommandIntent builds a target-less command.exec intent, which is the
// form an endpoint-scope shell line produces.
func endpointCommandIntent(id string) protocol.ImmutableIntent {
	return protocol.ImmutableIntent{
		HashVersion:          "v1",
		CommandID:            id,
		EndpointID:           "e1",
		Operation:            protocol.OperationCommandExec,
		OperationVersion:     protocol.CommandExecPayloadVersion,
		CapabilityRevision:   "v1",
		PayloadSchemaVersion: "v1",
		Payload:              []byte(`{"argv":["echo","hello"]}`),
		ExecuteBeforeAtMS:    time.Now().Add(time.Minute).UnixMilli(),
		Budget:               protocol.Budget{WaitTimeoutMS: 1000},
	}
}

// TestEndpointCommandExecReachesTheAdapterWithNoTarget proves a target-less
// command.exec is admitted and executed instead of being refused as target_required.
//
// This is the whole point of the endpoint-scope form: the command addresses the
// machine, so there is no session target to require. A regression here makes the
// interactive form unreachable even though the client submits it correctly.
func TestEndpointCommandExecReachesTheAdapterWithNoTarget(t *testing.T) {
	executor, executed := newEndpointCommandExecutor(t, 1)
	receipt, err := executor.Execute(context.Background(), endpointCommandIntent("cmd-endpoint"), "hash")
	if err != nil {
		t.Fatalf("execute: %v", err)
	}
	if receipt.ErrorCode == "target_required" {
		t.Fatalf("receipt = %+v, want the command to be admitted", receipt)
	}
	select {
	case <-executed:
	case <-time.After(time.Second):
		t.Fatal("adapter was not called for a target-less command.exec")
	}
}

// TestEndpointCommandExecRequiresOneAdapter proves the capability cannot be
// attributed without exactly one configured adapter.
//
// The capability set is published per adapter, so the operation is validated
// against one adapter's descriptor. Zero adapters publish nothing, and several
// would make the choice depend on configuration order, so the same command could
// be validated against a different adapter after a restart.
func TestEndpointCommandExecRequiresOneAdapter(t *testing.T) {
	cases := []struct {
		name     string
		adapters int
		want     string
	}{
		{name: "no adapter", adapters: 0, want: "adapter_not_configured"},
		{name: "several adapters", adapters: 2, want: "target_ambiguous"},
	}
	for _, testCase := range cases {
		t.Run(testCase.name, func(t *testing.T) {
			executor, executed := newEndpointCommandExecutor(t, testCase.adapters)
			receipt, err := executor.Execute(context.Background(), endpointCommandIntent("cmd-"+testCase.want), "hash")
			if err != nil {
				t.Fatalf("execute: %v", err)
			}
			if receipt.ErrorCode != testCase.want {
				t.Fatalf("error code = %q, want %q", receipt.ErrorCode, testCase.want)
			}
			if receipt.EffectCertainty != protocol.EffectNotApplied {
				t.Fatalf("effect certainty = %q, want %q", receipt.EffectCertainty, protocol.EffectNotApplied)
			}
			select {
			case <-executed:
				t.Fatal("adapter was called although the capability could not be attributed")
			case <-time.After(50 * time.Millisecond):
			}
		})
	}
}

// TestTargetKeySeparatesEndpointCommands proves a target-less command.exec does
// not share the empty lock key with an unrelated target-less intent.
//
// An empty key would serialize every target-less command on one lock, which
// silently couples unrelated work and hides the coupling from review.
func TestTargetKeySeparatesEndpointCommands(t *testing.T) {
	command := targetKey(endpointCommandIntent("cmd-1"))
	if command == "" {
		t.Fatal("target key is empty for a target-less command.exec")
	}
	other := targetKey(protocol.ImmutableIntent{EndpointID: "e1", Operation: "agent.start", LaunchProfileID: "profile-1"})
	if command == other {
		t.Fatalf("target key %q is shared with an unrelated target-less intent", command)
	}
	if command != "e1:endpoint:command.exec" {
		t.Fatalf("target key = %q, want e1:endpoint:command.exec", command)
	}
}
