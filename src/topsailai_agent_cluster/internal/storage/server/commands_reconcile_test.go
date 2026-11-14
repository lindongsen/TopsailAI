package serverstorage

import (
	"context"
	"path/filepath"
	"testing"

	"topsailai_agent_cluster/internal/protocol"
)

// seedEndpoint inserts the endpoint row that commands.endpoint_id references, so the fixture
// exercises the real foreign-key contract instead of bypassing it.
func seedEndpoint(t *testing.T, store *Store) {
	t.Helper()
	endpoint := protocol.Endpoint{
		EndpointID:         "endpoint-1",
		InstanceID:         "instance-1",
		DisplayName:        "reconcile-test",
		ConnectionState:    "online",
		ObservedAtMS:       1000,
		CapabilityRevision: "cap-1",
	}
	if err := store.UpsertEndpoint(context.Background(), endpoint, 1000); err != nil {
		t.Fatalf("seed endpoint: %v", err)
	}
}

// executingCommandFixture admits one command and drives it to the executing state through a
// real receipt, so the reconcile test exercises the same path that produced the ERR-12 symptom.
func executingCommandFixture(t *testing.T, store *Store, commandID string, deadlineAtMS int64) {
	t.Helper()
	ctx := context.Background()
	intent := protocol.ImmutableIntent{
		CommandID:         commandID,
		EndpointID:        "endpoint-1",
		Operation:         protocol.OperationAgentStop,
		OperationVersion:  "1",
		ExecuteBeforeAtMS: deadlineAtMS,
	}
	if err := store.AdmitCommand(ctx, intent, "hash-"+commandID, 1000); err != nil {
		t.Fatalf("admit command: %v", err)
	}
	receipt := protocol.ExecutionReceipt{
		CommandID:          commandID,
		RequestHash:        "hash-" + commandID,
		CommandRevision:    1,
		EndpointInstanceID: "instance-1",
		Phase:              protocol.PhaseInvocationStarted,
		DeliveryBoundary:   protocol.DeliverySignalSent,
		EffectCertainty:    protocol.EffectUnknown,
		Outcome:            "signal_sent",
		ExitConfirmed:      false,
	}
	if err := store.ApplyReceipt(ctx, receipt, 1100); err != nil {
		t.Fatalf("apply receipt: %v", err)
	}
	record, err := store.GetCommand(ctx, commandID)
	if err != nil {
		t.Fatalf("get command: %v", err)
	}
	if record.Status != protocol.StatusExecuting {
		t.Fatalf("fixture status=%q, want executing", record.Status)
	}
}

// TestReconcileExpiredCommandsConvergesExecutingPastDeadline proves the ERR-12 fix: a command whose
// signal was sent but whose exit was never confirmed becomes terminal once its deadline passed.
func TestReconcileExpiredCommandsConvergesExecutingPastDeadline(t *testing.T) {
	ctx := context.Background()
	store, err := Open(ctx, filepath.Join(t.TempDir(), "server.db"))
	if err != nil {
		t.Fatal(err)
	}
	defer store.Close()
	seedEndpoint(t, store)
	executingCommandFixture(t, store, "cmd-overdue", 5000)

	converged, err := store.ReconcileExpiredCommands(ctx, 6000)
	if err != nil {
		t.Fatalf("reconcile: %v", err)
	}
	if converged != 1 {
		t.Fatalf("converged=%d, want 1", converged)
	}
	record, err := store.GetCommand(ctx, "cmd-overdue")
	if err != nil {
		t.Fatal(err)
	}
	if record.Status != protocol.StatusUnconfirmed {
		t.Fatalf("status=%q, want unconfirmed", record.Status)
	}
	if record.EffectCertainty != protocol.EffectUnknown {
		t.Fatalf("effect_certainty=%q, want unknown: a sent signal must not be reported as not_applied", record.EffectCertainty)
	}

	// A second pass must be idempotent and must not rewrite the converged row.
	converged, err = store.ReconcileExpiredCommands(ctx, 7000)
	if err != nil {
		t.Fatalf("second reconcile: %v", err)
	}
	if converged != 0 {
		t.Fatalf("second reconcile converged=%d, want 0", converged)
	}
	again, err := store.GetCommand(ctx, "cmd-overdue")
	if err != nil {
		t.Fatal(err)
	}
	if again.Status != protocol.StatusUnconfirmed || again.EffectCertainty != protocol.EffectUnknown {
		t.Fatalf("second reconcile changed state to %q/%q", again.Status, again.EffectCertainty)
	}
}

