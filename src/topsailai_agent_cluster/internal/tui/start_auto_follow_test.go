package tui

import (
	"context"
	"errors"
	"strings"
	"sync"
	"testing"

	"topsailai_agent_cluster/internal/protocol"
)

// startAutoFollowStub serves the streaming seam, the forced-collection seam and
// the durable receipt, so a test can prove the automatic post-start step arms a
// live tail for the session the collection minted and still renders the table.
type startAutoFollowStub struct {
	*startRefreshStub
	followMu     sync.Mutex
	follows      []outputRequest
	followStarts int
	steps        []string
}

// newStartAutoFollowStub serves the shared two-endpoint fixture with both seams.
func newStartAutoFollowStub() *startAutoFollowStub {
	return &startAutoFollowStub{startRefreshStub: newStartRefreshStub()}
}

// FollowOutput records the request and returns a stream that stays open until the
// caller stops it, so a started tail is observable instead of ending at once.
func (s *startAutoFollowStub) FollowOutput(ctx context.Context, endpointID, resourceID, generation string, maxBytes, maxLines int) (<-chan protocol.OutputFollowRecord, error) {
	s.followMu.Lock()
	s.followStarts++
	s.follows = append(s.follows, outputRequest{endpointID: endpointID, resourceID: resourceID, generation: generation, maxBytes: maxBytes, maxLines: maxLines})
	s.steps = append(s.steps, "follow")
	s.followMu.Unlock()
	return make(chan protocol.OutputFollowRecord), nil
}

// RefreshInventory records the forced collection and its position in the
// automatic sequence, so a test can prove the tail is armed after the collection
// rather than before it.
func (s *startAutoFollowStub) RefreshInventory(ctx context.Context, endpointID string) (protocol.InventoryReport, error) {
	s.followMu.Lock()
	s.steps = append(s.steps, "refresh")
	s.followMu.Unlock()
	return s.startRefreshStub.RefreshInventory(ctx, endpointID)
}

// followRequests returns the recorded follow requests.
func (s *startAutoFollowStub) followRequests() []outputRequest {
	s.followMu.Lock()
	defer s.followMu.Unlock()
	return append([]outputRequest(nil), s.follows...)
}

// followCount reports how many streams were opened.
func (s *startAutoFollowStub) followCount() int {
	s.followMu.Lock()
	defer s.followMu.Unlock()
	return s.followStarts
}

// automaticSteps returns the recorded automatic steps in order.
func (s *startAutoFollowStub) automaticSteps() []string {
	s.followMu.Lock()
	defer s.followMu.Unlock()
	return append([]string(nil), s.steps...)
}

// launchedInventory is the committed document a successful launch produces: the
// pre-existing session plus the session the collection minted.
func launchedInventory(sessionID, generation string) protocol.InventoryReport {
	report := scopeInventory("res-1", "generation-1")
	report.Sessions = append(report.Sessions, protocol.Session{
		ClusterSessionID:    sessionID,
		ProviderSessionID:   "provider-" + sessionID,
		ProviderDisplayName: "launched work",
		AdapterID:           "adapter-1",
		ProviderGeneration:  generation,
		State:               "running",
		CollectionStatus:    protocol.CollectionSucceeded,
	})
	return report
}

// startAutoFollowInput is one confirmed start followed by a quit, so the prompt
// after the start is the one that carries the armed tail.
var startAutoFollowInput = []string{"start endpoint-1 compatibility --profile p --profile-revision r", "quit"}

// TestUnitStartAutoFollowArmsOneLiveTailForTheLaunchedSession proves a completed
// start arms exactly one live tail, and that it binds the identity the post-start
// collection minted rather than an empty generation. A launched session does not
// exist before the action, so the collection is the only source of that identity.
func TestUnitStartAutoFollowArmsOneLiveTailForTheLaunchedSession(t *testing.T) {
	stub := newStartAutoFollowStub()
	stub.fresh["endpoint-1"] = launchedInventory("res-new", "generation-new")
	output, diagnostics, _ := runWatchREPL(t, stub, startAutoFollowInput, nil)
	if diagnostics != "" {
		t.Fatalf("unexpected diagnostics: %q", diagnostics)
	}
	requests := stub.followRequests()
	if len(requests) != 1 {
		t.Fatalf("follow requests=%+v, want exactly one", requests)
	}
	request := requests[0]
	if request.endpointID != "endpoint-1" || request.resourceID != "res-new" || request.generation != "generation-new" {
		t.Fatalf("wrong follow identity tuple: %+v", request)
	}
	if !strings.Contains(output, "log.follow> res-new (any key stops)") {
		t.Fatalf("start did not announce the live tail: %q", output)
	}
}

