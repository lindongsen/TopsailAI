package main

import (
	"context"
	"encoding/json"
	"strings"
	"testing"
)

// unattributedRowDocument is one provider workspace response containing a row the
// provider could not attribute to a session.
//
// The row is real: the provider publishes a stdout file for a process it did not
// start as a session, so it reports an empty session_id. The healthy row is present
// so a test can prove the unattributed row neither disappears nor takes the healthy
// row with it.
const unattributedRowDocument = `{"items":[` +
	`{"session_id":"s-1","filename":"20261117162228.2557392.session.stdout","pid":2557392,"process_generation":7,"state":"input","session_name":"demo"},` +
	`{"session_id":"","filename":"topsailai.916395.session.stdout","pid":916395,"state":"running"}` +
	`],"total":2}`

// TestDiscoverAcceptsRowWithoutSessionID proves one unattributed row no longer
// aborts the whole inventory.
//
// The provider legitimately publishes a stdout file it cannot attribute to a
// session. Refusing that row made discovery fail, and the Endpoint then reported the
// entire node as failed/stale even though every other session was healthy. The
// assertion counts both observations, because a fix that merely stopped failing
// would still have dropped the healthy row.
func TestDiscoverAcceptsRowWithoutSessionID(t *testing.T) {
	r := &scriptedRunner{t: t, answers: map[string][]runnerAnswer{"workspace\x00list\x00--json\x00--local\x00--include-runtime": answer(unattributedRowDocument)}}
	p := fixedProvider(r)
	response := p.dispatch(context.Background(), validRequest(functionDiscover))
	if !response.OK || response.Discovery == nil {
		t.Fatalf("response=%+v", response)
	}
	if len(response.Discovery.Observations) != 2 {
		t.Fatalf("observations=%d, want 2: %+v", len(response.Discovery.Observations), response.Discovery.Observations)
	}
	if !response.Discovery.Complete {
		t.Fatalf("complete=false, want true: %+v", response.Discovery)
	}
	var unattributed *providerObservation
	for index := range response.Discovery.Observations {
		observation := &response.Discovery.Observations[index]
		var attributes sessionAttributes
		if err := json.Unmarshal(observation.Attributes, &attributes); err != nil {
			t.Fatalf("attributes=%s err=%v", observation.Attributes, err)
		}
		if attributes.ProviderSessionID == "" {
			unattributed = observation
		}
	}
	if unattributed == nil {
		t.Fatal("unattributed row was dropped from discovery")
	}
	if unattributed.ProviderResourceKey == "" {
		t.Fatal("unattributed row has no provider resource key")
	}
	if unattributed.State != "unknown" || unattributed.StateReason != "liveness_unverified" {
		t.Fatalf("state=%q reason=%q, want unknown/liveness_unverified", unattributed.State, unattributed.StateReason)
	}
}

// TestProviderSessionKeyRequiresOnlyFilename proves the row identity rule.
//
// The filename is the only identity a row must carry, because it is the only field
// that names the file the row describes. A row with no session identifier must still
// mint a key, and a row with no filename must not, because a key without a filename
// would name nothing.
func TestProviderSessionKeyRequiresOnlyFilename(t *testing.T) {
	key, err := providerSessionKey(workspaceItem{ProviderRowKey: "topsailai.916395.session.stdout"})
	if err != nil {
		t.Fatalf("unattributed row was refused: %v", err)
	}
	if !strings.HasPrefix(key, sessionRowProviderKeyPrefix) {
		t.Fatalf("key=%q, want the row prefix", key)
	}
	if _, err := providerSessionKey(workspaceItem{SessionID: "s-1"}); err == nil {
		t.Fatal("a row without a filename was accepted")
	}
}

// TestProviderSessionKeyKeepsAttributedRowIdentity proves the relaxation did not
// renumber rows that already had a session identifier.
//
// A changed key would orphan every existing Cluster resource mapping, so the
// attributed row must keep exactly the digest it had before the rule changed.
func TestProviderSessionKeyKeepsAttributedRowIdentity(t *testing.T) {
	item := workspaceItem{SessionID: "s-1", ProviderRowKey: "row", IsTask: false}
	key, err := providerSessionKey(item)
	if err != nil {
		t.Fatal(err)
	}
	// The digest is over the same three fields as before, so the key is unchanged.
	expected, err := stableProviderKey(sessionRowProviderKeyPrefix, struct {
		SessionID      string `json:"session_id"`
		ProviderRowKey string `json:"provider_row_key"`
		IsTask         bool   `json:"is_task"`
	}{"s-1", "row", false})
	if err != nil {
		t.Fatal(err)
	}
	if key != expected {
		t.Fatalf("key=%q, want %q", key, expected)
	}
}

// TestUnattributedRowIsNotMatchedBySessionKey proves a session-scoped target cannot
// claim an unattributed row.
//
// A session-scoped key names a session, and an unattributed row belongs to no
// session. Reporting an error instead of no match would let one unattributed row
// abort the resolution of every session-scoped key, which is a wider failure than
// the row itself.
func TestUnattributedRowIsNotMatchedBySessionKey(t *testing.T) {
	sessionKey, err := sessionProviderKey("s-1")
	if err != nil {
		t.Fatal(err)
	}
	matched, err := matchesSessionKey(sessionKey, workspaceItem{ProviderRowKey: "topsailai.916395.session.stdout"})
	if err != nil {
		t.Fatalf("unattributed row aborted session resolution: %v", err)
	}
	if matched {
		t.Fatal("unattributed row matched a session-scoped key")
	}
	matched, err = matchesSessionKey(sessionKey, workspaceItem{SessionID: "s-1", ProviderRowKey: "row"})
	if err != nil || !matched {
		t.Fatalf("attributed row did not match its session: matched=%v err=%v", matched, err)
	}
}

