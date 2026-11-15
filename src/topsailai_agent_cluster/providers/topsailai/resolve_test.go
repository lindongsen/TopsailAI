package main

import (
	"context"
	"encoding/json"
	"strings"
	"testing"
)

// resolveRequest builds one resolve request for a provider session identifier.
func resolveRequest(handle string) request {
	value := validRequest(functionResolve)
	value.Payload = json.RawMessage(`{"handle":"` + handle + `"}`)
	return value
}

// sessionScopedTarget returns a target that names the session rather than a row.
func sessionScopedTarget(t *testing.T, sessionID string) *target {
	t.Helper()
	key, err := sessionProviderKey(sessionID)
	if err != nil {
		t.Fatal(err)
	}
	return &target{ResourceKind: resourceSession, ProviderResourceKey: key}
}

// TestResolveMintsSessionScopedKeyWithoutCallingTheProvider proves resolving a
// handle is local bookkeeping: the key is minted from the identifier alone and the
// provider CLI is never asked whether the session exists.
func TestResolveMintsSessionScopedKeyWithoutCallingTheProvider(t *testing.T) {
	runner := &scriptedRunner{t: t, answers: map[string][]runnerAnswer{}}
	response := fixedProvider(runner).dispatch(context.Background(), resolveRequest("s-1"))
	if !response.OK || response.Resolution == nil {
		t.Fatalf("response=%+v", response)
	}
	want, err := sessionProviderKey("s-1")
	if err != nil {
		t.Fatal(err)
	}
	if response.Resolution.ProviderResourceKey != want {
		t.Fatalf("key=%q want %q", response.Resolution.ProviderResourceKey, want)
	}
	if response.Resolution.ResourceKind != resourceSession {
		t.Fatalf("kind=%q", response.Resolution.ResourceKind)
	}
	if len(runner.calls) != 0 {
		t.Fatalf("resolve invoked the provider CLI: %v", runner.calls)
	}
}

// TestSessionProviderKeyIsStableAndDistinctFromEveryOtherSelector proves the
// session selector is stable for one identifier and cannot collide with a row key
// or a history key, which are different identities for the same session.
func TestSessionProviderKeyIsStableAndDistinctFromEveryOtherSelector(t *testing.T) {
	first, err := sessionProviderKey("s-1")
	if err != nil {
		t.Fatal(err)
	}
	again, err := sessionProviderKey("s-1")
	if err != nil {
		t.Fatal(err)
	}
	other, err := sessionProviderKey("s-2")
	if err != nil {
		t.Fatal(err)
	}
	row, err := providerSessionKey(workspaceItem{SessionID: "s-1", ProviderRowKey: "row"})
	if err != nil {
		t.Fatal(err)
	}
	history, err := historySessionKey("s-1")
	if err != nil {
		t.Fatal(err)
	}
	if first != again {
		t.Fatalf("session key is not stable: %q != %q", first, again)
	}
	if first == other {
		t.Fatalf("two sessions share key %q", first)
	}
	if first == row || first == history {
		t.Fatalf("session key collides with another selector: %q", first)
	}
	if !strings.HasPrefix(first, sessionProviderKeyPrefix) {
		t.Fatalf("session key prefix=%q", first)
	}
	if len(first) > maxProviderKeyLength {
		t.Fatalf("key length=%d", len(first))
	}
}

// TestResolveRejectsEmptyAndMalformedHandles proves a handle that names nothing is
// a rejection rather than a key minted from an empty identity.
func TestResolveRejectsEmptyAndMalformedHandles(t *testing.T) {
	tests := map[string]string{
		"empty":         `{"handle":""}`,
		"blank":         `{"handle":"   "}`,
		"missing":       `{}`,
		"null document": `null`,
		"unknown field": `{"handle":"s-1","cluster_id":"c"}`,
	}
	for name, payload := range tests {
		t.Run(name, func(t *testing.T) {
			runner := &scriptedRunner{t: t, answers: map[string][]runnerAnswer{}}
			value := validRequest(functionResolve)
			value.Payload = json.RawMessage(payload)
			response := fixedProvider(runner).dispatch(context.Background(), value)
			if response.OK || response.Error == nil || response.Error.Code != "invalid_request" {
				t.Fatalf("response=%+v", response)
			}
			if len(runner.calls) != 0 {
				t.Fatalf("rejected resolve invoked the provider CLI: %v", runner.calls)
			}
		})
	}
}