// TestReconcileExpiredCommandsSkipsLiveAndDeadlineFreeCommands proves reconciliation is bounded by
// the immutable deadline and never touches rows that still have time or have no deadline at all.
func TestReconcileExpiredCommandsSkipsLiveAndDeadlineFreeCommands(t *testing.T) {
	ctx := context.Background()
	store, err := Open(ctx, filepath.Join(t.TempDir(), "server.db"))
	if err != nil {
		t.Fatal(err)
	}
	defer store.Close()
	seedEndpoint(t, store)
	executingCommandFixture(t, store, "cmd-future", 9000)
	executingCommandFixture(t, store, "cmd-no-deadline", 0)

	converged, err := store.ReconcileExpiredCommands(ctx, 6000)
	if err != nil {
		t.Fatalf("reconcile: %v", err)
	}
	if converged != 0 {
		t.Fatalf("converged=%d, want 0", converged)
	}
	for _, commandID := range []string{"cmd-future", "cmd-no-deadline"} {
		record, err := store.GetCommand(ctx, commandID)
		if err != nil {
			t.Fatal(err)
		}
		if record.Status != protocol.StatusExecuting {
			t.Fatalf("%s status=%q, want executing", commandID, record.Status)
		}
	}
}

// TestReconcileExpiredCommandsPreservesTerminalRowsAndExpiresAdmitted proves reconciliation
// cannot overwrite an authoritative terminal result, and that an admitted row past its deadline
// converges to expired rather than unconfirmed. An admitted command was never claimed for
// dispatch, so no signal was sent and the effect is certainly not applied.
func TestReconcileExpiredCommandsPreservesTerminalRowsAndExpiresAdmitted(t *testing.T) {
	ctx := context.Background()
	store, err := Open(ctx, filepath.Join(t.TempDir(), "server.db"))
	if err != nil {
		t.Fatal(err)
	}
	defer store.Close()
	seedEndpoint(t, store)

	// A finished command whose deadline has long passed must keep its confirmed result.
	finished := protocol.ImmutableIntent{
		CommandID:         "cmd-finished",
		EndpointID:        "endpoint-1",
		Operation:         protocol.OperationAgentStop,
		OperationVersion:  "1",
		ExecuteBeforeAtMS: 5000,
	}
	if err := store.AdmitCommand(ctx, finished, "hash-finished", 1000); err != nil {
		t.Fatal(err)
	}
	receipt := protocol.ExecutionReceipt{
		CommandID:          "cmd-finished",
		RequestHash:        "hash-finished",
		CommandRevision:    1,
		EndpointInstanceID: "instance-1",
		Phase:              protocol.PhaseReceiptRecorded,
		DeliveryBoundary:   protocol.DeliverySignalSent,
		EffectCertainty:    protocol.EffectAcknowledged,
		Outcome:            "stopped",
		ExitConfirmed:      true,
	}
	if err := store.ApplyReceipt(ctx, receipt, 1200); err != nil {
		t.Fatal(err)
	}

	// An admitted command past its deadline was never claimed for dispatch, so it converges to
	// expired. Leaving it admitted would keep it dispatchable forever, because DispatchCommand
	// only requires status = admitted.
	admitted := protocol.ImmutableIntent{
		CommandID:         "cmd-admitted",
		EndpointID:        "endpoint-1",
		Operation:         protocol.OperationAgentStop,
		OperationVersion:  "1",
		ExecuteBeforeAtMS: 5000,
	}
	if err := store.AdmitCommand(ctx, admitted, "hash-admitted", 1000); err != nil {
		t.Fatal(err)
	}

	converged, err := store.ReconcileExpiredCommands(ctx, 6000)
	if err != nil {
		t.Fatalf("reconcile: %v", err)
	}
	if converged != 1 {
		t.Fatalf("converged=%d, want 1: only the admitted row is overdue", converged)
	}
	finishedRecord, err := store.GetCommand(ctx, "cmd-finished")
	if err != nil {
		t.Fatal(err)
	}
	if finishedRecord.Status != protocol.StatusFinished {
		t.Fatalf("finished status=%q, want finished", finishedRecord.Status)
	}
	if finishedRecord.EffectCertainty != protocol.EffectAcknowledged {
		t.Fatalf("finished effect_certainty=%q, want applied", finishedRecord.EffectCertainty)
	}
	admittedRecord, err := store.GetCommand(ctx, "cmd-admitted")
	if err != nil {
		t.Fatal(err)
	}
	if admittedRecord.Status != protocol.StatusExpired {
		t.Fatalf("admitted status=%q, want expired", admittedRecord.Status)
	}
	if admittedRecord.EffectCertainty != protocol.EffectNotApplied {
		t.Fatalf("admitted effect_certainty=%q, want not_applied: no signal was ever sent", admittedRecord.EffectCertainty)
	}
}

