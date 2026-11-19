package main

import (
	"context"
	"errors"
	"testing"
)

// TestCurrentModelNameReadsTheRegisteredInstruction proves the observation uses
// the registered agent.llm instruction and returns the live model name.
func TestCurrentModelNameReadsTheRegisteredInstruction(t *testing.T) {
	runner := &scriptedRunner{t: t, answers: map[string][]runnerAnswer{
		"runtime\x00control\x00call_instruction\x00-s\x00s-1\x00-a\x00{\"args\":null,\"instruction\":\"agent.llm\"}\x00--json": answer(`{"ok":true,"response":{"status":"ok","result":"fast"}}`),
	}}
	got := fixedProvider(runner).currentModelName(context.Background(), "s-1", 0)
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
			if got := fixedProvider(runner).currentModelName(context.Background(), "s-1", 0); got != "" {
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