// TestUnitStartAutoFollowArmsAfterTheCollection proves the tail is armed after the
// forced collection, which is the opposite of the post-send order. Arming earlier
// would bind an empty generation, because the launched session is minted by the
// collection itself.
func TestUnitStartAutoFollowArmsAfterTheCollection(t *testing.T) {
	stub := newStartAutoFollowStub()
	stub.fresh["endpoint-1"] = launchedInventory("res-new", "generation-new")
	if _, diagnostics, _ := runWatchREPL(t, stub, startAutoFollowInput, nil); diagnostics != "" {
		t.Fatalf("unexpected diagnostics: %q", diagnostics)
	}
	steps := stub.automaticSteps()
	if len(steps) != 2 || steps[0] != "refresh" || steps[1] != "follow" {
		t.Fatalf("automatic steps=%v, want refresh then follow", steps)
	}
}

// TestUnitStartAutoFollowStartsTheStreamOnTheNextPrompt proves the armed intent
// becomes a real stream for the following prompt, so the operator watches the new
// session without typing logf, and that a keypress stops it.
func TestUnitStartAutoFollowStartsTheStreamOnTheNextPrompt(t *testing.T) {
	stub := newStartAutoFollowStub()
	stub.fresh["endpoint-1"] = launchedInventory("res-new", "generation-new")
	_, diagnostics, reader := runWatchREPL(t, stub, startAutoFollowInput, nil)
	if diagnostics != "" {
		t.Fatalf("unexpected diagnostics: %q", diagnostics)
	}
	if stub.followCount() != 1 {
		t.Fatalf("streams opened=%d want=1", stub.followCount())
	}
	sessions, _ := reader.recorded()
	if len(sessions) < 2 {
		t.Fatalf("prompts=%d, want at least two", len(sessions))
	}
	stream := sessions[1]
	if stream == nil {
		t.Fatal("the prompt after the start did not carry a stream")
	}
	labelled, ok := stream.(followStopLabel)
	if !ok {
		t.Fatalf("the armed session does not name itself as a follow: %T", stream)
	}
	if label := labelled.StopLabel(); label != "follow stopped" {
		t.Fatalf("stop label=%q, want the follow wording", label)
	}
	stream.Stop()
}

// TestUnitStartAutoFollowIsBoundedByTheReplDefaults proves the automatic tail
// never requests an unbounded stream, so a launch cannot pull an arbitrary amount
// of provider output into the terminal.
func TestUnitStartAutoFollowIsBoundedByTheReplDefaults(t *testing.T) {
	stub := newStartAutoFollowStub()
	stub.fresh["endpoint-1"] = launchedInventory("res-new", "generation-new")
	if _, diagnostics, _ := runWatchREPL(t, stub, startAutoFollowInput, nil); diagnostics != "" {
		t.Fatalf("unexpected diagnostics: %q", diagnostics)
	}
	requests := stub.followRequests()
	if len(requests) != 1 {
		t.Fatalf("follow requests=%+v, want exactly one", requests)
	}
	if got := requests[0].maxLines; got != DefaultInteractiveMaxLines {
		t.Fatalf("automatic follow maxLines=%d want=%d", got, DefaultInteractiveMaxLines)
	}
	if got := requests[0].maxBytes; got != 64<<10 {
		t.Fatalf("automatic follow maxBytes=%d want=%d", got, 64<<10)
	}
}

