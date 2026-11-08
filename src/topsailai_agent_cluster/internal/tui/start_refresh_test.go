package tui

import (
	"context"
	"errors"
	"strings"
	"testing"

	"topsailai_agent_cluster/internal/protocol"
)

// startRefreshStub overrides the durable command result, so a test can pin the
// receipt's effect certainty without changing the shared interactive fixture.
type startRefreshStub struct {
	*refreshStub
	commandResult map[string]any
}

func (s *startRefreshStub) GetCommand(context.Context, string) (map[string]any, error) {
	return s.commandResult, nil
}

// newStartRefreshStub serves two endpoints and a finished command receipt.
func newStartRefreshStub() *startRefreshStub {
	return &startRefreshStub{
		refreshStub:   refreshScopeStub(),
		commandResult: map[string]any{"status": string(protocol.StatusFinished), "effect_certainty": string(protocol.EffectAcknowledged)},
	}
}

const startRefreshInput = "start endpoint-1 compatibility --profile p --profile-revision r\nexit\n"

// TestStartRefreshesOnlyTheStartedEndpoint proves a successful start forces one
// collection for the Endpoint that accepted it, so the next list already contains
// the launched session instead of waiting for the periodic collection. A
// workspace-wide collection would multiply provider discovery cost by the fleet
// size for a single launch, so the other Endpoint must not be collected.
func TestStartRefreshesOnlyTheStartedEndpoint(t *testing.T) {
	stub := newStartRefreshStub()
	output, diagnostics := runScope(t, stub, startRefreshInput, ColorPolicy{})
	if diagnostics != "" {
		t.Fatalf("unexpected diagnostics: %q", diagnostics)
	}
	if len(stub.refreshCalls) != 1 || stub.refreshCalls[0] != "endpoint-1" {
		t.Fatalf("forced collections=%v, want exactly the started endpoint", stub.refreshCalls)
	}
	if !strings.Contains(output, "CommandID: cmd-1") {
		t.Fatalf("start receipt missing: %q", output)
	}
}

// TestStartRendersTheFreshlyCollectedSession proves the post-start table comes from
// the forced collection, so the operator sees the launched session immediately.
func TestStartRendersTheFreshlyCollectedSession(t *testing.T) {
	stub := newStartRefreshStub()
	stub.fresh["endpoint-1"] = scopeInventory("fresh-session", "fresh-generation")
	output, diagnostics := runScope(t, stub, startRefreshInput, ColorPolicy{})
	if diagnostics != "" {
		t.Fatalf("unexpected diagnostics: %q", diagnostics)
	}
	if !strings.Contains(output, "provider-fresh-session") {
		t.Fatalf("post-start table did not show the freshly collected session: %q", output)
	}
}

// TestStartRefreshFailureDoesNotMaskAdmission proves a failed post-start collection
// is reported as a diagnostic while the successful admission still stands. Turning
// it into a command error would tell the operator the start failed when it did not.
func TestStartRefreshFailureDoesNotMaskAdmission(t *testing.T) {
	stub := newStartRefreshStub()
	stub.refreshErrors["endpoint-1"] = errors.New("endpoint unavailable")
	output, diagnostics := runScope(t, stub, startRefreshInput, ColorPolicy{})
	if diagnostics != "" {
		t.Fatalf("refresh failure must not become a command error: %q", diagnostics)
	}
	if !strings.Contains(output, "CommandID: cmd-1") {
		t.Fatalf("start receipt missing after refresh failure: %q", output)
	}
	if !strings.Contains(output, "refresh after start failed") || !strings.Contains(output, "endpoint unavailable") {
		t.Fatalf("refresh failure was not reported: %q", output)
	}
}

// TestStartWithoutForcedCollectionKeepsReadOnlyBehaviour proves a client without the
// forced-collection seam still starts and renders the receipt, so the optional seam
// never becomes a hard requirement.
func TestStartWithoutForcedCollectionKeepsReadOnlyBehaviour(t *testing.T) {
	stub := &interactiveStub{
		endpoints: []protocol.Endpoint{{EndpointID: "endpoint-1", Hostname: "host-one"}},
		reports:   map[string]protocol.InventoryReport{"endpoint-1": scopeInventory("res-1", "generation-1")},
	}
	output, diagnostics := runScope(t, stub, startRefreshInput, ColorPolicy{})
	if diagnostics != "" {
		t.Fatalf("unexpected diagnostics: %q", diagnostics)
	}
	if !strings.Contains(output, "CommandID: cmd-1") {
		t.Fatalf("start receipt missing without the refresh seam: %q", output)
	}
	if strings.Contains(output, "refresh after start failed") {
		t.Fatalf("a client without the seam must not report a refresh failure: %q", output)
	}
}

