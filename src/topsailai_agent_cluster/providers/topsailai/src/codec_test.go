package main

import (
	"encoding/json"
	"strings"
	"testing"
)

// TestDecodeRequestAdmitsTheTargetlessProjectAdd verifies the real process entry
// point accepts the one execute form that carries no target.
//
// This test exists because every other project.add test calls dispatch directly,
// which skips decodeRequest and therefore skips validateExecuteEnvelope. That gap
// let a target-less project.add be advertised, unit-tested and still refused by the
// binary: the envelope check ran first and rejected it before any handler could
// accept it. The test drives decodeRequest, which is the layer that refused, and it
// deliberately stops there so no business command runs.
func TestDecodeRequestAdmitsTheTargetlessProjectAdd(t *testing.T) {
	document := encodeRequest(t, projectAddRequest(`{"folder":"/work/alpha"}`))
	decoded, err := decodeRequest(document)
	if err != nil {
		t.Fatalf("decode project.add: %v", err)
	}
	if decoded.Target != nil {
		t.Fatalf("target = %+v, want nil", decoded.Target)
	}
	if decoded.Operation == nil || decoded.Operation.Name != operationProjectAdd {
		t.Fatalf("operation = %+v", decoded.Operation)
	}
}

// TestDecodeRequestStillRequiresATargetForEveryOtherExecute verifies the exception
// did not become a general relaxation.
//
// The operation is message.send, which genuinely addresses a live session, so a
// request without a target must still be refused at the envelope. Without this
// assertion the previous test would pass even if the target requirement had been
// deleted outright.
func TestDecodeRequestStillRequiresATargetForEveryOtherExecute(t *testing.T) {
	value := validRequest(functionExecute)
	value.InvocationID = "invocation-1"
	value.Operation = &namedContract{Name: operationMessageSend, Version: operationVersion}
	value.Target = nil
	value.Payload = json.RawMessage(`{"text":"hello"}`)

	_, err := decodeRequest(encodeRequest(t, value))
	if err == nil || !strings.Contains(err.Error(), "target is required for execute") {
		t.Fatalf("error = %v, want target is required for execute", err)
	}
}

// TestDecodeRequestRequiresAGenerationOnlyWhenATargetExists verifies the generation
// check cannot dereference an absent target.
//
// project.add carries no target, so a generation check that reads the target
// unconditionally would panic on the one request the contract permits. The
// assertion is that decoding succeeds rather than that a specific error appears,
// because a panic is the failure this guards against.
func TestDecodeRequestRequiresAGenerationOnlyWhenATargetExists(t *testing.T) {
	document := encodeRequest(t, projectAddRequest(`{"folder":"/work/alpha","name":"alpha"}`))
	if _, err := decodeRequest(document); err != nil {
		t.Fatalf("decode project.add with a name: %v", err)
	}
}
