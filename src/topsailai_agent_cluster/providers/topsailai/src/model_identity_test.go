package main

import (
	"context"
	"encoding/json"
	"testing"
)

// TestModelCatalogUsesTheSuppliedTargetInOneCall proves an online catalog read
// consumes the exact Provider slot and needs only the agent.models instruction.
func TestModelCatalogUsesTheSuppliedTargetInOneCall(t *testing.T) {
	runner := &scriptedRunner{t: t, answers: map[string][]runnerAnswer{
		"runtime\x00control\x00call_instruction\x00-s\x00s-1\x00-p\x0077\x00-a\x00{\"instruction\":\"agent.models\",\"kwargs\":{\"json\":\"1\"}}\x00--json": answer(`{"ok":true,"response":{"status":"ok","result":"{\"ok\":true,\"current_model\":\"fast\",\"models\":[{\"name\":\"fast\",\"current\":true}]}"}}`),
	}}
	slot, err := encodeProviderTarget(providerSessionTarget{SessionID: "s-1", PID: 77, ProviderRowKey: "row"})
	if err != nil {
		t.Fatal(err)
	}
	target := sessionTarget(t)
	target.ProviderTarget = slot
	result, err := fixedProvider(runner).models(context.Background(), target, json.RawMessage(`{}`))
	if err != nil {
		t.Fatalf("models: %v", err)
	}
	if len(result.Profiles) != 1 || result.Profiles[0].CurrentState != modelCurrentYes || !result.Profiles[0].Available {
		t.Fatalf("result = %+v, want one available current profile", result)
	}
	if len(runner.calls) != 1 {
		t.Fatalf("calls = %d, want exactly one agent.models call", len(runner.calls))
	}
}

// TestModelCatalogFallsBackWithoutAProviderTarget proves a historical target
// still resolves through discovery and uses the explicit offline sources.
func TestModelCatalogFallsBackWithoutAProviderTarget(t *testing.T) {
	runner := &scriptedRunner{t: t, answers: map[string][]runnerAnswer{
		"workspace\x00list\x00--json\x00--local": answer(`{"items":[{"session_id":"s-1","filename":"row","pid":77}]}`),
		"models\x00list\x00--json":               answer(`[{"name":"fast","protocol":"openai-compatible"}]`),
		"session\x00info\x00s-1\x00--json":       answer(`{"model_name":"fast"}`),
	}}
	result, err := fixedProvider(runner).models(context.Background(), sessionTarget(t), json.RawMessage(`{}`))
	if err != nil {
		t.Fatalf("models: %v", err)
	}
	if len(result.Profiles) != 1 || result.Profiles[0].CurrentState != modelCurrentYes {
		t.Fatalf("result = %+v, want one current profile", result)
	}
	if len(runner.calls) != 3 {
		t.Fatalf("calls = %d, want discovery, models list and session info", len(runner.calls))
	}
}

// TestModelCatalogRejectsAMalformedProviderTarget proves Provider-private target
// validation happens before any business CLI invocation.
func TestModelCatalogRejectsAMalformedProviderTarget(t *testing.T) {
	runner := &scriptedRunner{t: t, answers: map[string][]runnerAnswer{}}
	target := sessionTarget(t)
	target.ProviderTarget = `{"provider_session_id":"s-1","provider_pid":-1}`
	if _, err := fixedProvider(runner).models(context.Background(), target, json.RawMessage(`{}`)); err == nil {
		t.Fatal("models accepted a negative provider_pid")
	}
	if len(runner.calls) != 0 {
		t.Fatalf("calls = %d, want 0", len(runner.calls))
	}
}

// TestModelCatalogRejectsAProviderTargetForAnotherRow proves the one-call online
// path remains bound to the durable Provider resource key.
func TestModelCatalogRejectsAProviderTargetForAnotherRow(t *testing.T) {
	runner := &scriptedRunner{t: t, answers: map[string][]runnerAnswer{}}
	target := sessionTarget(t)
	slot, err := encodeProviderTarget(providerSessionTarget{SessionID: "other", ProviderRowKey: "other-row", PID: 88})
	if err != nil {
		t.Fatal(err)
	}
	target.ProviderTarget = slot
	if _, err := fixedProvider(runner).models(context.Background(), target, json.RawMessage(`{}`)); err == nil {
		t.Fatal("models accepted a provider target for another row")
	}
	if len(runner.calls) != 0 {
		t.Fatalf("calls=%v, want none", runner.calls)
	}
}