// TestStartNotAppliedDoesNotRefresh proves a request the provider did not apply is
// not collected, because no session was created and the collection would only add
// provider cost without changing the inventory.
func TestStartNotAppliedDoesNotRefresh(t *testing.T) {
	stub := newStartRefreshStub()
	stub.commandResult = map[string]any{"status": string(protocol.StatusFinished), "effect_certainty": string(protocol.EffectNotApplied)}
	output, diagnostics := runScope(t, stub, startRefreshInput, ColorPolicy{})
	if diagnostics != "" {
		t.Fatalf("unexpected diagnostics: %q", diagnostics)
	}
	if len(stub.refreshCalls) != 0 {
		t.Fatalf("forced collections=%v, want none for a not-applied request", stub.refreshCalls)
	}
	if !strings.Contains(output, "CommandID: cmd-1") {
		t.Fatalf("start receipt missing: %q", output)
	}
}

// inventoryWithSessions builds a report holding the given sessions, so a test can
// model a collection that either does or does not contain the launched session.
func inventoryWithSessions(sessionIDs ...string) protocol.InventoryReport {
	report := scopeInventory(sessionIDs[0], "generation-1")
	for _, sessionID := range sessionIDs[1:] {
		report.Sessions = append(report.Sessions, protocol.Session{
			SessionID:         sessionID,
			ProviderSessionID: "provider-" + sessionID,
			AdapterID:         "adapter-1",
			Generation:        "generation-1",
			State:             "running",
			CollectionStatus:  protocol.CollectionSucceeded,
		})
	}
	return report
}

// acknowledgedResult is a finished receipt whose effect certainty is acknowledged,
// which is the only case that triggers a post-start collection.
func acknowledgedResult() map[string]any {
	return map[string]any{"status": string(protocol.StatusFinished), "effect_certainty": string(protocol.EffectAcknowledged)}
}

// TestStartReportsSessionNotYetVisible proves a collection that omits the launched
// session is reported as pending visibility instead of a failure. The provider
// reports a background launch as submitted, and a session only becomes routable
// once its process is observed holding the output file, so an immediate collection
// can legitimately miss it. Claiming failure would deny a launch that happened.
func TestStartReportsSessionNotYetVisible(t *testing.T) {
	stub := newStartRefreshStub()
	output, diagnostics := runScope(t, stub, startRefreshInput, ColorPolicy{})
	if diagnostics != "" {
		t.Fatalf("unexpected diagnostics: %q", diagnostics)
	}
	if !strings.Contains(output, "session submitted but not yet visible") {
		t.Fatalf("missing pending-visibility notice: %q", output)
	}
	if strings.Contains(output, "refresh after start failed") {
		t.Fatalf("pending visibility must not be reported as a refresh failure: %q", output)
	}
	if !strings.Contains(output, "CommandID: cmd-1") {
		t.Fatalf("start receipt missing: %q", output)
	}
}

// TestStartDoesNotClaimNotYetVisibleWhenSessionAppears proves the notice is absent
// once the collection actually returns the launched session, so a visible launch is
// never described as pending.
func TestStartDoesNotClaimNotYetVisibleWhenSessionAppears(t *testing.T) {
	stub := newStartRefreshStub()
	stub.fresh["endpoint-1"] = inventoryWithSessions("res-1", "res-new")
	output, diagnostics := runScope(t, stub, startRefreshInput, ColorPolicy{})
	if diagnostics != "" {
		t.Fatalf("unexpected diagnostics: %q", diagnostics)
	}
	if strings.Contains(output, "not yet visible") {
		t.Fatalf("a visible launch was reported as pending: %q", output)
	}
	if !strings.Contains(output, "provider-res-new") {
		t.Fatalf("the launched session was not rendered: %q", output)
	}
}

// baselineFailureStub fails only the first projection read, which is the baseline
// taken before the forced collection. Later reads succeed, so the refresh path is
// unaffected and the test isolates the unreadable-baseline decision.
type baselineFailureStub struct {
	*startRefreshStub
	calls int
}

func (s *baselineFailureStub) GetInventory(ctx context.Context, endpointID string) (protocol.InventoryReport, error) {
	s.calls++
	if s.calls == 1 {
		return protocol.InventoryReport{}, errors.New("projection unavailable")
	}
	return s.startRefreshStub.GetInventory(ctx, endpointID)
}

// TestStartUnreadableBaselineDoesNotClaimNotYetVisible proves an unreadable
// projection never fabricates a pending-visibility conclusion. Without a baseline
// there is no evidence that the session is missing, so silence is the only honest
// outcome. The forced collection itself supplies the post-refresh document, so the
// baseline is the only projection read.
func TestStartUnreadableBaselineDoesNotClaimNotYetVisible(t *testing.T) {
	stub := &baselineFailureStub{startRefreshStub: newStartRefreshStub()}
	var out strings.Builder
	if err := refreshAfterStart(context.Background(), stub, "endpoint-1", acknowledgedResult(), &out, &out, InteractiveOptions{}); err != nil {
		t.Fatalf("refreshAfterStart: %v", err)
	}
	if strings.Contains(out.String(), "not yet visible") {
		t.Fatalf("unreadable baseline fabricated a pending-visibility claim: %q", out.String())
	}
	if stub.calls != 1 {
		t.Fatalf("projection reads=%d, want only the baseline read", stub.calls)
	}
}