// dispatchedCommandFixture admits one command and claims it for dispatch without any receipt,
// so the row stays dispatched. This is the state the live cluster was stuck in: the claim
// succeeded, the transport send was attempted, and no receipt ever came back.
func dispatchedCommandFixture(t *testing.T, store *Store, commandID string, deadlineAtMS int64) {
	t.Helper()
	ctx := context.Background()
	intent := protocol.ImmutableIntent{
		CommandID:         commandID,
		EndpointID:        "endpoint-1",
		Operation:         protocol.OperationAgentStop,
		OperationVersion:  "1",
		ExecuteBeforeAtMS: deadlineAtMS,
	}
	if err := store.AdmitCommand(ctx, intent, "hash-"+commandID, 1000); err != nil {
		t.Fatalf("admit command: %v", err)
	}
	claimed, err := store.DispatchCommand(ctx, commandID, 1050)
	if err != nil {
		t.Fatalf("dispatch command: %v", err)
	}
	if !claimed {
		t.Fatalf("dispatch command %q was not claimed", commandID)
	}
}

// endpointAdmittedCommandFixture drives a command to endpoint_admitted through a real receipt,
// so the fixture exercises the same path production uses instead of writing the status directly.
func endpointAdmittedCommandFixture(t *testing.T, store *Store, commandID string, deadlineAtMS int64) {
	t.Helper()
	ctx := context.Background()
	intent := protocol.ImmutableIntent{
		CommandID:         commandID,
		EndpointID:        "endpoint-1",
		Operation:         protocol.OperationAgentStop,
		OperationVersion:  "1",
		ExecuteBeforeAtMS: deadlineAtMS,
	}
	if err := store.AdmitCommand(ctx, intent, "hash-"+commandID, 1000); err != nil {
		t.Fatalf("admit command: %v", err)
	}
	if _, err := store.DispatchCommand(ctx, commandID, 1050); err != nil {
		t.Fatalf("dispatch command: %v", err)
	}
	receipt := protocol.ExecutionReceipt{
		CommandID:          commandID,
		RequestHash:        "hash-" + commandID,
		CommandRevision:    1,
		EndpointInstanceID: "instance-1",
		Phase:              protocol.PhaseInvocationStarted,
		DeliveryBoundary:   protocol.DeliveryNotStarted,
		EffectCertainty:    protocol.EffectUnknown,
		Outcome:            "endpoint_admitted",
		ExitConfirmed:      false,
	}
	if err := store.ApplyReceipt(ctx, receipt, 1100); err != nil {
		t.Fatalf("apply receipt: %v", err)
	}
	record, err := store.GetCommand(ctx, commandID)
	if err != nil {
		t.Fatalf("get command: %v", err)
	}
	if record.Status != protocol.StatusEndpointAdmitted {
		t.Fatalf("fixture status=%q, want endpoint_admitted", record.Status)
	}
}

