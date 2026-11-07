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

// policyTestAdapter records whether the adapter was invoked, so a policy
// rejection can be proven to happen before any provider call.
type policyTestAdapter struct {
	adapter.Adapter
	called chan struct{}
}

func (a policyTestAdapter) Describe(context.Context) (adapter.Descriptor, error) {
	return adapter.Descriptor{AdapterID: "a1", Capabilities: protocol.CapabilityDescriptor{Revision: "v1", Capabilities: []protocol.Capability{{Name: protocol.OperationCommandExec, Version: "v1"}}}}, nil
}

func (a policyTestAdapter) Inspect(context.Context, adapter.InspectRequest) (adapter.InspectResult, error) {
	return adapter.InspectResult{Found: true, Generation: "g1"}, nil
}

func (a policyTestAdapter) Execute(context.Context, adapter.ExecuteRequest) (adapter.ExecuteResult, error) {
	close(a.called)
	return adapter.ExecuteResult{}, nil
}

// newPolicyTestExecutor builds an executor whose only adapter supports
// command.exec, so the policy seam is the only thing that can reject the intent.
// It also registers a durable session mapping, because command.exec targets a
// session and that target is what resolves the working directory.
func newPolicyTestExecutor(t *testing.T) (*Executor, *endpointstorage.Store, chan struct{}, string) {
	t.Helper()
	store, err := endpointstorage.Open(context.Background(), t.TempDir()+"/endpoint.db")
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = store.Close() })
	registry := adapter.NewRegistry()
	called := make(chan struct{})
	if err := registry.RegisterType("fixture", func(context.Context, adapter.Config) (adapter.Adapter, error) {
		return policyTestAdapter{called: called}, nil
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
	return executor, store, called, mapping.ResourceID
}

func commandExecIntent(commandID, resourceID string) protocol.ImmutableIntent {
	return protocol.ImmutableIntent{
		HashVersion:          "v1",
		CommandID:            commandID,
		EndpointID:           "e1",
		Operation:            protocol.OperationCommandExec,
		Target:               &protocol.CommandTarget{Kind: "session", ResourceID: resourceID, Generation: "g1"},
		OperationVersion:     "v1",
		CapabilityRevision:   "v1",
		PayloadSchemaVersion: protocol.CommandExecPayloadVersion,
		Payload:              []byte(`{"argv":["git","status"]}`),
		ExecuteBeforeAtMS:    time.Now().Add(time.Minute).UnixMilli(),
	}
}

// TestPolicyHookRejectionIsRecordedAsNotApplied proves a denied command is
// recorded as a terminal not_applied rejection rather than a false unknown.
// Recording the rejection after MarkInvocationStarted would make a retry look
// like a crash mid-invocation and report unknown effects for a command that was
// never applied.
func TestPolicyHookRejectionIsRecordedAsNotApplied(t *testing.T) {
	executor, store, called, resourceID := newPolicyTestExecutor(t)
	executor.PolicyHook = func(context.Context, protocol.ImmutableIntent) error {
		return errors.New("command is not allowed")
	}
	intent := commandExecIntent("policy-denied", resourceID)
	receipt, err := executor.Execute(context.Background(), intent, "policy-hash")
	if err != nil {
		t.Fatal(err)
	}
	if receipt.Phase != protocol.PhaseReceiptRecorded {
		t.Fatalf("phase=%q", receipt.Phase)
	}
	if receipt.EffectCertainty != protocol.EffectNotApplied {
		t.Fatalf("effect certainty=%q, want not_applied", receipt.EffectCertainty)
	}
	if receipt.ErrorCode != "policy_denied" {
		t.Fatalf("error code=%q", receipt.ErrorCode)
	}
	select {
	case <-called:
		t.Fatal("adapter was invoked despite policy rejection")
	default:
	}
	entry, err := store.GetJournal(context.Background(), intent.CommandID)
	if err != nil {
		t.Fatal(err)
	}
	if entry.Phase != protocol.PhaseReceiptRecorded {
		t.Fatalf("journal phase=%q, want receipt_recorded", entry.Phase)
	}
}

// TestPolicyHookRejectionReplayStaysNotApplied proves a replay of a denied
// command returns the same terminal rejection instead of an unknown outcome.
func TestPolicyHookRejectionReplayStaysNotApplied(t *testing.T) {
	executor, _, _, resourceID := newPolicyTestExecutor(t)
	executor.PolicyHook = func(context.Context, protocol.ImmutableIntent) error {
		return errors.New("command is not allowed")
	}
	intent := commandExecIntent("policy-replay", resourceID)
	first, err := executor.Execute(context.Background(), intent, "policy-hash")
	if err != nil {
		t.Fatal(err)
	}
	second, err := executor.Execute(context.Background(), intent, "policy-hash")
	if err != nil {
		t.Fatal(err)
	}
	if second.ErrorCode != first.ErrorCode || second.EffectCertainty != protocol.EffectNotApplied {
		t.Fatalf("replay receipt=%#v", second)
	}
}

// TestPolicyHookAllowsPermittedCommand proves the seam does not block an
// allowed command, so the allowlist is a filter rather than a blanket denial.
func TestPolicyHookAllowsPermittedCommand(t *testing.T) {
	executor, _, called, resourceID := newPolicyTestExecutor(t)
	executor.PolicyHook = func(context.Context, protocol.ImmutableIntent) error {
		return nil
	}
	intent := commandExecIntent("policy-allowed", resourceID)
	if _, err := executor.Execute(context.Background(), intent, "policy-hash"); err != nil {
		t.Fatal(err)
	}
	select {
	case <-called:
	case <-time.After(time.Second):
		t.Fatal("adapter was not invoked for a permitted command")
	}
}

// TestPolicyHookRunsBeforeInvocationRecorded proves the policy seam runs before
// the journal records an invocation, which is what keeps a rejection
// distinguishable from a crash mid-invocation.
func TestPolicyHookRunsBeforeInvocationRecorded(t *testing.T) {
	executor, store, _, resourceID := newPolicyTestExecutor(t)
	var observedPhase protocol.CommandPhase
	executor.PolicyHook = func(ctx context.Context, intent protocol.ImmutableIntent) error {
		entry, err := store.GetJournal(ctx, intent.CommandID)
		if err != nil {
			return err
		}
		observedPhase = entry.Phase
		return errors.New("stop after observing phase")
	}
	intent := commandExecIntent("policy-phase", resourceID)
	if _, err := executor.Execute(context.Background(), intent, "policy-hash"); err != nil {
		t.Fatal(err)
	}
	if observedPhase == protocol.PhaseInvocationStarted || observedPhase == protocol.PhaseEndpointAdmitted {
		t.Fatalf("policy ran after invocation was recorded: phase=%q", observedPhase)
	}
}