// TestUnitStartAutoFollowSkipsANotYetVisibleLaunch proves a collection that omits
// the launched session arms nothing. The provider reports a background launch as
// submitted, so an immediate collection can legitimately miss it; following
// nothing is correct, and polling here would turn one launch into a discovery
// loop.
func TestUnitStartAutoFollowSkipsANotYetVisibleLaunch(t *testing.T) {
	stub := newStartAutoFollowStub()
	output, diagnostics, _ := runWatchREPL(t, stub, startAutoFollowInput, nil)
	if diagnostics != "" {
		t.Fatalf("unexpected diagnostics: %q", diagnostics)
	}
	if stub.followCount() != 0 {
		t.Fatalf("streams opened=%d, want none for a not-yet-visible launch", stub.followCount())
	}
	if !strings.Contains(output, "session submitted but not yet visible") {
		t.Fatalf("missing pending-visibility notice: %q", output)
	}
}

// TestUnitStartAutoFollowSkipsAnUnverifiedLaunch proves a launched session with no
// verified generation arms nothing and says why. An empty generation means
// liveness was never proven, so the Endpoint would refuse the stream with
// generation_required; arming it would only fail on the next prompt.
func TestUnitStartAutoFollowSkipsAnUnverifiedLaunch(t *testing.T) {
	stub := newStartAutoFollowStub()
	stub.fresh["endpoint-1"] = launchedInventory("res-new", "")
	output, diagnostics, _ := runWatchREPL(t, stub, startAutoFollowInput, nil)
	if diagnostics != "" {
		t.Fatalf("unexpected diagnostics: %q", diagnostics)
	}
	if stub.followCount() != 0 {
		t.Fatalf("streams opened=%d, want none without a verified generation", stub.followCount())
	}
	if !strings.Contains(output, "automatic follow skipped: the launched session has no verified generation") {
		t.Fatalf("missing unverified-generation diagnostic: %q", output)
	}
}

// TestUnitStartAutoFollowSkipsAnAmbiguousLaunch proves a collection that reports
// more than one new session arms nothing and says why. The evidence does not
// identify the launched session, and following a guess would stream the wrong one.
func TestUnitStartAutoFollowSkipsAnAmbiguousLaunch(t *testing.T) {
	stub := newStartAutoFollowStub()
	report := launchedInventory("res-new", "generation-new")
	report.Sessions = append(report.Sessions, protocol.Session{
		ClusterSessionID:   "res-other",
		ProviderSessionID:  "provider-other",
		AdapterID:          "adapter-1",
		ProviderGeneration: "generation-other",
		State:              "running",
		CollectionStatus:   protocol.CollectionSucceeded,
	})
	stub.fresh["endpoint-1"] = report
	output, diagnostics, _ := runWatchREPL(t, stub, startAutoFollowInput, nil)
	if diagnostics != "" {
		t.Fatalf("unexpected diagnostics: %q", diagnostics)
	}
	if stub.followCount() != 0 {
		t.Fatalf("streams opened=%d, want none for an ambiguous launch", stub.followCount())
	}
	if !strings.Contains(output, "automatic follow skipped: 2 sessions appeared") {
		t.Fatalf("missing ambiguity diagnostic: %q", output)
	}
}

// TestUnitStartAutoFollowDegradesToASnapshotWithoutStreaming proves a client that
// cannot stream still shows the launched session's output, and says why it is a
// snapshot. A snapshot presented as a stream would look complete while silently
// missing everything written after it.
func TestUnitStartAutoFollowDegradesToASnapshotWithoutStreaming(t *testing.T) {
	stub := newStartRefreshStub()
	stub.fresh["endpoint-1"] = launchedInventory("res-new", "generation-new")
	output, diagnostics, _ := runWatchREPL(t, stub, startAutoFollowInput, nil)
	if diagnostics != "" {
		t.Fatalf("a degraded automatic step must not be an error: %q", diagnostics)
	}
	if !strings.Contains(output, "start completed; automatic follow unavailable:") {
		t.Fatalf("missing degradation diagnostic: %q", output)
	}
	if !strings.Contains(output, "rendered one bounded snapshot instead") {
		t.Fatalf("degradation did not name the substitute: %q", output)
	}
}

// TestUnitStartAutoFollowDegradesWithoutAKeypressSeam proves a reader that cannot
// observe a keypress never arms a tail it could not stop, and reports the
// substitute instead of silently doing nothing.
func TestUnitStartAutoFollowDegradesWithoutAKeypressSeam(t *testing.T) {
	stub := newStartAutoFollowStub()
	stub.fresh["endpoint-1"] = launchedInventory("res-new", "generation-new")
	output, diagnostics := runScope(t, stub, strings.Join(startAutoFollowInput, "\n")+"\n", ColorPolicy{})
	if diagnostics != "" {
		t.Fatalf("a degraded automatic step must not be an error: %q", diagnostics)
	}
	if stub.followCount() != 0 {
		t.Fatalf("streams opened=%d, want none without a keypress seam", stub.followCount())
	}
	if !strings.Contains(output, "start completed; automatic follow unavailable:") {
		t.Fatalf("missing degradation diagnostic: %q", output)
	}
}