// TestReconcileExpiredCommandsConvergesDispatchedPastDeadline proves the reported defect: a
// command that was claimed for dispatch but never received a receipt stays dispatched forever
// unless reconciliation converges it. Delivery may have happened, so the effect is unknown.
func TestReconcileExpiredCommandsConvergesDispatchedPastDeadline(t *testing.T) {
	ctx := context.Background()
	store, err := Open(ctx, filepath.Join(t.TempDir(), "server.db"))
	if err != nil {
		t.Fatal(err)
	}
	defer store.Close()
	seedEndpoint(t, store)
	dispatchedCommandFixture(t, store, "cmd-dispatched-overdue", 5000)

	converged, err := store.ReconcileExpiredCommands(ctx, 6000)
	if err != nil {
		t.Fatalf("reconcile: %v", err)
	}
	if converged != 1 {
		t.Fatalf("converged=%d, want 1", converged)
	}
	record, err := store.GetCommand(ctx, "cmd-dispatched-overdue")
	if err != nil {
		t.Fatal(err)
	}
	if record.Status != protocol.StatusUnconfirmed {
		t.Fatalf("status=%q, want unconfirmed", record.Status)
	}
	if record.EffectCertainty != protocol.EffectUnknown {
		t.Fatalf("effect_certainty=%q, want unknown: the signal may have been sent", record.EffectCertainty)
	}
}

// TestReconcileExpiredCommandsConvergesEndpointAdmittedPastDeadline proves the second
// unreachable status converges too. The Endpoint acknowledged the command, so delivery
// definitely happened and the effect must be unknown rather than not_applied.
func TestReconcileExpiredCommandsConvergesEndpointAdmittedPastDeadline(t *testing.T) {
	ctx := context.Background()
	store, err := Open(ctx, filepath.Join(t.TempDir(), "server.db"))
	if err != nil {
		t.Fatal(err)
	}
	defer store.Close()
	seedEndpoint(t, store)
	endpointAdmittedCommandFixture(t, store, "cmd-endpoint-admitted-overdue", 5000)

	converged, err := store.ReconcileExpiredCommands(ctx, 6000)
	if err != nil {
		t.Fatalf("reconcile: %v", err)
	}
	if converged != 1 {
		t.Fatalf("converged=%d, want 1", converged)
	}
	record, err := store.GetCommand(ctx, "cmd-endpoint-admitted-overdue")
	if err != nil {
		t.Fatal(err)
	}
	if record.Status != protocol.StatusUnconfirmed {
		t.Fatalf("status=%q, want unconfirmed", record.Status)
	}
	if record.EffectCertainty != protocol.EffectUnknown {
		t.Fatalf("effect_certainty=%q, want unknown: the Endpoint acknowledged the command", record.EffectCertainty)
	}
}

// TestReconcileExpiredCommandsSkipsDispatchedInsideDeadline proves convergence is bounded by the
// immutable deadline. A command still inside its window is live work and must not be converged,
// which is what keeps a fresh in-flight dispatch on a healthy Endpoint untouched.
func TestReconcileExpiredCommandsSkipsDispatchedInsideDeadline(t *testing.T) {
	ctx := context.Background()
	store, err := Open(ctx, filepath.Join(t.TempDir(), "server.db"))
	if err != nil {
		t.Fatal(err)
	}
	defer store.Close()
	seedEndpoint(t, store)
	dispatchedCommandFixture(t, store, "cmd-dispatched-live", 9000)

	converged, err := store.ReconcileExpiredCommands(ctx, 6000)
	if err != nil {
		t.Fatalf("reconcile: %v", err)
	}
	if converged != 0 {
		t.Fatalf("converged=%d, want 0", converged)
	}
	record, err := store.GetCommand(ctx, "cmd-dispatched-live")
	if err != nil {
		t.Fatal(err)
	}
	if record.Status != protocol.StatusDispatched {
		t.Fatalf("status=%q, want dispatched", record.Status)
	}
}
