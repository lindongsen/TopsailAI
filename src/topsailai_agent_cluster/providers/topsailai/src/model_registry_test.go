package main

import (
	"context"
	"encoding/json"
	"testing"
)

// TestModelRegistryKeysOnTheProviderIdentifier proves the registry addresses entries by
// the provider's own identifier rather than by the display name.
//
// The fixture deliberately gives every entry an identifier that differs from its name,
// because that is the shape the provider produces for any name containing a space or an
// upper-case letter. A fixture whose id equals its name cannot express the failure mode:
// a reader that keyed on the name would pass while being unable to mark the current
// selection, and the operator would see a menu where nothing is in use.
func TestModelRegistryKeysOnTheProviderIdentifier(t *testing.T) {
	runner := &scriptedRunner{t: t, answers: map[string][]runnerAnswer{
		"models\x00list\x00--json": answer(`[{"id":"my-model","name":"My Model","protocol":"openai-compatible","selected":true},{"id":"second","name":"second","protocol":"openai-compatible","selected":false}]`),
	}}
	result, err := fixedProvider(runner).modelRegistry(context.Background(), nil, json.RawMessage(`{}`))
	if err != nil {
		t.Fatalf("modelRegistry: %v", err)
	}
	if len(result.Entries) != 2 {
		t.Fatalf("entries = %d, want 2", len(result.Entries))
	}
	if result.Entries[0].ProviderResourceKey != "model:my-model" {
		t.Fatalf("provider_resource_key = %q, want the identifier not the name", result.Entries[0].ProviderResourceKey)
	}
	if result.Entries[0].ProviderID != "my-model" {
		t.Fatalf("provider_id = %q, want my-model", result.Entries[0].ProviderID)
	}
	if result.Entries[0].DisplayName != "My Model" {
		t.Fatalf("display_name = %q, want the human name", result.Entries[0].DisplayName)
	}
	if result.CurrentProviderID != "my-model" || result.CurrentSource != modelRegistrySourceWorkspace {
		t.Fatalf("current = %q/%q, want my-model/workspace", result.CurrentProviderID, result.CurrentSource)
	}
}

// TestModelRegistryReadsTheSelectionFromTheSameDocument proves the current marker comes
// from the entry list rather than from a second provider call.
//
// Two reads are two sources of truth for one fact, and they disagree in practice: after
// the selected model was disabled, `models list --json` reported every entry as
// selected:false while `models current --json` reported selection_invalid for the same
// state. Reading the marker from the list makes the disagreement structurally
// impossible and costs one provider invocation instead of two.
func TestModelRegistryReadsTheSelectionFromTheSameDocument(t *testing.T) {
	runner := &scriptedRunner{t: t, answers: map[string][]runnerAnswer{
		"models\x00list\x00--json": answer(`[{"id":"a","name":"A","protocol":"openai-compatible","selected":true}]`),
	}}
	if _, err := fixedProvider(runner).modelRegistry(context.Background(), nil, json.RawMessage(`{}`)); err != nil {
		t.Fatalf("modelRegistry: %v", err)
	}
	if len(runner.calls) != 1 {
		t.Fatalf("calls = %v, want exactly one list read", runner.calls)
	}
}

// TestModelRegistryRejectsATarget proves the Endpoint-scoped read refuses a target
// instead of ignoring it.
//
// An ignored target would let a session-scoped caller believe the answer described its
// session, which is the one thing a machine-scoped registry cannot answer.
func TestModelRegistryRejectsATarget(t *testing.T) {
	runner := &scriptedRunner{t: t, answers: map[string][]runnerAnswer{}}
	if _, err := fixedProvider(runner).modelRegistry(context.Background(), sessionTarget(t), json.RawMessage(`{}`)); err == nil {
		t.Fatal("modelRegistry accepted a target")
	}
	if len(runner.calls) != 0 {
		t.Fatalf("calls = %v, want none", runner.calls)
	}
}

// TestModelRegistryReportsNoSelectionAsUnknown proves a registry where every entry
// reports selected:false is answered as "unknown" rather than as a default.
//
// The operator's rule is that all-false means nothing is selected, so the model in use
// is unknown. Reporting a concrete source would claim an observation nobody made, and
// reporting the first entry would invent a selection the provider did not declare.
func TestModelRegistryReportsNoSelectionAsUnknown(t *testing.T) {
	runner := &scriptedRunner{t: t, answers: map[string][]runnerAnswer{
		"models\x00list\x00--json": answer(`[{"id":"a","name":"A","protocol":"openai-compatible","selected":false},{"id":"b","name":"B","protocol":"openai-compatible","selected":false}]`),
	}}
	result, err := fixedProvider(runner).modelRegistry(context.Background(), nil, json.RawMessage(`{}`))
	if err != nil {
		t.Fatalf("modelRegistry: %v", err)
	}
	if len(result.Entries) != 2 {
		t.Fatalf("entries = %d, want the menu to survive", len(result.Entries))
	}
	if result.CurrentProviderID != "" || result.CurrentSource != modelRegistrySourceUnknown {
		t.Fatalf("current = %q/%q, want unknown with no identifier", result.CurrentProviderID, result.CurrentSource)
	}
}

