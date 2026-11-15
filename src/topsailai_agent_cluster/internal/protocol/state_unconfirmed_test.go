package protocol

import "testing"

// TestCanTransitionAllowsClaimedStatesToUnconfirmed proves the reconcile write is a legal
// transition from every state that was claimed for dispatch. A claimed command may have had
// its signal sent, so its effect can be unknown; refusing this edge would make the
// convergence update violate the state machine.
func TestCanTransitionAllowsClaimedStatesToUnconfirmed(t *testing.T) {
	for _, from := range []CommandStatus{StatusDispatched, StatusEndpointAdmitted, StatusExecuting} {
		if !CanTransition(from, StatusUnconfirmed) {
			t.Fatalf("%q -> unconfirmed must be allowed: the command was claimed for dispatch", from)
		}
		if err := ValidateTransition(from, StatusUnconfirmed); err != nil {
			t.Fatalf("ValidateTransition rejected the reconcile edge from %q: %v", from, err)
		}
	}
}

// TestCanTransitionRejectsUnclaimedAdmittedToUnconfirmed proves an admitted command cannot
// become unconfirmed. It was never claimed for dispatch, so no signal was sent and the effect
// is certainly not applied; reporting it as unknown would overstate the uncertainty.
func TestCanTransitionRejectsUnclaimedAdmittedToUnconfirmed(t *testing.T) {
	if CanTransition(StatusAdmitted, StatusUnconfirmed) {
		t.Fatal("admitted -> unconfirmed must be rejected: no signal was ever sent")
	}
}

// TestCanTransitionRejectsUnrelatedUnconfirmedEdges proves unconfirmed is terminal and cannot be
// reached from states that never delivered a signal.
func TestCanTransitionRejectsUnrelatedUnconfirmedEdges(t *testing.T) {
	for _, to := range []CommandStatus{StatusFinished, StatusFailed, StatusExecuting, StatusAdmitted} {
		if CanTransition(StatusUnconfirmed, to) {
			t.Fatalf("unconfirmed -> %q must be rejected: unconfirmed is terminal", to)
		}
	}
	if !CanTransition(StatusUnconfirmed, StatusUnconfirmed) {
		t.Fatal("identity transition must remain allowed")
	}
}
