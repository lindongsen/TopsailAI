package tui

import (
	"context"
	"errors"
	"strings"
	"sync"
	"testing"

	"topsailai_agent_cluster/internal/protocol"
)

// resumeScopeStub serves the history seam, the forced-collection seam and the
// streaming seam together, so a test can prove the whole composed path: the
// resume is admitted, the collection mints the generation, the scope moves into
// the session and the tail is armed for the identity the collection reported.
type resumeScopeStub struct {
	*interactiveHistoryStub
	mu            sync.Mutex
	refreshCalls  []string
	fresh         map[string]protocol.InventoryReport
	refreshErr    error
	follows       []outputRequest
	followStarts  int
	steps         []string
	commandResult map[string]any
}

// GetCommand serves the durable receipt the resume produced, so a test can state
// whether the effect was applied without changing the shared stub.
func (s *resumeScopeStub) GetCommand(context.Context, string) (map[string]any, error) {
	if s.commandResult != nil {
		return s.commandResult, nil
	}
	return map[string]any{"status": string(protocol.StatusFinished), "effect_certainty": string(protocol.EffectAcknowledged)}, nil
}

// newResumeScopeStub serves one endpoint whose history holds one resumable row
// and whose current inventory proves that row is not live, which is exactly the
// state resume authorizes on.
func newResumeScopeStub() *resumeScopeStub {
	return &resumeScopeStub{
		interactiveHistoryStub: historyScenarioStub(
			[]protocol.HistoryRow{{ProviderSessionID: "wa-past", ProviderDisplayName: "past work", Resumable: true, ResourceID: "res-past"}},
			historyReport(),
		),
		fresh: make(map[string]protocol.InventoryReport),
	}
}

// RefreshInventory records the forced collection and its position in the
// automatic sequence, so a test can prove the entry happens after the collection
// rather than before it.
func (s *resumeScopeStub) RefreshInventory(_ context.Context, endpointID string) (protocol.InventoryReport, error) {
	s.mu.Lock()
	s.refreshCalls = append(s.refreshCalls, endpointID)
	s.steps = append(s.steps, "refresh")
	s.mu.Unlock()
	if s.refreshErr != nil {
		return protocol.InventoryReport{}, s.refreshErr
	}
	report, ok := s.fresh[endpointID]
	if !ok {
		return protocol.InventoryReport{}, errors.New("missing fresh inventory")
	}
	return report, nil
}

// FollowOutput records the request and returns a stream that stays open until the
// caller stops it, so an armed tail is observable instead of ending at once.
func (s *resumeScopeStub) FollowOutput(_ context.Context, endpointID, resourceID, generation string, maxBytes, maxLines int) (<-chan protocol.OutputFollowRecord, error) {
	s.mu.Lock()
	s.followStarts++
	s.follows = append(s.follows, outputRequest{endpointID: endpointID, resourceID: resourceID, generation: generation, maxBytes: maxBytes, maxLines: maxLines})
	s.steps = append(s.steps, "follow")
	s.mu.Unlock()
	return make(chan protocol.OutputFollowRecord), nil
}

func (s *resumeScopeStub) followRequests() []outputRequest {
	s.mu.Lock()
	defer s.mu.Unlock()
	return append([]outputRequest(nil), s.follows...)
}

func (s *resumeScopeStub) followCount() int {
	s.mu.Lock()
	defer s.mu.Unlock()
	return s.followStarts
}

func (s *resumeScopeStub) automaticSteps() []string {
	s.mu.Lock()
	defer s.mu.Unlock()
	return append([]string(nil), s.steps...)
}

func (s *resumeScopeStub) forcedCollections() []string {
	s.mu.Lock()
	defer s.mu.Unlock()
	return append([]string(nil), s.refreshCalls...)
}

// resumedInventory is the committed document a successful resume produces: the
// session the collection now proves a process holds.
func resumedInventory(generation string) protocol.InventoryReport {
	return protocol.InventoryReport{
		ReportComplete:   true,
		CollectionStatus: protocol.CollectionSucceeded,
		Adapters:         []protocol.AdapterSummary{{AdapterID: "adapter-1", DataKnown: true, CollectionStatus: protocol.CollectionSucceeded}},
		Sessions: []protocol.Session{{
			ClusterSessionID:    "res-past",
			ProviderSessionID:   "wa-past",
			ProviderDisplayName: "past work",
			AdapterID:           "adapter-1",
			ProviderGeneration:  generation,
			State:               "running",
			CollectionStatus:    protocol.CollectionSucceeded,
		}},
	}
}

// resumeScopeInput is one confirmed resume followed by a quit, so the prompt
// after the resume is the one that carries the entered scope and the armed tail.
var resumeScopeInput = []string{"history endpoint-1", "resume 1", "y", "exit"}

