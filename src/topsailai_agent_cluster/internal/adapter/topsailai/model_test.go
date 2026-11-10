package topsailai

import (
	"context"
	"encoding/json"
	"strings"
	"testing"

	"topsailai_agent_cluster/internal/adapter"
	"topsailai_agent_cluster/internal/protocol"
)

// modelSelectIntent builds one agent.model.select intent for a mapped session.
func modelSelectIntent(sessionID, profileID string) protocol.ImmutableIntent {
	return protocol.ImmutableIntent{
		CommandID: "cmd-1",
		Operation: protocol.OperationAgentModelSelect,
		Target:    &protocol.CommandTarget{ResourceID: sessionID, Generation: "gen-1"},
		Payload:   []byte(`{"model_profile_id":"` + profileID + `"}`),
	}
}

// mintSession mints the session resource the way a discovery read would, so the
// target resolves before the profile is examined.
func mintSession(t *testing.T, instance *Adapter) string {
	t.Helper()
	sessionID, err := instance.resourceID(context.Background(), "session-1")
	if err != nil {
		t.Fatal(err)
	}
	return sessionID
}

// TestDescribeDeclaresModelSelectAsMutatingControl pins the declared safety class
// and permission. A read_output credential must not be able to change the model a
// running agent uses, so the capability has to declare control rather than inherit
// a weaker default.
func TestDescribeDeclaresModelSelectAsMutatingControl(t *testing.T) {
	descriptor, err := newTestAdapter(t, &fakeRunner{}).Describe(context.Background())
	if err != nil {
		t.Fatal(err)
	}
	var found *protocol.Capability
	for index := range descriptor.Capabilities.Capabilities {
		if descriptor.Capabilities.Capabilities[index].Name == protocol.OperationAgentModelSelect {
			found = &descriptor.Capabilities.Capabilities[index]
		}
	}
	if found == nil {
		t.Fatal("agent.model.select is not advertised")
	}
	if found.SafetyClass != protocol.SafetyClassMutating {
		t.Fatalf("expected mutating safety class, got %q", found.SafetyClass)
	}
	if found.RequiredPermission != "control" {
		t.Fatalf("expected control permission, got %q", found.RequiredPermission)
	}
	if len(found.TargetKinds) != 1 || found.TargetKinds[0] != "session" {
		t.Fatalf("expected a session target, got %v", found.TargetKinds)
	}
}

// TestModelSelectResolvesOpaqueIDToProviderName proves the provider receives the
// provider's own selection key, never the cluster identifier. The provider selects
// by name, so forwarding the opaque identifier would select nothing.
func TestModelSelectResolvesOpaqueIDToProviderName(t *testing.T) {
	runner := &fakeRunner{out: []byte(`{"ok":true,"delivery_state":"control_acknowledged"}`)}
	instance := newTestAdapter(t, runner)
	ctx := context.Background()
	sessionID := mintSession(t, instance)
	// Mint the profile the way a catalog read would, so the identifier is one this
	// Endpoint really owns.
	profileID, err := instance.resourceID(ctx, modelProviderKeyPrefix+"fast-model")
	if err != nil {
		t.Fatal(err)
	}
	result, err := instance.Execute(ctx, adapter.ExecuteRequest{Intent: modelSelectIntent(sessionID, profileID)})
	if err != nil {
		t.Fatalf("expected the selection to execute, got %v", err)
	}
	if result.Receipt.Outcome == "failed" {
		t.Fatalf("unexpected failed receipt %q", result.Receipt.ErrorCode)
	}
	joined := strings.Join(runner.args, " ")
	if !strings.Contains(joined, "call_instruction") {
		t.Fatalf("expected the instruction entry point, got %q", joined)
	}
	if !strings.Contains(joined, "fast-model") {
		t.Fatalf("expected the provider name in the argv, got %q", joined)
	}
	if strings.Contains(joined, profileID) {
		t.Fatalf("the opaque identifier must never reach the provider, got %q", joined)
	}
	// The instruction payload must carry the provider name as one argument, so the
	// provider selects exactly one model instead of parsing a string.
	payloadIndex := -1
	for index, arg := range runner.args {
		if arg == "-a" && index+1 < len(runner.args) {
			payloadIndex = index + 1
		}
	}
	if payloadIndex < 0 {
		t.Fatalf("expected an instruction payload, got %q", joined)
	}
	var payload struct {
		Instruction string   `json:"instruction"`
		Args        []string `json:"args"`
	}
	if err := json.Unmarshal([]byte(runner.args[payloadIndex]), &payload); err != nil {
		t.Fatalf("decode instruction payload: %v", err)
	}
	if payload.Instruction != "agent.models" {
		t.Fatalf("unexpected instruction %q", payload.Instruction)
	}
	if len(payload.Args) != 1 || payload.Args[0] != "fast-model" {
		t.Fatalf("expected one provider name argument, got %v", payload.Args)
	}
}