// TestUnitStartAutoFollowSkipsARejectedStart proves the tail is triggered by a
// completed start only. A receipt the provider did not apply performs no
// collection and arms nothing, because no session was created.
func TestUnitStartAutoFollowSkipsARejectedStart(t *testing.T) {
	stub := newStartAutoFollowStub()
	stub.commandResult = map[string]any{"status": string(protocol.StatusRejected), "effect_certainty": string(protocol.EffectNotApplied)}
	stub.fresh["endpoint-1"] = launchedInventory("res-new", "generation-new")
	output, diagnostics, _ := runWatchREPL(t, stub, startAutoFollowInput, nil)
	if diagnostics != "" {
		t.Fatalf("unexpected diagnostics: %q", diagnostics)
	}
	if len(stub.refreshCalls) != 0 {
		t.Fatalf("forced collections=%v, want none for a rejected start", stub.refreshCalls)
	}
	if stub.followCount() != 0 {
		t.Fatalf("streams opened=%d, want none for a rejected start", stub.followCount())
	}
	if strings.Contains(output, "follow:") {
		t.Fatalf("a rejected start armed a tail: %q", output)
	}
}

// TestUnitStartAutoFollowKeepsTheExplicitLogf proves the automatic step does not
// replace the explicit command: an operator who asks for logf still gets a second
// stream with its own identity. The explicit command is issued from endpoint
// scope, because logs and logf are unavailable in workspace scope.
func TestUnitStartAutoFollowKeepsTheExplicitLogf(t *testing.T) {
	stub := newStartAutoFollowStub()
	stub.fresh["endpoint-1"] = launchedInventory("res-new", "generation-new")
	lines := []string{"cd host-one/endpoint-1", "start endpoint-1 compatibility --profile p --profile-revision r", "logf res-1", "quit"}
	if _, diagnostics, _ := runWatchREPL(t, stub, lines, nil); diagnostics != "" {
		t.Fatalf("unexpected diagnostics: %q", diagnostics)
	}
	requests := stub.followRequests()
	if len(requests) != 2 {
		t.Fatalf("follow requests=%+v, want the automatic tail and the explicit one", requests)
	}
	if requests[0].resourceID != "res-new" {
		t.Fatalf("automatic tail followed %q, want the launched session", requests[0].resourceID)
	}
	if requests[1].resourceID != "res-1" {
		t.Fatalf("explicit logf followed %q, want the requested session", requests[1].resourceID)
	}
}

// startAutoFollowOutputFailureStub fails every snapshot read, so a test can prove
// a degraded automatic step reports its own failure without turning a successful
// admission into a command error.
type startAutoFollowOutputFailureStub struct {
	*startRefreshStub
}

func (s *startAutoFollowOutputFailureStub) GetOutput(context.Context, string, string, string, int, int) (protocol.OutputSnapshotResponse, error) {
	return protocol.OutputSnapshotResponse{}, errors.New("output unavailable")
}

// TestUnitStartAutoFollowReportsAFailedSnapshot proves a degraded snapshot that
// fails is reported as a diagnostic naming the primary action, instead of turning
// a successful admission into a command error.
func TestUnitStartAutoFollowReportsAFailedSnapshot(t *testing.T) {
	stub := &startAutoFollowOutputFailureStub{startRefreshStub: newStartRefreshStub()}
	stub.fresh["endpoint-1"] = launchedInventory("res-new", "generation-new")
	output, diagnostics, _ := runWatchREPL(t, stub, startAutoFollowInput, nil)
	if diagnostics != "" {
		t.Fatalf("a failed automatic step must not be an error: %q", diagnostics)
	}
	if !strings.Contains(output, "start completed; automatic logs failed: output unavailable") {
		t.Fatalf("missing failed-snapshot diagnostic: %q", output)
	}
}
