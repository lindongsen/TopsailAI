package topsailai

import (
	"context"
	"testing"

	"topsailai_agent_cluster/internal/adapter"
	"topsailai_agent_cluster/internal/protocol"
)

// TestProviderSessionHandleKeyIsDecodable proves the handle key is a real
// TopsailAI session selector. A bare provider session identifier is not, which is
// what made every history-only resume fail with "resource mapping is not a
// TopsailAI session row".
func TestProviderSessionHandleKeyIsDecodable(t *testing.T) {
	key, err := providerSessionHandleKey("wa-1")
	if err != nil {
		t.Fatal(err)
	}
	target, err := decodeProviderSessionKey(key)
	if err != nil {
		t.Fatalf("handle key must decode: %v", err)
	}
	if target.SessionID != "wa-1" {
		t.Fatalf("session ID = %q, want wa-1", target.SessionID)
	}
	if !target.SessionScoped {
		t.Fatal("handle key must be session-scoped")
	}
}

// TestProviderSessionHandleKeyRejectsEmpty proves an empty handle cannot mint a
// mapping that would address nothing.
func TestProviderSessionHandleKeyRejectsEmpty(t *testing.T) {
	if _, err := providerSessionHandleKey(""); err == nil {
		t.Fatal("empty handle must be rejected")
	}
}

// TestResolveProviderSessionHandleIsStableAndOffline proves resolution mints a
// durable mapping without asking the provider, and that resolving twice returns
// the same identity. Asking the provider would re-introduce the existence
// judgement the operator explicitly removed.
func TestResolveProviderSessionHandleIsStableAndOffline(t *testing.T) {
	runner := &fakeRunner{}
	a := newTestAdapter(t, runner)
	first, err := a.ResolveProviderSessionHandle(context.Background(), "wa-1")
	if err != nil {
		t.Fatal(err)
	}
	second, err := a.ResolveProviderSessionHandle(context.Background(), "wa-1")
	if err != nil {
		t.Fatal(err)
	}
	if first.ResourceID == "" {
		t.Fatal("resolution must mint a resource ID")
	}
	if first.ResourceID != second.ResourceID {
		t.Fatalf("resolution is not stable: %q then %q", first.ResourceID, second.ResourceID)
	}
	if runner.args != nil {
		t.Fatalf("resolution must not invoke the provider, invoked %v", runner.args)
	}
}

// TestSessionScopedTargetMatchesAnyRowOfTheSession proves a handle mapping is not
// tied to one row. One provider session identifier can appear in several rows, and
// the operator named the session rather than a row.
func TestSessionScopedTargetMatchesAnyRowOfTheSession(t *testing.T) {
	target := providerSessionTarget{SessionID: "wa-1", SessionScoped: true}
	item := workspaceItem{SessionID: "wa-1", ProviderRowKey: "file-a", PID: 42, IsTask: true}
	if !target.matchesWorkspaceItem(item) {
		t.Fatal("session-scoped target must match any row of its session")
	}
	if target.matchesWorkspaceItem(workspaceItem{SessionID: "wa-2"}) {
		t.Fatal("session-scoped target must not match another session")
	}
}

// TestRowScopedTargetStillRequiresExactRow proves the existing row contract is
// unchanged, so a row-number resume keeps addressing exactly one row.
func TestRowScopedTargetStillRequiresExactRow(t *testing.T) {
	target := providerSessionTarget{SessionID: "wa-1", ProviderRowKey: "file-a", PID: 42}
	if !target.matchesWorkspaceItem(workspaceItem{SessionID: "wa-1", ProviderRowKey: "file-a", PID: 42}) {
		t.Fatal("row-scoped target must match its exact row")
	}
	if target.matchesWorkspaceItem(workspaceItem{SessionID: "wa-1", ProviderRowKey: "file-b", PID: 42}) {
		t.Fatal("row-scoped target must not match a different row key")
	}
	if target.matchesWorkspaceItem(workspaceItem{SessionID: "wa-1", ProviderRowKey: "file-a", PID: 43}) {
		t.Fatal("row-scoped target must not match a different PID")
	}
}

