package main

import (
	"encoding/json"
	"testing"
)

// wantOperations is the complete operation surface the mock must advertise and
// answer. It is written out literally rather than derived from the evidence
// table, because a test that reads the same table it verifies cannot detect a
// missing entry.
var wantOperations = []string{
	"agent.drive.start",
	"agent.drive.stop",
	"agent.model.select",
	"agent.resume",
	"agent.start",
	"agent.stop",
	"command.exec",
	"context.inject",
	"execution.interrupt",
	"message.send",
	"workspace.clean",
}

// TestDescriptorAdvertisesEveryOperation proves the advertised surface is the
// full eleven-operation set, so a scenario that drives one of them cannot fail
// with "unsupported" merely because the mock forgot to advertise it.
func TestDescriptorAdvertisesEveryOperation(t *testing.T) {
	descriptor := mockDescriptor("")
	if len(descriptor.Operations) != len(wantOperations) {
		t.Fatalf("advertised %d operations, want %d: %#v", len(descriptor.Operations), len(wantOperations), descriptor.Operations)
	}
	for index, want := range wantOperations {
		got := descriptor.Operations[index]
		if got.Name != want || got.Version != "v1" {
			t.Fatalf("operation %d = %#v, want %q/v1", index, got, want)
		}
	}
}

// TestExecuteAnswersEveryAdvertisedOperation proves the answered surface equals
// the advertised surface. An operation that is advertised but rejected would be
// a capability lie, and the Cluster would surface it as a provider failure
// rather than as a missing mock entry.
func TestExecuteAnswersEveryAdvertisedOperation(t *testing.T) {
	for _, name := range wantOperations {
		request := request{
			RequestID: "req-" + name,
			Function:  functionExecute,
			Operation: &namedContract{Name: name, Version: "v1"},
			Target:    &target{ResourceKind: resourceSession, ProviderResourceKey: "session:stable", ExpectedGeneration: "generation-1"},
			Payload:   json.RawMessage(`{}`),
		}
		response := executeResponse(request, "")
		if !response.OK {
			t.Fatalf("operation %q rejected: %#v", name, response.Error)
		}
		if response.Result == nil {
			t.Fatalf("operation %q returned no result", name)
		}
		if response.Result.DeliveryBoundary == "" || response.Result.EffectCertainty == "" || response.Result.ProviderOutcome == "" {
			t.Fatalf("operation %q returned incomplete evidence: %#v", name, response.Result)
		}
	}
}

// TestExecutePreservesStopEvidence proves the evidence shape the Cluster receipt
// depends on. A stop that reported pipe_written would make the TUI render
// "delivered" instead of "stop request sent", so the boundary is behaviour, not
// decoration.
func TestExecutePreservesStopEvidence(t *testing.T) {
	cases := map[string]string{
		"agent.stop":          "signal_sent",
		"execution.interrupt": "signal_sent",
		"agent.drive.stop":    "signal_sent",
		"message.send":        "pipe_written",
		"context.inject":      "pipe_written",
	}
	for name, wantBoundary := range cases {
		request := request{
			RequestID: "req-" + name,
			Function:  functionExecute,
			Operation: &namedContract{Name: name, Version: "v1"},
			Target:    &target{ResourceKind: resourceSession, ProviderResourceKey: "session:stable", ExpectedGeneration: "generation-1"},
			Payload:   json.RawMessage(`{}`),
		}
		response := executeResponse(request, "")
		if !response.OK || response.Result == nil {
			t.Fatalf("operation %q rejected: %#v", name, response.Error)
		}
		if response.Result.DeliveryBoundary != wantBoundary {
			t.Fatalf("operation %q delivery boundary = %q, want %q", name, response.Result.DeliveryBoundary, wantBoundary)
		}
	}
}

// TestExecuteRejectsLiveOperationWithoutGeneration proves the fail-closed rule
// survives the widened surface: a live operation with no generation is rejected
// before any effect is claimed, while a non-live operation is allowed to carry
// none because it addresses a durable record rather than a process.
func TestExecuteRejectsLiveOperationWithoutGeneration(t *testing.T) {
	live := request{
		RequestID: "req-live",
		Function:  functionExecute,
		Operation: &namedContract{Name: "message.send", Version: "v1"},
		Target:    &target{ResourceKind: resourceSession, ProviderResourceKey: "session:stable"},
		Payload:   json.RawMessage(`{}`),
	}
	if response := executeResponse(live, ""); response.OK || response.Error == nil || response.Error.Code != "generation_mismatch" {
		t.Fatalf("live operation without generation was not rejected: %#v", response)
	}
	for _, name := range []string{"agent.resume", "agent.drive.stop", "workspace.clean"} {
		nonLive := request{
			RequestID: "req-" + name,
			Function:  functionExecute,
			Operation: &namedContract{Name: name, Version: "v1"},
			Target:    &target{ResourceKind: resourceSession, ProviderResourceKey: "session:stable"},
			Payload:   json.RawMessage(`{}`),
		}
		if response := executeResponse(nonLive, ""); !response.OK {
			t.Fatalf("non-live operation %q rejected: %#v", name, response.Error)
		}
	}
}

// TestExecuteRejectsUnknownOperation proves an operation outside the advertised
// set is rejected rather than silently succeeding.
func TestExecuteRejectsUnknownOperation(t *testing.T) {
	request := request{
		RequestID: "req-unknown",
		Function:  functionExecute,
		Operation: &namedContract{Name: "agent.teleport", Version: "v1"},
		Target:    &target{ResourceKind: resourceSession, ProviderResourceKey: "session:stable", ExpectedGeneration: "generation-1"},
		Payload:   json.RawMessage(`{}`),
	}
	response := executeResponse(request, "")
	if response.OK || response.Error == nil || response.Error.Code != "unsupported" {
		t.Fatalf("unknown operation was not rejected: %#v", response)
	}
}