// TestModelSelectRejectsUnknownProfile proves an identifier this Endpoint never
// minted is rejected before any provider call. Forwarding it would let a caller
// probe the provider's own namespace through the cluster.
func TestModelSelectRejectsUnknownProfile(t *testing.T) {
	runner := &fakeRunner{out: []byte(`{"ok":true}`)}
	instance := newTestAdapter(t, runner)
	sessionID := mintSession(t, instance)
	result, err := instance.Execute(context.Background(), adapter.ExecuteRequest{Intent: modelSelectIntent(sessionID, "res_never-minted")})
	if err == nil {
		t.Fatal("expected an unknown profile to be rejected")
	}
	if result.Receipt.ErrorCode != protocol.ModelSelectUnknownProfile {
		t.Fatalf("expected %q, got %q", protocol.ModelSelectUnknownProfile, result.Receipt.ErrorCode)
	}
	if len(runner.args) != 0 {
		t.Fatalf("the provider must not be called, got %v", runner.args)
	}
}

// TestModelSelectRejectsSessionResourceAsProfile proves a session identifier cannot
// be used as a profile identifier. Both live in one mapping table, so without the
// namespace check a session resource would resolve and select a model named after
// that session.
func TestModelSelectRejectsSessionResourceAsProfile(t *testing.T) {
	runner := &fakeRunner{out: []byte(`{"ok":true}`)}
	instance := newTestAdapter(t, runner)
	sessionID := mintSession(t, instance)
	result, err := instance.Execute(context.Background(), adapter.ExecuteRequest{Intent: modelSelectIntent(sessionID, sessionID)})
	if err == nil {
		t.Fatal("expected a session resource to be rejected as a profile")
	}
	if result.Receipt.ErrorCode != protocol.ModelSelectUnknownProfile {
		t.Fatalf("expected %q, got %q", protocol.ModelSelectUnknownProfile, result.Receipt.ErrorCode)
	}
	if len(runner.args) != 0 {
		t.Fatalf("the provider must not be called, got %v", runner.args)
	}
}

// TestModelSelectRejectsProviderVocabularyInPayload proves a payload carrying a
// provider name or index is rejected. Accepting it would let a caller bypass the
// opaque identifier and address the provider's own namespace directly.
func TestModelSelectRejectsProviderVocabularyInPayload(t *testing.T) {
	runner := &fakeRunner{out: []byte(`{"ok":true}`)}
	instance := newTestAdapter(t, runner)
	sessionID := mintSession(t, instance)
	intent := modelSelectIntent(sessionID, "res_whatever")
	intent.Payload = []byte(`{"model_profile_id":"res_whatever","provider_model":"gpt-4"}`)
	result, err := instance.Execute(context.Background(), adapter.ExecuteRequest{Intent: intent})
	if err == nil {
		t.Fatal("expected provider vocabulary in the payload to be rejected")
	}
	if result.Receipt.ErrorCode != "invalid_payload" {
		t.Fatalf("expected invalid_payload, got %q", result.Receipt.ErrorCode)
	}
	if len(runner.args) != 0 {
		t.Fatalf("the provider must not be called, got %v", runner.args)
	}
}