// TestModelRegistryReportsDisabledEntries proves an entry the provider disabled is
// reported as unavailable rather than silently offered.
//
// The provider omits `enabled` when an entry is usable and writes `false` only when it is
// not, so a plain bool would read every usable entry as disabled. The fixture carries one
// of each so the two directions are distinguished in one assertion.
func TestModelRegistryReportsDisabledEntries(t *testing.T) {
	runner := &scriptedRunner{t: t, answers: map[string][]runnerAnswer{
		"models\x00list\x00--json": answer(`[{"id":"on","name":"On","protocol":"openai-compatible","selected":false},{"id":"off","name":"Off","protocol":"openai-compatible","enabled":false,"selected":false}]`),
	}}
	result, err := fixedProvider(runner).modelRegistry(context.Background(), nil, json.RawMessage(`{}`))
	if err != nil {
		t.Fatalf("modelRegistry: %v", err)
	}
	if !result.Entries[0].Available {
		t.Fatalf("entry without an enabled field = %+v, want available", result.Entries[0])
	}
	if result.Entries[1].Available || result.Entries[1].UnavailableReason != "disabled" {
		t.Fatalf("disabled entry = %+v, want unavailable with reason disabled", result.Entries[1])
	}
	if result.CurrentProviderID != "" || result.CurrentSource != modelRegistrySourceUnknown {
		t.Fatalf("current = %q/%q, want unknown with no identifier", result.CurrentProviderID, result.CurrentSource)
	}
}

// TestModelRegistryRejectsTwoSelectedEntries proves a registry that marks two entries as
// selected is refused instead of resolved silently.
//
// "The model in use" must have one answer. Picking one would be a guess, and reporting
// both would leave the operator unable to tell which one a launch would use.
func TestModelRegistryRejectsTwoSelectedEntries(t *testing.T) {
	runner := &scriptedRunner{t: t, answers: map[string][]runnerAnswer{
		"models\x00list\x00--json": answer(`[{"id":"a","name":"A","protocol":"openai-compatible","selected":true},{"id":"b","name":"B","protocol":"openai-compatible","selected":true}]`),
	}}
	if _, err := fixedProvider(runner).modelRegistry(context.Background(), nil, json.RawMessage(`{}`)); err == nil {
		t.Fatal("modelRegistry accepted two selected entries")
	}
}

// TestModelRegistryRejectsDuplicateIdentifiers proves two entries cannot share one
// provider resource key.
//
// A duplicate would collapse two registry records onto one Cluster resource, so the
// operator would select one and reach the other.
func TestModelRegistryRejectsDuplicateIdentifiers(t *testing.T) {
	runner := &scriptedRunner{t: t, answers: map[string][]runnerAnswer{
		"models\x00list\x00--json": answer(`[{"id":"dup","name":"One","protocol":"openai-compatible"},{"id":"dup","name":"Two","protocol":"openai-compatible"}]`),
	}}
	if _, err := fixedProvider(runner).modelRegistry(context.Background(), nil, json.RawMessage(`{}`)); err == nil {
		t.Fatal("modelRegistry accepted duplicate identifiers")
	}
}

// TestModelRegistryFallsBackToTheIdentifierForAMissingName proves a hand-edited record
// stays visible instead of failing the whole read.
//
// The Cluster contract requires a non-empty display name, so an entry without one would
// otherwise reject the registry and hide every usable model. The identifier is the
// entry's real identity, so it is a truthful label rather than a placeholder.
func TestModelRegistryFallsBackToTheIdentifierForAMissingName(t *testing.T) {
	runner := &scriptedRunner{t: t, answers: map[string][]runnerAnswer{
		"models\x00list\x00--json": answer(`[{"id":"nameless","protocol":"openai-compatible"}]`),
	}}
	result, err := fixedProvider(runner).modelRegistry(context.Background(), nil, json.RawMessage(`{}`))
	if err != nil {
		t.Fatalf("modelRegistry: %v", err)
	}
	if result.Entries[0].DisplayName != "nameless" {
		t.Fatalf("display_name = %q, want the identifier", result.Entries[0].DisplayName)
	}
}