// TestValidateSessionTargetAcceptsBothSessionSelectors proves the row selector and
// the session selector are both valid targets while a history key is not.
func TestValidateSessionTargetAcceptsBothSessionSelectors(t *testing.T) {
	rowKey, err := providerSessionKey(workspaceItem{SessionID: "s-1", ProviderRowKey: "row"})
	if err != nil {
		t.Fatal(err)
	}
	sessionKey, err := sessionProviderKey("s-1")
	if err != nil {
		t.Fatal(err)
	}
	historyKey, err := historySessionKey("s-1")
	if err != nil {
		t.Fatal(err)
	}
	accepted := map[string]*target{
		"row selector":     {ResourceKind: resourceSession, ProviderResourceKey: rowKey},
		"session selector": {ResourceKind: resourceSession, ProviderResourceKey: sessionKey},
	}
	for name, value := range accepted {
		t.Run(name, func(t *testing.T) {
			if _, err := validateSessionTarget(value); err != nil {
				t.Fatalf("accepted selector rejected: %v", err)
			}
		})
	}
	rejected := map[string]*target{
		"history selector": {ResourceKind: resourceSession, ProviderResourceKey: historyKey},
		"empty key":        {ResourceKind: resourceSession},
		"wrong kind":       {ResourceKind: resourceLaunchProfile, ProviderResourceKey: sessionKey},
		"no target":        nil,
	}
	for name, value := range rejected {
		t.Run(name, func(t *testing.T) {
			if _, err := validateSessionTarget(value); err == nil {
				t.Fatal("invalid selector was accepted")
			}
		})
	}
}

// TestInspectReportsLiveWhenAnyRowOfTheSessionIsLive proves the scan does not stop
// at the first matching row: a dormant sibling must not hide a live one, because
// that would let resume target a session that is still running.
func TestInspectReportsLiveWhenAnyRowOfTheSessionIsLive(t *testing.T) {
	document := `{"items":[{"session_id":"s-1","filename":"manager.stdout","pid":42},{"session_id":"s-1","filename":"task.stdout","pid":99,"process_generation":9,"is_task":true},{"session_id":"s-2","filename":"row","pid":7,"process_generation":3}]}`
	runner := &scriptedRunner{t: t, answers: map[string][]runnerAnswer{authorityCall: answer(document)}}
	value := validRequest(functionInspect)
	value.Target = sessionScopedTarget(t, "s-1")
	response := fixedProvider(runner).dispatch(context.Background(), value)
	if !response.OK || response.Inspection == nil {
		t.Fatalf("response=%+v", response)
	}
	if !response.Inspection.Found || !response.Inspection.Live {
		t.Fatalf("inspection=%+v", response.Inspection)
	}
	if response.Inspection.Observation.ProviderGeneration != "9" {
		t.Fatalf("observation=%+v", response.Inspection.Observation)
	}
	if response.Inspection.Observation.Attributes == nil {
		t.Fatal("live observation carries no attributes")
	}
}

// TestInspectReportsDormantSessionAsFoundNotLive proves a session with no live row
// is reported as found and not live rather than as missing.
func TestInspectReportsDormantSessionAsFoundNotLive(t *testing.T) {
	document := `{"items":[{"session_id":"s-1","filename":"manager.stdout","pid":42},{"session_id":"s-1","filename":"task.stdout","pid":99,"is_task":true}]}`
	runner := &scriptedRunner{t: t, answers: map[string][]runnerAnswer{authorityCall: answer(document)}}
	value := validRequest(functionInspect)
	value.Target = sessionScopedTarget(t, "s-1")
	response := fixedProvider(runner).dispatch(context.Background(), value)
	if !response.OK || response.Inspection == nil {
		t.Fatalf("response=%+v", response)
	}
	if !response.Inspection.Found || response.Inspection.Live {
		t.Fatalf("inspection=%+v", response.Inspection)
	}
}

// TestInspectReportsUnknownSessionAsMissing proves a session selector that matches
// no row is reported as not found.
func TestInspectReportsUnknownSessionAsMissing(t *testing.T) {
	document := `{"items":[{"session_id":"s-2","filename":"row","pid":7,"process_generation":3}]}`
	runner := &scriptedRunner{t: t, answers: map[string][]runnerAnswer{authorityCall: answer(document)}}
	value := validRequest(functionInspect)
	value.Target = sessionScopedTarget(t, "s-1")
	response := fixedProvider(runner).dispatch(context.Background(), value)
	if !response.OK || response.Inspection == nil {
		t.Fatalf("response=%+v", response)
	}
	if response.Inspection.Found || response.Inspection.Live {
		t.Fatalf("inspection=%+v", response.Inspection)
	}
}

// TestInspectStillRejectsDuplicateRowsForARowScopedKey proves the session selector
// did not weaken the row selector: two rows claiming one row key stay ambiguous.
func TestInspectStillRejectsDuplicateRowsForARowScopedKey(t *testing.T) {
	document := `{"items":[{"session_id":"s-1","filename":"row","pid":42},{"session_id":"s-1","filename":"row","pid":42}]}`
	runner := &scriptedRunner{t: t, answers: map[string][]runnerAnswer{authorityCall: answer(document)}}
	value := validRequest(functionInspect)
	value.Target = sessionTarget(t)
	response := fixedProvider(runner).dispatch(context.Background(), value)
	if response.OK || response.Error == nil {
		t.Fatalf("duplicate row was accepted: %+v", response)
	}
}

