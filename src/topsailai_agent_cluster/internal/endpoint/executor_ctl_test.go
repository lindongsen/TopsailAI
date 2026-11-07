package endpoint

import (
	"context"
	"testing"
	"time"

	"topsailai_agent_cluster/internal/adapter"
	"topsailai_agent_cluster/internal/protocol"
	"topsailai_agent_cluster/internal/security"
	endpointstorage "topsailai_agent_cluster/internal/storage/endpoint"
)

// ctlTestAdapter advertises a fixed capability set, so a test can prove that
// admission follows the descriptor the adapter actually published rather than a
// hardcoded operation list inside the executor.
type ctlTestAdapter struct {
	adapter.Adapter
	capabilities []protocol.Capability
	called       chan struct{}
}

func (a ctlTestAdapter) Describe(context.Context) (adapter.Descriptor, error) {
	return adapter.Descriptor{
		AdapterID:    "a1",
		Capabilities: protocol.CapabilityDescriptor{Revision: "v1", Capabilities: a.capabilities},
	}, nil
}

func (a ctlTestAdapter) Inspect(context.Context, adapter.InspectRequest) (adapter.InspectResult, error) {
	return adapter.InspectResult{Found: true, Generation: "g1"}, nil
}

func (a ctlTestAdapter) Execute(context.Context, adapter.ExecuteRequest) (adapter.ExecuteResult, error) {
	close(a.called)
	return adapter.ExecuteResult{Receipt: protocol.ExecutionReceipt{Outcome: "submitted"}}, nil
}

// newCtlTestExecutor builds an executor whose adapter advertises exactly the
// supplied capabilities, plus a durable session mapping so a ctl. intent can
// resolve its target adapter.
func newCtlTestExecutor(t *testing.T, capabilities []protocol.Capability) (*Executor, chan struct{}, string) {
	t.Helper()
	store, err := endpointstorage.Open(context.Background(), t.TempDir()+"/endpoint.db")
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = store.Close() })
	registry := adapter.NewRegistry()
	called := make(chan struct{})
	if err := registry.RegisterType("fixture", func(context.Context, adapter.Config) (adapter.Adapter, error) {
		return ctlTestAdapter{capabilities: capabilities, called: called}, nil
	}); err != nil {
		t.Fatal(err)
	}
	if _, err := registry.Configure(context.Background(), adapter.Config{AdapterID: "a1", ProviderType: "fixture"}); err != nil {
		t.Fatal(err)
	}
	mapping, err := store.GetOrCreateResourceID(context.Background(), "a1", "session-key", time.Now().UnixMilli())
	if err != nil {
		t.Fatal(err)
	}
	executor, err := NewExecutor(store, registry)
	if err != nil {
		t.Fatal(err)
	}
	return executor, called, mapping.ResourceID
}

// ctlIntent builds a session-targeted ctl. intent for one provider action.
func ctlIntent(commandID, operation, resourceID string) protocol.ImmutableIntent {
	return protocol.ImmutableIntent{
		HashVersion:          "v1",
		CommandID:            commandID,
		EndpointID:           "e1",
		Operation:            operation,
		Target:               &protocol.CommandTarget{Kind: "session", ResourceID: resourceID, Generation: "g1"},
		OperationVersion:     "v1",
		CapabilityRevision:   "v1",
		PayloadSchemaVersion: "v1",
		Payload:              []byte(`{}`),
		ExecuteBeforeAtMS:    time.Now().Add(time.Minute).UnixMilli(),
	}
}

// TestExecutorAdmitsAdvertisedControlAction proves a ctl. operation the adapter
// advertised reaches the adapter. This closes the loop between Describe and
// admission: the executor must not reject the ctl. family merely because the
// operation name is not one of the built-in constants.
func TestExecutorAdmitsAdvertisedControlAction(t *testing.T) {
	operation := security.ProviderControlPrefix + "heartbeat"
	executor, called, resourceID := newCtlTestExecutor(t, []protocol.Capability{{
		Name:               operation,
		Version:            "v1",
		TargetKinds:        []string{"session"},
		SafetyClass:        "mutating",
		RequiredPermission: security.ScopeControl,
	}})
	intent := ctlIntent("ctl-admitted", operation, resourceID)
	receipt, err := executor.Execute(context.Background(), intent, "ctl-hash")
	if err != nil {
		t.Fatal(err)
	}
	if receipt.ErrorCode == "unsupported" {
		t.Fatalf("advertised ctl operation was rejected as unsupported: %#v", receipt)
	}
	select {
	case <-called:
	case <-time.After(time.Second):
		t.Fatal("adapter was not invoked for an advertised ctl operation")
	}
}

// TestExecutorRejectsUnadvertisedControlAction proves an action the adapter did
// not advertise is rejected as unsupported before any provider call. Without
// this, a ctl. name would be reachable simply by being spelled correctly.
func TestExecutorRejectsUnadvertisedControlAction(t *testing.T) {
	executor, called, resourceID := newCtlTestExecutor(t, []protocol.Capability{{
		Name:               security.ProviderControlPrefix + "heartbeat",
		Version:            "v1",
		TargetKinds:        []string{"session"},
		SafetyClass:        "mutating",
		RequiredPermission: security.ScopeControl,
	}})
	intent := ctlIntent("ctl-unadvertised", security.ProviderControlPrefix+"get_session_messages", resourceID)
	receipt, err := executor.Execute(context.Background(), intent, "ctl-hash")
	if err != nil {
		t.Fatal(err)
	}
	if receipt.ErrorCode != "unsupported" {
		t.Fatalf("error code=%q, want unsupported", receipt.ErrorCode)
	}
	if receipt.EffectCertainty != protocol.EffectNotApplied {
		t.Fatalf("effect certainty=%q, want not_applied", receipt.EffectCertainty)
	}
	select {
	case <-called:
		t.Fatal("adapter was invoked for an unadvertised ctl operation")
	default:
	}
}

// TestExecutorRejectsControlActionVersionMismatch proves admission matches the
// advertised version, so a capability revision change cannot be bypassed by
// naming the same action with a different version.
func TestExecutorRejectsControlActionVersionMismatch(t *testing.T) {
	operation := security.ProviderControlPrefix + "pause"
	executor, called, resourceID := newCtlTestExecutor(t, []protocol.Capability{{
		Name:               operation,
		Version:            "v1",
		TargetKinds:        []string{"session"},
		SafetyClass:        "mutating",
		RequiredPermission: security.ScopeControl,
	}})
	intent := ctlIntent("ctl-version", operation, resourceID)
	intent.OperationVersion = "v2"
	receipt, err := executor.Execute(context.Background(), intent, "ctl-hash")
	if err != nil {
		t.Fatal(err)
	}
	if receipt.ErrorCode != "unsupported" {
		t.Fatalf("error code=%q, want unsupported", receipt.ErrorCode)
	}
	select {
	case <-called:
		t.Fatal("adapter was invoked despite a version mismatch")
	default:
	}
}
