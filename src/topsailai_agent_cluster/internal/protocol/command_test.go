package protocol

import (
	"testing"
)

func TestCanonicalHashAndConflictInputs(t *testing.T) {
	intent := ImmutableIntent{HashVersion: "v1", CommandID: "c1", IssuerID: "u1", Scope: "send", EndpointID: "e1", Target: &CommandTarget{Kind: "session", ResourceID: "s1", Generation: "g1"}, Operation: "message.send", OperationVersion: "v1", CapabilityRevision: "cap1", PayloadSchemaVersion: "v1", Payload: []byte(`{"text":"hello"}`), ExecuteBeforeAtMS: 100}
	first, err := CanonicalHash(intent)
	if err != nil {
		t.Fatal(err)
	}
	intent.Payload = []byte(`{"text":"changed"}`)
	second, err := CanonicalHash(intent)
	if err != nil {
		t.Fatal(err)
	}
	if first == second {
		t.Fatal("different intent payloads have the same hash")
	}
	intent.Payload = []byte(`{"text":`)
	if _, err := CanonicalHash(intent); err == nil {
		t.Fatal("invalid payload was accepted")
	}
}

func TestCommandTransitionsAndCancellation(t *testing.T) {
	if err := ValidateTransition(StatusAdmitted, StatusDispatched); err != nil {
		t.Fatal(err)
	}
	if err := ValidateTransition(StatusAdmitted, StatusExecuting); err == nil {
		t.Fatal("invalid transition accepted")
	}
	if !CanCancel(StatusAdmitted) || CanCancel(StatusDispatched) {
		t.Fatal("unexpected cancellation boundary")
	}
}
