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

// deadlineFixtureAdapter records whether the provider was reached, so a test can
// prove that a reported certainty matches what actually happened.
type deadlineFixtureAdapter struct {
	adapter.Adapter
	executions int
}

func (a *deadlineFixtureAdapter) Describe(context.Context) (adapter.Descriptor, error) {
	return adapter.Descriptor{AdapterID: "a1", Capabilities: protocol.CapabilityDescriptor{Revision: "v1", Capabilities: []protocol.Capability{
		{Name: protocol.OperationAgentStart, Version: "v1"},
	}}}, nil
}

func (a *deadlineFixtureAdapter) Inspect(context.Context, adapter.InspectRequest) (adapter.InspectResult, error) {
	return adapter.InspectResult{Found: true, ProviderGeneration: "g1"}, nil
}

func (a *deadlineFixtureAdapter) Execute(_ context.Context, request adapter.ExecuteRequest) (adapter.ExecuteResult, error) {
	a.executions++
	return adapter.ExecuteResult{Receipt: protocol.ExecutionReceipt{
		CommandID:        request.Intent.CommandID,
		Outcome:          "succeeded",
		DeliveryBoundary: protocol.DeliverySubmitted,
		EffectCertainty:  protocol.EffectAcknowledged,
	}}, nil
}

// newDeadlineExecutor builds an executor whose single fixture adapter counts
// executions, so "the provider was never reached" is measured rather than assumed.
func newDeadlineExecutor(t *testing.T) (*Executor, *endpointstorage.Store, *deadlineFixtureAdapter) {
	t.Helper()
	store, err := endpointstorage.Open(context.Background(), t.TempDir()+"/endpoint.db")
	if err != nil {
		t.Fatalf("open endpoint store: %v", err)
	}
	t.Cleanup(func() { _ = store.Close() })
	fixture := &deadlineFixtureAdapter{}
	registry := adapter.NewRegistry()
	if err := registry.RegisterType("fixture", func(context.Context, adapter.Config) (adapter.Adapter, error) {
		return fixture, nil
	}); err != nil {
		t.Fatalf("register fixture adapter: %v", err)
	}
	if _, err := registry.Configure(context.Background(), adapter.Config{AdapterID: "a1", ProviderType: "fixture"}); err != nil {
		t.Fatalf("configure fixture adapter: %v", err)
	}
	executor, err := NewExecutor(store, registry)
	if err != nil {
		t.Fatalf("build executor: %v", err)
	}
	return executor, store, fixture
}

// deadlineIntent builds a launch-profile intent whose only varying field is the
// immutable execution deadline.
func deadlineIntent(commandID string, deadlineAtMS int64) protocol.ImmutableIntent {
	return protocol.ImmutableIntent{
		HashVersion:          "v1",
		CommandID:            commandID,
		EndpointID:           "e1",
		Operation:            protocol.OperationAgentStart,
		OperationVersion:     "v1",
		CapabilityRevision:   "v1",
		PayloadSchemaVersion: "v1",
		LaunchProfileID:      "a1",
		ProfileRevision:      "v1",
		Payload:              []byte(`{}`),
		ExecuteBeforeAtMS:    deadlineAtMS,
	}
}

// TestExpiredDeadlineReportsCertainNotAppliedEffect proves that every deadline
// value which provably prevents the provider call reports a certain, unapplied
// effect instead of an unknown one.
//
// The assertion covers both the error code and the effect certainty because the
// error code alone cannot distinguish the cases: the zero and past deadlines both
// return a receipt with no error, so the certainty is the only observable
// difference. Asserting only the code would have let the defect survive.
func TestExpiredDeadlineReportsCertainNotAppliedEffect(t *testing.T) {
	cases := []struct {
		name     string
		deadline int64
		wantCode string
	}{
		{name: "zero deadline", deadline: 0, wantCode: "expired_after_validation"},
		{name: "deadline already passed", deadline: time.Now().Add(-time.Hour).UnixMilli(), wantCode: "expired_before_execution"},
	}
	for _, testCase := range cases {
		t.Run(testCase.name, func(t *testing.T) {
			executor, store, fixture := newDeadlineExecutor(t)
			intent := deadlineIntent("expired-"+testCase.wantCode, testCase.deadline)
			receipt, err := executor.Execute(context.Background(), intent, "hash")
			if err != nil {
				t.Fatalf("an expired deadline is a decision, not an infrastructure failure: %v", err)
			}
			if fixture.executions != 0 {
				t.Fatalf("the provider was reached %d times, so the reported certainty cannot be trusted", fixture.executions)
			}
			if receipt.ErrorCode != testCase.wantCode {
				t.Fatalf("error code=%q, want %q", receipt.ErrorCode, testCase.wantCode)
			}
			if receipt.EffectCertainty != protocol.EffectNotApplied {
				t.Fatalf("effect certainty=%q, want %q: the provider was never called, so the effect is certain", receipt.EffectCertainty, protocol.EffectNotApplied)
			}
			if receipt.Outcome != "expired" {
				t.Fatalf("outcome=%q, want expired", receipt.Outcome)
			}
			assertDurableExpiry(t, store, intent.CommandID, testCase.wantCode)
		})
	}
}