// TestWorkspaceAuthorityPrefersTheLiveRowForASessionScopedKey proves the authority
// read addresses the live row of the named session, so a mutation cannot be
// validated against a dormant sibling.
func TestWorkspaceAuthorityPrefersTheLiveRowForASessionScopedKey(t *testing.T) {
	document := `{"items":[{"session_id":"s-1","filename":"manager.stdout","pid":42},{"session_id":"s-1","filename":"task.stdout","pid":99,"process_generation":9,"is_task":true}]}`
	runner := &scriptedRunner{t: t, answers: map[string][]runnerAnswer{authorityCall: answer(document)}}
	target := sessionScopedTarget(t, "s-1")
	target.ExpectedGeneration = "9"
	resolved, generation, err := fixedProvider(runner).workspaceAuthority(context.Background(), target)
	if err != nil {
		t.Fatalf("authority: %v", err)
	}
	if generation != "9" || resolved.ProviderRowKey != "task.stdout" || resolved.PID != 99 || !resolved.IsTask {
		t.Fatalf("resolved=%+v generation=%q", resolved, generation)
	}
}

// TestWorkspaceAuthorityStillRejectsDuplicateRowsForARowScopedKey proves the row
// selector keeps its ambiguity rejection.
func TestWorkspaceAuthorityStillRejectsDuplicateRowsForARowScopedKey(t *testing.T) {
	document := `{"items":[{"session_id":"s-1","filename":"row","pid":42},{"session_id":"s-1","filename":"row","pid":42}]}`
	runner := &scriptedRunner{t: t, answers: map[string][]runnerAnswer{authorityCall: answer(document)}}
	if _, _, err := fixedProvider(runner).workspaceAuthority(context.Background(), liveSessionTarget(t, "7")); err == nil {
		t.Fatal("duplicate row was accepted")
	}
}

// TestResolveKeyAddressesTheSessionTheRowKeyBelongsTo proves the two selectors
// describe one session: a session key and a row key of that session both resolve
// rows of the same session, and neither resolves another session.
func TestResolveKeyAddressesTheSessionTheRowKeyBelongsTo(t *testing.T) {
	sessionKey, err := sessionProviderKey("s-1")
	if err != nil {
		t.Fatal(err)
	}
	rowKey, err := providerSessionKey(workspaceItem{SessionID: "s-1", ProviderRowKey: "row"})
	if err != nil {
		t.Fatal(err)
	}
	ownRow := workspaceItem{SessionID: "s-1", ProviderRowKey: "row"}
	otherRow := workspaceItem{SessionID: "s-1", ProviderRowKey: "task.stdout", IsTask: true}
	foreignRow := workspaceItem{SessionID: "s-2", ProviderRowKey: "row"}
	tests := []struct {
		name string
		key  string
		item workspaceItem
		want bool
	}{
		{name: "session key matches its own row", key: sessionKey, item: ownRow, want: true},
		{name: "session key matches a sibling row", key: sessionKey, item: otherRow, want: true},
		{name: "session key rejects another session", key: sessionKey, item: foreignRow, want: false},
		{name: "row key matches its own row", key: rowKey, item: ownRow, want: true},
		{name: "row key rejects a sibling row", key: rowKey, item: otherRow, want: false},
		{name: "row key rejects another session", key: rowKey, item: foreignRow, want: false},
	}
	for _, test := range tests {
		t.Run(test.name, func(t *testing.T) {
			got, err := matchesSessionKey(test.key, test.item)
			if err != nil {
				t.Fatalf("match: %v", err)
			}
			if got != test.want {
				t.Fatalf("matched=%v want %v", got, test.want)
			}
		})
	}
}

// TestResolveHasAHandlerButIsNotAdvertisedYet proves the descriptor stays narrower
// than the dispatch switch while the frozen request schema cannot carry the name.
//
// Advertising a function the wire contract rejects would claim a capability no
// caller can reach, and the conformance sweep invokes every advertised function, so
// the name must appear in the descriptor only together with the schema enum that
// admits it. This guard fails the moment one side moves without the other.
func TestResolveHasAHandlerButIsNotAdvertisedYet(t *testing.T) {
	runner := &scriptedRunner{t: t, answers: map[string][]runnerAnswer{}}
	response := fixedProvider(runner).dispatch(context.Background(), resolveRequest("s-1"))
	if !response.OK || response.Resolution == nil {
		t.Fatalf("resolve has no handler: %+v", response)
	}
	for _, advertised := range topsailaiDescriptor(controlCatalog{}).Functions {
		if advertised == functionResolve {
			t.Fatal("resolve is advertised while the request schema cannot carry it")
		}
	}
}
