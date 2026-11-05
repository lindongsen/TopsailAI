package protocol

import "testing"

// TestCanTransitionAllowsExecutingToUnconfirmed proves the reconcile write is a legal transition:
// without this edge the convergence update would violate the state machine.
func TestCanTransitionAllowsExecutingToUnconfirmed(t *testing.T) {
	if !CanTransition(StatusExecuting, StatusUnconfirmed) {
		t.Fatal("executing -> unconfirmed must be allowed")
	}
	if err := ValidateTransition(StatusExecuting, StatusUnconfirmed); err != nil {
		t.Fatalf("ValidateTransition rejected the reconcile edge: %v", err)
	}
}

// TestCanTransitionRejectsUnrelatedUnconfirmedEdges proves unconfirmed is terminal and cannot be
// reached from states that never delivered a signal.
func TestCanTransitionRejectsUnrelatedUnconfirmedEdges(t *testing.T) {
	for _, from := range []CommandStatus{StatusAdmitted, StatusDispatched, StatusEndpointAdmitted} {
		if CanTransition(from, StatusUnconfirmed) {
			t.Fatalf("%q -> unconfirmed must be rejected", from)
		}
	}
	for _, to := range []CommandStatus{StatusFinished, StatusFailed, StatusExecuting, StatusAdmitted} {
		if CanTransition(StatusUnconfirmed, to) {
			t.Fatalf("unconfirmed -> %q must be rejected: unconfirmed is terminal", to)
		}
	}
	if !CanTransition(StatusUnconfirmed, StatusUnconfirmed) {
		t.Fatal("identity transition must remain allowed")
	}
}
