package main

import (
	"context"
	"encoding/json"
	"testing"
)

// TestModelCatalogUsesTheSuppliedIdentityWithoutDiscovery proves the catalog read
// addresses the session the caller named instead of scanning every workspace row to
// recover an identity the caller already held.
//
// The scripted runner fails on any unscripted call, so the absence of a
// `workspace list` answer is the assertion: if the read still resolved the target
// from the mapping key, this test would fail with "unexpected CLI call" rather than
// pass for an unrelated reason.
func TestModelCatalogUsesTheSuppliedIdentityWithoutDiscovery(t *testing.T) {
	runner := &scriptedRunner{t: t, answers: map[string][]runnerAnswer{
		"models\x00list\x00--json": answer(`[{"name":"fast","protocol":"openai-compatible"}]`),
		"runtime\x00control\x00call_instruction\x00-s\x00s-1\x00-p\x0077\x00-a\x00{\"args\":null,\"instruction\":\"agent.llm\"}\x00--json": answer(`{"ok":true,"response":{"status":"ok","result":"fast"}}`),
	}}
	payload := json.RawMessage(`{"provider_session_id":"s-1","provider_pid":77}`)
	result, err := fixedProvider(runner).models(context.Background(), sessionTarget(t), payload)
	if err != nil {
		t.Fatalf("models: %v", err)
	}
	if len(result.Profiles) != 1 {
		t.Fatalf("profiles = %d, want 1", len(result.Profiles))
	}
	if result.Profiles[0].CurrentState != modelCurrentYes {
		t.Fatalf("current_state = %q, want %q", result.Profiles[0].CurrentState, modelCurrentYes)
	}
	for _, call := range runner.calls {
		if len(call.args) > 1 && call.args[0] == "workspace" && call.args[1] == "list" {
			t.Fatalf("catalog read ran workspace list: %v", call.args)
		}
	}
	if len(runner.calls) != 2 {
		t.Fatalf("calls = %d, want 2 (models list and the current-model observation)", len(runner.calls))
	}
}

// TestModelCatalogFallsBackToDiscoveryWithoutAnIdentity proves the previous
// behaviour still serves a caller that supplies no identity, so the new field
// widens reachability instead of replacing a working path.
func TestModelCatalogFallsBackToDiscoveryWithoutAnIdentity(t *testing.T) {
	runner := &scriptedRunner{t: t, answers: map[string][]runnerAnswer{
		"workspace\x00list\x00--json\x00--local": answer(`{"items":[{"session_id":"s-1","filename":"row","pid":77}]}`),
		"models\x00list\x00--json":               answer(`[{"name":"fast","protocol":"openai-compatible"}]`),
		"runtime\x00control\x00call_instruction\x00-s\x00s-1\x00-p\x0077\x00-a\x00{\"args\":null,\"instruction\":\"agent.llm\"}\x00--json": answer(`{"ok":true,"response":{"status":"ok","result":"fast"}}`),
	}}
	result, err := fixedProvider(runner).models(context.Background(), sessionTarget(t), json.RawMessage(`{}`))
	if err != nil {
		t.Fatalf("models: %v", err)
	}
	if len(result.Profiles) != 1 || result.Profiles[0].CurrentState != modelCurrentYes {
		t.Fatalf("result = %+v, want one profile marked current", result)
	}
	if len(runner.calls) != 3 {
		t.Fatalf("calls = %d, want 3 (discovery, models list and the observation)", len(runner.calls))
	}
}

// TestModelCatalogRejectsANegativePID proves a malformed identity is refused
// instead of being forwarded as an argv element the provider would misread.
func TestModelCatalogRejectsANegativePID(t *testing.T) {
	runner := &scriptedRunner{t: t, answers: map[string][]runnerAnswer{}}
	payload := json.RawMessage(`{"provider_session_id":"s-1","provider_pid":-1}`)
	if _, err := fixedProvider(runner).models(context.Background(), sessionTarget(t), payload); err == nil {
		t.Fatal("models accepted a negative provider_pid")
	}
	if len(runner.calls) != 0 {
		t.Fatalf("calls = %d, want 0: a rejected payload must not reach the provider", len(runner.calls))
	}
}
