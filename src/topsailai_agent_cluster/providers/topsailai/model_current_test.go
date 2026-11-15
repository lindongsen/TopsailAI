package main

import (
	"context"
	"encoding/json"
	"errors"
	"testing"
)

// TestCurrentModelNameReadsTheRegisteredInstruction proves the observation uses
// the registered agent.llm instruction and returns the live model name.
func TestCurrentModelNameReadsTheRegisteredInstruction(t *testing.T) {
	runner := &scriptedRunner{t: t, answers: map[string][]runnerAnswer{
		"runtime\x00control\x00call_instruction\x00-s\x00s-1\x00-a\x00{\"args\":null,\"instruction\":\"agent.llm\"}\x00--json": answer(`{"ok":true,"response":{"status":"ok","result":"fast"}}`),
	}}
	got := fixedProvider(runner).currentModelName(context.Background(), "s-1")
	if got != "fast" {
		t.Fatalf("currentModelName = %q, want %q", got, "fast")
	}
	if len(runner.calls) != 1 {
		t.Fatalf("calls = %d, want 1", len(runner.calls))
	}
}

// TestCurrentModelNameIsUnavailableRatherThanFatal proves every unavailable
// observation collapses to an empty name instead of an error, because a catalog
// that cannot prove the current model is still a usable menu.
func TestCurrentModelNameIsUnavailableRatherThanFatal(t *testing.T) {
	key := "runtime\x00control\x00call_instruction\x00-s\x00s-1\x00-a\x00{\"args\":null,\"instruction\":\"agent.llm\"}\x00--json"
	cases := []struct {
		name   string
		answer runnerAnswer
	}{
		{name: "provider failed", answer: runnerAnswer{err: errors.New("boom")}},
		{name: "not ok", answer: runnerAnswer{stdout: `{"ok":false,"response":{"status":"ok","result":"fast"}}`}},
		{name: "error code", answer: runnerAnswer{stdout: `{"ok":true,"error_code":"E_X","response":{"status":"ok","result":"fast"}}`}},
		{name: "no response", answer: runnerAnswer{stdout: `{"ok":true}`}},
		{name: "status not ok", answer: runnerAnswer{stdout: `{"ok":true,"response":{"status":"error","result":"fast"}}`}},
		{name: "malformed document", answer: runnerAnswer{stdout: `not json`}},
	}
	for _, testCase := range cases {
		t.Run(testCase.name, func(t *testing.T) {
			runner := &scriptedRunner{t: t, answers: map[string][]runnerAnswer{key: {testCase.answer}}}
			if got := fixedProvider(runner).currentModelName(context.Background(), "s-1"); got != "" {
				t.Fatalf("currentModelName = %q, want an empty name", got)
			}
		})
	}
}

// TestModelCurrentStateKeepsUnobservedDistinctFromNegative pins the tri-state
// contract: an unobserved name is unknown for every profile, while an observed
// name that matches nothing is a definite no.
func TestModelCurrentStateKeepsUnobservedDistinctFromNegative(t *testing.T) {
	cases := []struct {
		name        string
		profileName string
		currentName string
		want        string
	}{
		{name: "unobserved", profileName: "fast", currentName: "", want: modelCurrentUnknown},
		{name: "matching", profileName: "fast", currentName: "fast", want: modelCurrentYes},
		{name: "different", profileName: "fast", currentName: "slow", want: modelCurrentNo},
		{name: "observed but unlisted", profileName: "fast", currentName: "retired", want: modelCurrentNo},
	}
	for _, testCase := range cases {
		t.Run(testCase.name, func(t *testing.T) {
			if got := modelCurrentState(testCase.profileName, testCase.currentName); got != testCase.want {
				t.Fatalf("modelCurrentState(%q, %q) = %q, want %q", testCase.profileName, testCase.currentName, got, testCase.want)
			}
		})
	}
}

// TestModelCatalogReportsTheObservedCurrentModel proves the catalog column is
// filled from the observation instead of a fixed literal.
func TestModelCatalogReportsTheObservedCurrentModel(t *testing.T) {
	runner := &scriptedRunner{t: t, answers: map[string][]runnerAnswer{
		"workspace\x00list\x00--json\x00--local": answer(`{"items":[{"session_id":"s-1","filename":"row","pid":77}]}`),
		"models\x00list\x00--json":               answer(`[{"name":"fast","protocol":"openai-compatible"},{"name":"slow","protocol":"openai-compatible"}]`),
		"runtime\x00control\x00call_instruction\x00-s\x00s-1\x00-a\x00{\"args\":null,\"instruction\":\"agent.llm\"}\x00--json": answer(`{"ok":true,"response":{"status":"ok","result":"slow"}}`),
	}}
	result, err := fixedProvider(runner).models(context.Background(), sessionTarget(t), json.RawMessage(`{}`))
	if err != nil {
		t.Fatalf("models: %v", err)
	}
	states := map[string]string{}
	for _, profile := range result.Profiles {
		states[profile.ProviderDisplayName] = profile.CurrentState
	}
	if states["fast"] != modelCurrentNo {
		t.Fatalf("fast current_state = %q, want %q", states["fast"], modelCurrentNo)
	}
	if states["slow"] != modelCurrentYes {
		t.Fatalf("slow current_state = %q, want %q", states["slow"], modelCurrentYes)
	}
}

// TestModelCatalogStaysUsableWhenTheObservationIsUnavailable proves an
// unavailable observation degrades every profile to unknown instead of failing
// the read.
func TestModelCatalogStaysUsableWhenTheObservationIsUnavailable(t *testing.T) {
	runner := &scriptedRunner{t: t, answers: map[string][]runnerAnswer{
		"workspace\x00list\x00--json\x00--local": answer(`{"items":[{"session_id":"s-1","filename":"row","pid":77}]}`),
		"models\x00list\x00--json":               answer(`[{"name":"fast","protocol":"openai-compatible"}]`),
		"runtime\x00control\x00call_instruction\x00-s\x00s-1\x00-a\x00{\"args\":null,\"instruction\":\"agent.llm\"}\x00--json": {runnerAnswer{err: errors.New("boom")}},
	}}
	result, err := fixedProvider(runner).models(context.Background(), sessionTarget(t), json.RawMessage(`{}`))
	if err != nil {
		t.Fatalf("models must stay usable: %v", err)
	}
	if len(result.Profiles) != 1 {
		t.Fatalf("profiles = %d, want 1", len(result.Profiles))
	}
	if result.Profiles[0].CurrentState != modelCurrentUnknown {
		t.Fatalf("current_state = %q, want %q", result.Profiles[0].CurrentState, modelCurrentUnknown)
	}
}