// assertDurableExpiry proves the expiry is written to the journal, not merely
// returned to the caller.
//
// A receipt that is only returned leaves the journal at endpoint_admitted, and a
// replay then re-derives the outcome from that phase and reports
// invocation_recovery_unknown. That code claims the provider might have run, which
// is false, and it also reports an unknown effect, so the command would be parked
// as executing on the Server with no deadline left to converge it.
func assertDurableExpiry(t *testing.T, store *endpointstorage.Store, commandID, wantCode string) {
	t.Helper()
	entry, err := store.GetJournal(context.Background(), commandID)
	if err != nil {
		t.Fatalf("the expiry must be durable, otherwise a replay re-derives it from the journal phase: %v", err)
	}
	if entry.Phase != protocol.PhaseReceiptRecorded {
		t.Fatalf("journal phase=%q, want %q: a returned-only receipt leaves the command replayable as unknown", entry.Phase, protocol.PhaseReceiptRecorded)
	}
	var stored protocol.ExecutionReceipt
	if err := json.Unmarshal([]byte(entry.ReceiptJSON), &stored); err != nil {
		t.Fatalf("decode stored receipt: %v", err)
	}
	if stored.ErrorCode != wantCode {
		t.Fatalf("stored error code=%q, want %q", stored.ErrorCode, wantCode)
	}
	if stored.EffectCertainty != protocol.EffectNotApplied {
		t.Fatalf("stored effect certainty=%q, want %q", stored.EffectCertainty, protocol.EffectNotApplied)
	}
}

// TestReplayedExpiredDeadlineKeepsTheCertainOutcome proves a replay of an expired
// command reports the same terminal outcome instead of falling back to the
// invocation-recovery path.
//
// The Server re-sends a command whenever a receipt is lost, so the replay path is
// reachable in production and must not contradict the first answer.
func TestReplayedExpiredDeadlineKeepsTheCertainOutcome(t *testing.T) {
	executor, _, fixture := newDeadlineExecutor(t)
	intent := deadlineIntent("replayed-zero-deadline", 0)
	first, err := executor.Execute(context.Background(), intent, "hash")
	if err != nil {
		t.Fatalf("first execution: %v", err)
	}
	replay, err := executor.Execute(context.Background(), intent, "hash")
	if err != nil {
		t.Fatalf("replay: %v", err)
	}
	if fixture.executions != 0 {
		t.Fatalf("the provider was reached %d times, so a replay must not execute either", fixture.executions)
	}
	if replay.ErrorCode != first.ErrorCode {
		t.Fatalf("replay error code=%q, want %q: a replay must not invent a different reason", replay.ErrorCode, first.ErrorCode)
	}
	if replay.EffectCertainty != protocol.EffectNotApplied {
		t.Fatalf("replay effect certainty=%q, want %q: invocation_recovery_unknown claims the provider might have run", replay.EffectCertainty, protocol.EffectNotApplied)
	}
	if replay.Outcome != "expired" {
		t.Fatalf("replay outcome=%q, want expired", replay.Outcome)
	}
}

// TestLiveDeadlineStillReachesTheProvider is the positive control for the two
// tests above. Without it, deleting the deadline check entirely would satisfy
// every expired-deadline assertion while silently removing the time bound.
func TestLiveDeadlineStillReachesTheProvider(t *testing.T) {
	executor, _, fixture := newDeadlineExecutor(t)
	intent := deadlineIntent("live-deadline", time.Now().Add(time.Hour).UnixMilli())
	receipt, err := executor.Execute(context.Background(), intent, "hash")
	if err != nil {
		t.Fatalf("a live deadline must execute: %v", err)
	}
	if fixture.executions != 1 {
		t.Fatalf("provider executions=%d, want 1: a future deadline must not be treated as expired", fixture.executions)
	}
	if receipt.EffectCertainty != protocol.EffectAcknowledged {
		t.Fatalf("effect certainty=%q, want %q", receipt.EffectCertainty, protocol.EffectAcknowledged)
	}
	if receipt.ErrorCode != "" {
		t.Fatalf("error code=%q, want empty for a successful execution", receipt.ErrorCode)
	}
}