// TestUnitResumeEntersTheResumedSessionScope proves a completed resume moves the
// REPL into the session it started, so the operator does not have to type cd
// afterwards. The prompt is the assertion because it is the only surface that
// states the current scope.
func TestUnitResumeEntersTheResumedSessionScope(t *testing.T) {
	stub := newResumeScopeStub()
	stub.fresh["endpoint-1"] = resumedInventory("generation-new")
	output, diagnostics, _ := runWatchREPL(t, stub, resumeScopeInput, nil)
	if diagnostics != "" {
		t.Fatalf("unexpected diagnostics: %q", diagnostics)
	}
	if got := lastPrompt(output); got != "session[host-one/wa-past]>" {
		t.Fatalf("final prompt=%q, want the resumed session scope", got)
	}
}

// TestUnitResumeEntersAfterTheCollection proves the entry happens after the
// forced collection, which is the opposite of the post-send order. Resume submits
// no generation, so the generation only exists once a collection proves a process
// holds the session; entering earlier would bind an empty generation, which the
// Endpoint rejects with generation_required.
func TestUnitResumeEntersAfterTheCollection(t *testing.T) {
	stub := newResumeScopeStub()
	stub.fresh["endpoint-1"] = resumedInventory("generation-new")
	if _, diagnostics, _ := runWatchREPL(t, stub, resumeScopeInput, nil); diagnostics != "" {
		t.Fatalf("unexpected diagnostics: %q", diagnostics)
	}
	steps := waitAutomaticSteps(t, stub, 2)
	if len(steps) != 2 || steps[0] != "refresh" || steps[1] != "follow" {
		t.Fatalf("automatic steps=%v, want refresh then follow", steps)
	}
}

// TestUnitResumeCollectsOnlyTheResumedEndpoint proves the entry collects the one
// endpoint the resume addressed. A workspace-wide collection would multiply
// provider discovery cost by the fleet size for a single resume.
func TestUnitResumeCollectsOnlyTheResumedEndpoint(t *testing.T) {
	stub := newResumeScopeStub()
	stub.fresh["endpoint-1"] = resumedInventory("generation-new")
	if _, diagnostics, _ := runWatchREPL(t, stub, resumeScopeInput, nil); diagnostics != "" {
		t.Fatalf("unexpected diagnostics: %q", diagnostics)
	}
	if calls := stub.forcedCollections(); len(calls) != 1 || calls[0] != "endpoint-1" {
		t.Fatalf("forced collections=%v, want exactly the resumed endpoint", calls)
	}
}

// TestUnitResumeArmsTheTailForTheCollectedIdentity proves the entry arms one live
// tail bound to the identity the collection minted, so the operator watches the
// resumed session without typing logf.
func TestUnitResumeArmsTheTailForTheCollectedIdentity(t *testing.T) {
	stub := newResumeScopeStub()
	stub.fresh["endpoint-1"] = resumedInventory("generation-new")
	output, diagnostics, _ := runWatchREPL(t, stub, resumeScopeInput, nil)
	if diagnostics != "" {
		t.Fatalf("unexpected diagnostics: %q", diagnostics)
	}
	requests := waitFollowRequests(t, stub, 1)
	if len(requests) != 1 {
		t.Fatalf("follow requests=%+v, want exactly one", requests)
	}
	request := requests[0]
	if request.endpointID != "endpoint-1" || request.resourceID != "res-past" || request.generation != "generation-new" {
		t.Fatalf("wrong follow identity tuple: %+v", request)
	}
	if !strings.Contains(output, "res-past (any key stops)") {
		t.Fatalf("resume did not announce the live tail: %q", output)
	}
}

// TestUnitResumeEntrySuppressesTheStaleRowNotice proves a successful entry does
// not also tell the operator to re-render a table they have left. The transition
// clears both row namespaces, so the notice would describe a step that no longer
// applies.
func TestUnitResumeEntrySuppressesTheStaleRowNotice(t *testing.T) {
	stub := newResumeScopeStub()
	stub.fresh["endpoint-1"] = resumedInventory("generation-new")
	output, diagnostics, _ := runWatchREPL(t, stub, resumeScopeInput, nil)
	if diagnostics != "" {
		t.Fatalf("unexpected diagnostics: %q", diagnostics)
	}
	if strings.Contains(output, "history row numbers are stale after resume") {
		t.Fatalf("entry printed the stale row notice: %q", output)
	}
}

