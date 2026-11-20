package main

import (
	"context"
	"encoding/json"
	"errors"
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
		"models\x00list\x00--json":    answer(`[{"id":"my-model","name":"My Model","protocol":"openai-compatible"},{"id":"second","name":"second","protocol":"openai-compatible"}]`),
		"models\x00current\x00--json": answer(`{"status":"ok","scope":"workspace","source":"workspace","model_id":"my-model"}`),
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
	if len(runner.calls) != 2 {
		t.Fatalf("calls = %v, want exactly the list and current reads", runner.calls)
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

// TestModelRegistryReportsAnUnobservedSelectionAsUnknown proves a failed selection read
// keeps the menu and states that the source was not observed.
//
// Failing the whole read would take every model away because one observation was
// unavailable, and reporting a concrete source would claim an observation nobody made.
func TestModelRegistryReportsAnUnobservedSelectionAsUnknown(t *testing.T) {
	runner := &scriptedRunner{t: t, answers: map[string][]runnerAnswer{
		"models\x00list\x00--json":    answer(`[{"id":"a","name":"A","protocol":"openai-compatible"}]`),
		"models\x00current\x00--json": {{stderr: "boom", err: errors.New("scripted failure")}},
	}}
	result, err := fixedProvider(runner).modelRegistry(context.Background(), nil, json.RawMessage(`{}`))
	if err != nil {
		t.Fatalf("modelRegistry: %v", err)
	}
	if len(result.Entries) != 1 {
		t.Fatalf("entries = %d, want the menu to survive", len(result.Entries))
	}
	if result.CurrentSource != modelRegistrySourceUnknown || result.CurrentProviderID != "" {
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
		"models\x00list\x00--json":    answer(`[{"id":"on","name":"On","protocol":"openai-compatible"},{"id":"off","name":"Off","protocol":"openai-compatible","enabled":false}]`),
		"models\x00current\x00--json": answer(`{"status":"ok","source":"inherited","model_id":null}`),
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
	if result.CurrentSource != modelRegistrySourceInherited || result.CurrentProviderID != "" {
		t.Fatalf("current = %q/%q, want inherited with no identifier", result.CurrentProviderID, result.CurrentSource)
	}
}

// TestModelRegistryRejectsDuplicateIdentifiers proves two entries cannot share one
// provider resource key.
//
// A duplicate would collapse two registry records onto one Cluster resource, so the
// operator would select one and reach the other.
func TestModelRegistryRejectsDuplicateIdentifiers(t *testing.T) {
	runner := &scriptedRunner{t: t, answers: map[string][]runnerAnswer{
		"models\x00list\x00--json":    answer(`[{"id":"dup","name":"One","protocol":"openai-compatible"},{"id":"dup","name":"Two","protocol":"openai-compatible"}]`),
		"models\x00current\x00--json": answer(`{"status":"ok","source":"inherited","model_id":null}`),
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
		"models\x00list\x00--json":    answer(`[{"id":"nameless","protocol":"openai-compatible"}]`),
		"models\x00current\x00--json": answer(`{"status":"ok","source":"inherited","model_id":null}`),
	}}
	result, err := fixedProvider(runner).modelRegistry(context.Background(), nil, json.RawMessage(`{}`))
	if err != nil {
		t.Fatalf("modelRegistry: %v", err)
	}
	if result.Entries[0].DisplayName != "nameless" {
		t.Fatalf("display_name = %q, want the identifier", result.Entries[0].DisplayName)
	}
}