// TestInspectReportsLiveWhenAnyRowOfTheSessionIsLive proves the scan does not
// return on the first non-live row. Returning early would hide a live sibling and
// let resume target a session that is still running, which is the one thing the
// resume gate exists to prevent.
func TestInspectReportsLiveWhenAnyRowOfTheSessionIsLive(t *testing.T) {
	runner := &fakeRunner{out: []byte(`{"items":[
		{"session_id":"wa-1","filename":"file-a","process_generation":null,"status":"Idle"},
		{"session_id":"wa-1","filename":"file-b","process_generation":"g7","status":"Running"}
	]}`)}
	a := newTestAdapter(t, runner)
	mapping, err := a.ResolveProviderSessionHandle(context.Background(), "wa-1")
	if err != nil {
		t.Fatal(err)
	}
	result, err := a.Inspect(context.Background(), adapter.InspectRequest{Target: protocol.CommandTarget{Kind: "session", ResourceID: mapping.ResourceID}})
	if err != nil {
		t.Fatal(err)
	}
	if !result.Found {
		t.Fatal("session must be found")
	}
	if !result.Live {
		t.Fatal("a live row of the session must make the target live")
	}
	if result.ProviderGeneration != "g7" {
		t.Fatalf("generation = %q, want g7", result.ProviderGeneration)
	}
}

// TestInspectReportsFoundNotLiveWhenNoRowIsLive proves a session whose records are
// all unverified is found but not live, which is exactly the state resume exists
// for.
func TestInspectReportsFoundNotLiveWhenNoRowIsLive(t *testing.T) {
	runner := &fakeRunner{out: []byte(`{"items":[
		{"session_id":"wa-1","filename":"file-a","process_generation":null,"status":"Idle"}
	]}`)}
	a := newTestAdapter(t, runner)
	mapping, err := a.ResolveProviderSessionHandle(context.Background(), "wa-1")
	if err != nil {
		t.Fatal(err)
	}
	result, err := a.Inspect(context.Background(), adapter.InspectRequest{Target: protocol.CommandTarget{Kind: "session", ResourceID: mapping.ResourceID}})
	if err != nil {
		t.Fatal(err)
	}
	if !result.Found || result.Live {
		t.Fatalf("found=%v live=%v, want found and not live", result.Found, result.Live)
	}
}

// TestInspectReportsAbsentWhenProviderListsNoRow proves an empty targeted result is
// reported as absence rather than as a malformed report, so the Endpoint can tell
// "the provider does not list it" from "the provider failed".
func TestInspectReportsAbsentWhenProviderListsNoRow(t *testing.T) {
	runner := &fakeRunner{out: []byte(`{"items":[]}`)}
	a := newTestAdapter(t, runner)
	mapping, err := a.ResolveProviderSessionHandle(context.Background(), "wa-1")
	if err != nil {
		t.Fatal(err)
	}
	result, err := a.Inspect(context.Background(), adapter.InspectRequest{Target: protocol.CommandTarget{Kind: "session", ResourceID: mapping.ResourceID}})
	if err != nil {
		t.Fatal(err)
	}
	if result.Found || result.Live {
		t.Fatalf("found=%v live=%v, want neither", result.Found, result.Live)
	}
}

// TestHistoryMappingDecodesAsSessionScoped proves a history row mints a key the
// adapter can decode. The previous bare session identifier was rejected, so a
// history-only session could not be resumed at all.
func TestHistoryMappingDecodesAsSessionScoped(t *testing.T) {
	runner := &fakeRunner{out: []byte(`[{"session_id":"wa-9","session_name":"old","status":"Idle","no":1}]`)}
	a := newTestAdapter(t, runner)
	result, err := a.History(context.Background(), protocol.HistoryQuery{})
	if err != nil {
		t.Fatal(err)
	}
	if len(result.Rows) != 1 {
		t.Fatalf("rows = %d, want 1", len(result.Rows))
	}
	mapping, err := a.mapper.LookupResourceID(context.Background(), result.Rows[0].ResourceID)
	if err != nil {
		t.Fatal(err)
	}
	target, err := decodeProviderSessionKey(mapping.ProviderKey)
	if err != nil {
		t.Fatalf("history mapping must decode: %v", err)
	}
	if target.SessionID != "wa-9" || !target.SessionScoped {
		t.Fatalf("history mapping = %+v, want session-scoped wa-9", target)
	}
}

// TestHistoryAndHandleResolveToOneIdentity proves a history row and an
// operator-typed handle for the same session share one resource ID. Two identities
// for one session would let a resume address a mapping that discovery never
// refreshes.
func TestHistoryAndHandleResolveToOneIdentity(t *testing.T) {
	runner := &fakeRunner{out: []byte(`[{"session_id":"wa-9","session_name":"old","status":"Idle","no":1}]`)}
	a := newTestAdapter(t, runner)
	result, err := a.History(context.Background(), protocol.HistoryQuery{})
	if err != nil {
		t.Fatal(err)
	}
	handleMapping, err := a.ResolveProviderSessionHandle(context.Background(), "wa-9")
	if err != nil {
		t.Fatal(err)
	}
	if result.Rows[0].ResourceID != handleMapping.ResourceID {
		t.Fatalf("history ID %q and handle ID %q must be one identity", result.Rows[0].ResourceID, handleMapping.ResourceID)
	}
}