// TestUnitResumeEntrySkipsAnUnverifiedSession proves a collection that reports the
// resumed session without a generation leaves the scope unchanged and says why.
// Entering would bind an empty generation, and a tail bound to it would be refused
// by the Endpoint, so naming the next collection is the only useful answer.
func TestUnitResumeEntrySkipsAnUnverifiedSession(t *testing.T) {
	stub := newResumeScopeStub()
	stub.fresh["endpoint-1"] = resumedInventory("")
	output, diagnostics, _ := runWatchREPL(t, stub, resumeScopeInput, nil)
	if diagnostics != "" {
		t.Fatalf("unexpected diagnostics: %q", diagnostics)
	}
	want := "resume completed; automatic entry skipped: the resumed session has no verified generation; run list after the next collection"
	if !strings.Contains(output, want) {
		t.Fatalf("output=%q, want %q", output, want)
	}
	if got := lastPrompt(output); got == "session[host-one/wa-past]>" {
		t.Fatalf("prompt=%q, want the scope to stay unchanged", got)
	}
	// The scope did not move, so the numbers really are stale and the notice must
	// still be printed.
	if !strings.Contains(output, "history row numbers are stale after resume") {
		t.Fatalf("missing row invalidation notice: %q", output)
	}
	settleFollowCount(t, stub, 0)
}

// TestUnitResumeEntryReportsAFailedCollection proves a failed collection is a
// diagnostic rather than a command failure. The resume already succeeded, so
// reporting an error would deny an admission that happened.
func TestUnitResumeEntryReportsAFailedCollection(t *testing.T) {
	stub := newResumeScopeStub()
	stub.refreshErr = errors.New("endpoint unavailable")
	output, diagnostics, _ := runWatchREPL(t, stub, resumeScopeInput, nil)
	if diagnostics != "" {
		t.Fatalf("unexpected diagnostics: %q", diagnostics)
	}
	want := "resume completed; automatic collection failed: endpoint unavailable"
	if !strings.Contains(output, want) {
		t.Fatalf("output=%q, want %q", output, want)
	}
	if got := lastPrompt(output); got == "session[host-one/wa-past]>" {
		t.Fatalf("prompt=%q, want the scope to stay unchanged", got)
	}
	settleFollowCount(t, stub, 0)
}

// TestUnitResumeEntrySkipsANotYetVisibleSession proves a collection that omits the
// resumed session enters nothing and says so. A background resume is reported as
// submitted, so an immediate collection can legitimately miss the session; polling
// here would turn one resume into a discovery loop.
func TestUnitResumeEntrySkipsANotYetVisibleSession(t *testing.T) {
	stub := newResumeScopeStub()
	stub.fresh["endpoint-1"] = historyReport()
	output, diagnostics, _ := runWatchREPL(t, stub, resumeScopeInput, nil)
	if diagnostics != "" {
		t.Fatalf("unexpected diagnostics: %q", diagnostics)
	}
	want := "resume completed; automatic entry skipped: session res-past is not visible yet; run list after the next collection"
	if !strings.Contains(output, want) {
		t.Fatalf("output=%q, want %q", output, want)
	}
	settleFollowCount(t, stub, 0)
}

// TestUnitResumeEntryIsSilentWithoutTheCollectionSeam proves a client that cannot
// force a collection keeps its previous behaviour silently. It cannot mint the
// generation the entry needs, and a diagnostic would turn a working resume into a
// noisy one on every such client.
func TestUnitResumeEntryIsSilentWithoutTheCollectionSeam(t *testing.T) {
	stub := historyScenarioStub(
		[]protocol.HistoryRow{{ProviderSessionID: "wa-past", Resumable: true, ResourceID: "res-past"}},
		historyReport(),
	)
	output, diagnostics := runScope(t, stub, "history endpoint-1\nresume 1\ny\nexit\n", ColorPolicy{})
	if diagnostics != "" {
		t.Fatalf("unexpected diagnostics: %q", diagnostics)
	}
	if strings.Contains(output, "resume completed") {
		t.Fatalf("a client without the seam reported an automatic step: %q", output)
	}
	if !strings.Contains(output, "history row numbers are stale after resume") {
		t.Fatalf("missing row invalidation notice: %q", output)
	}
}

// TestUnitResumeEntrySkipsARejectedResume proves a receipt that proves the effect
// was not applied enters nothing. No runtime was started, so there is no session
// to enter, and the predicate is the same one the post-start refresh uses.
func TestUnitResumeEntrySkipsARejectedResume(t *testing.T) {
	stub := newResumeScopeStub()
	stub.fresh["endpoint-1"] = resumedInventory("generation-new")
	stub.commandResult = map[string]any{"status": string(protocol.StatusRejected), "effect_certainty": string(protocol.EffectNotApplied)}
	output, diagnostics, _ := runWatchREPL(t, stub, resumeScopeInput, nil)
	if diagnostics != "" {
		t.Fatalf("unexpected diagnostics: %q", diagnostics)
	}
	if calls := stub.forcedCollections(); len(calls) != 0 {
		t.Fatalf("forced collections=%v, want none after a rejected resume", calls)
	}
	if got := lastPrompt(output); got == "session[host-one/wa-past]>" {
		t.Fatalf("prompt=%q, want the scope to stay unchanged", got)
	}
	settleFollowCount(t, stub, 0)
}