// TestUnattributedRowCannotBeOperated proves the unattributed row stays listable
// without becoming operable.
//
// Every provider operation passes the session identifier as its selector. An empty
// selector would be rejected by the provider or, worse, be read as "no filter" and
// address a different session, so the refusal must happen before any argv exists.
func TestUnattributedRowCannotBeOperated(t *testing.T) {
	operations := []string{
		operationMessageSend, operationContextInject, operationAgentStop,
		operationAgentDriveStart, operationAgentDriveStop, operationAgentResume,
		operationWorkspaceClean, operationAgentModelSelect, operationExecutionInterrupt,
	}
	for _, operation := range operations {
		_, err := mutationArgs(mutationInvocation{Operation: operation, Generation: "7", Payload: json.RawMessage(`{"message":"hi"}`)})
		if err == nil {
			t.Fatalf("operation %q accepted an empty session identifier", operation)
		}
		if !strings.Contains(err.Error(), "requires a session identifier") {
			t.Fatalf("operation %q error=%v, want a session-identifier refusal", operation, err)
		}
	}
}

// TestControlActionRequiresSessionIdentifier proves the control path refuses an
// empty selector too.
//
// Control actions build their argv through the catalog rather than through
// mutationArgs, so a guard in only one of the two paths would leave the other one
// able to emit an empty selector.
func TestControlActionRequiresSessionIdentifier(t *testing.T) {
	catalog := controlCatalog{actions: map[string]controlAction{}, order: nil}
	_, err := catalog.args(controlOperationPrefix+"soft_interrupt", "", json.RawMessage(`{}`))
	if err == nil {
		t.Fatal("control action accepted an empty session identifier")
	}
	if !strings.Contains(err.Error(), "requires a session identifier") {
		t.Fatalf("error=%v, want a session-identifier refusal", err)
	}
}

// TestUnattributedRowCannotBeRead proves the unattributed row stays listable
// without becoming readable.
//
// The provider CLI takes the session identifier as its selector, so an empty one
// would be rejected or, worse, read as "no filter" and return another session's
// output. The row is resolved through discovery, because a filename always parses
// back to some session identifier and therefore cannot prove an unattributed key.
// The assertion is that resolution succeeds and the refusal comes from the
// addressability guard, not from a resolution failure.
func TestUnattributedRowCannotBeRead(t *testing.T) {
	runner := &scriptedRunner{t: t, answers: map[string][]runnerAnswer{
		strings.Join([]string{"workspace", "list", "--json", "--local"}, "\x00"): answer(unattributedRowDocument),
	}}
	provider := newProvider(runner, controlCatalog{}, supportedPlatform, t.TempDir())

	key, err := providerSessionKey(workspaceItem{ProviderRowKey: "topsailai.916395.session.stdout"})
	if err != nil {
		t.Fatal(err)
	}
	if _, err := provider.resolveReadTarget(context.Background(), &target{
		ResourceKind: resourceSession, ProviderResourceKey: key,
	}); err == nil {
		t.Fatal("an unattributed row was readable")
	} else if !strings.Contains(err.Error(), "requires a session identifier") {
		t.Fatalf("error=%v, want a session-identifier refusal", err)
	}
	if len(runner.calls) != 1 {
		t.Fatalf("discovery calls = %d, want 1", len(runner.calls))
	}
}

// TestDiscoverSkipsAnUnmappableRow proves one row that cannot be mapped no longer
// aborts the whole inventory.
//
// The unattributed row is now mappable, so this uses a row with no filename at all:
// that row has no identity and cannot become a resource. Returning the error made
// every healthy row in the same response disappear, which is how one bad row turned
// a whole node into failed/stale. The cycle must instead be reported incomplete
// while still carrying the rows that did map.
func TestDiscoverSkipsAnUnmappableRow(t *testing.T) {
	document := `{"items":[` +
		`{"session_id":"s-1","filename":"20261117162228.2557392.session.stdout","pid":2557392,"process_generation":7,"state":"input"},` +
		`{"session_id":"s-2","filename":"","pid":4242,"state":"running"}` +
		`],"total":2}`
	runner := &scriptedRunner{t: t, answers: map[string][]runnerAnswer{
		strings.Join([]string{"workspace", "list", "--json", "--local", "--include-runtime"}, "\x00"): answer(document),
	}}
	provider := newProvider(runner, controlCatalog{}, supportedPlatform, t.TempDir())

	result, err := provider.discover(context.Background())
	if err != nil {
		t.Fatalf("one unmappable row aborted discovery: %v", err)
	}
	if result.Complete {
		t.Fatal("a cycle that skipped a row claimed completeness")
	}
	if len(result.Observations) != 1 {
		t.Fatalf("observations = %d, want the one mappable row", len(result.Observations))
	}
	if !strings.Contains(string(result.Observations[0].Attributes), `"provider_session_id":"s-1"`) {
		t.Fatalf("kept the wrong row: %s", result.Observations[0].Attributes)
	}
}
