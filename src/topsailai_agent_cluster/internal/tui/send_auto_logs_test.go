package tui

import (
	"context"
	"errors"
	"strings"
	"sync"
	"testing"
	"time"

	"topsailai_agent_cluster/internal/protocol"
)

// sendScenario is the confirmed send used by the trigger tests. Entering the
// session already renders one bounded snapshot, so the automatic post-send step
// is the second output action and the first one is the entry snapshot.
const sendScenario = "cd host-one/endpoint-1/res-1\nsend {\"text\":\"hi\"}\nexit\n"

// sendFollowStub serves both the streaming seam and the forced-collection seam,
// so a test can prove the automatic post-send step arms a live tail and still
// forces one collection afterwards.
type sendFollowStub struct {
	sendRefreshStub
	mu           sync.Mutex
	follows      []outputRequest
	followStarts int
	followErr    error
}

// newSendFollowStub serves the shared two-endpoint fixture with both seams.
func newSendFollowStub() *sendFollowStub {
	return &sendFollowStub{sendRefreshStub: *newSendRefreshStub()}
}

// FollowOutput records the request and returns a stream that stays open until
// the caller stops it, so a started tail is observable instead of ending at once.
func (s *sendFollowStub) FollowOutput(ctx context.Context, endpointID, resourceID, generation string, maxBytes, maxLines int) (<-chan protocol.OutputFollowRecord, error) {
	s.mu.Lock()
	s.followStarts++
	s.follows = append(s.follows, outputRequest{endpointID: endpointID, resourceID: resourceID, generation: generation, maxBytes: maxBytes, maxLines: maxLines})
	s.steps = append(s.steps, "follow")
	followErr := s.followErr
	s.mu.Unlock()
	if followErr != nil {
		return nil, followErr
	}
	return make(chan protocol.OutputFollowRecord), nil
}

// followRequests returns the recorded follow requests.
func (s *sendFollowStub) followRequests() []outputRequest {
	s.mu.Lock()
	defer s.mu.Unlock()
	return append([]outputRequest(nil), s.follows...)
}

// followCount reports how many streams were opened.
func (s *sendFollowStub) followCount() int {
	s.mu.Lock()
	defer s.mu.Unlock()
	return s.followStarts
}

// automaticSteps returns the recorded automatic steps in order.
func (s *sendFollowStub) automaticSteps() []string {
	s.mu.Lock()
	defer s.mu.Unlock()
	return append([]string(nil), s.steps...)
}

// sendOutputRequests returns the recorded snapshot reads after the entry
// snapshot, which are the reads the send itself caused.
func sendOutputRequests(stub *interactiveStub) []outputRequest {
	if len(stub.outputRequests) <= 1 {
		return nil
	}
	return stub.outputRequests[1:]
}

// actionFollowRequests returns the follow requests caused by the action under
// test, skipping the entry transition's own tail. Entering a session arms the
// same live tail as logs -f, so the first request belongs to the scenario rather
// than to the action, exactly as the entry snapshot does for snapshot reads.
func actionFollowRequests(stub *sendFollowStub) []outputRequest {
	requests := stub.followRequests()
	if len(requests) <= 1 {
		return nil
	}
	return requests[1:]
}

// runSendREPL drives the REPL with a keypress-capable reader, so the automatic
// follow can actually start. The reader records every watch session it was
// given, which is how a test proves a stream was armed and then started.
func runSendREPL(t *testing.T, stub InteractiveAPI, lines []string) (string, string, *watchRecordingReader) {
	t.Helper()
	return runWatchREPL(t, stub, lines, nil)
}

// sendRefreshStub records forced collections and the order of the automatic
// steps, so a test can prove the refresh runs once, for the selected Endpoint,
// and only after the tail was armed.
type sendRefreshStub struct {
	interactiveStub
	refreshCalls    []string
	refreshErr      error
	refreshDeadline time.Time
	refreshHasLimit bool
	steps           []string
	fresh           map[string]protocol.InventoryReport
}

// newSendRefreshStub serves the shared two-endpoint fixture with the
// forced-collection seam.
func newSendRefreshStub() *sendRefreshStub {
	base := scopeStub()
	return &sendRefreshStub{
		interactiveStub: *base,
		fresh:           make(map[string]protocol.InventoryReport),
	}
}

// RefreshInventory records the forced collection and its position in the
// automatic sequence.
func (s *sendRefreshStub) RefreshInventory(ctx context.Context, endpointID string) (protocol.InventoryReport, error) {
	s.refreshCalls = append(s.refreshCalls, endpointID)
	s.steps = append(s.steps, "refresh")
	if deadline, ok := ctx.Deadline(); ok {
		s.refreshDeadline = deadline
		s.refreshHasLimit = true
	}
	if s.refreshErr != nil {
		return protocol.InventoryReport{}, s.refreshErr
	}
	if report, ok := s.fresh[endpointID]; ok {
		s.reports[endpointID] = report
	}
	return s.reports[endpointID], nil
}

// GetOutput records a snapshot read in the automatic sequence, so a degraded
// step is distinguishable from an armed tail.
func (s *sendRefreshStub) GetOutput(ctx context.Context, endpointID, resourceID, generation string, maxBytes, maxLines int) (protocol.OutputSnapshotResponse, error) {
	s.steps = append(s.steps, "logs")
	return s.interactiveStub.GetOutput(ctx, endpointID, resourceID, generation, maxBytes, maxLines)
}

// TestUnitSendAutoFollowArmsOneLiveTailAfterTheReceipt proves a completed send
// arms exactly one live tail for the identity the send already validated, and
// that it does so after the durable receipt was rendered. It also proves the
// automatic step is no longer a one-shot snapshot, because a snapshot stops at
// the moment it was read while the agent keeps writing.
func TestUnitSendAutoFollowArmsOneLiveTailAfterTheReceipt(t *testing.T) {
	stub := newSendFollowStub()
	output, diagnostics, _ := runSendREPL(t, stub, []string{"cd host-one/endpoint-1/res-1", `send {"text":"hi"}`, "quit"})
	if diagnostics != "" {
		t.Fatalf("unexpected diagnostics: %q", diagnostics)
	}
	if stub.admit != 1 {
		t.Fatalf("admitted %d commands, want 1", stub.admit)
	}
	requests := actionFollowRequests(stub)
	if len(requests) != 1 {
		t.Fatalf("follow requests=%+v, want exactly one", requests)
	}
	request := requests[0]
	if request.endpointID != "endpoint-1" || request.resourceID != "res-1" || request.generation != "generation-1" {
		t.Fatalf("wrong follow identity tuple: %+v", request)
	}
	receipt := strings.Index(output, "command submitted:")
	if receipt < 0 {
		t.Fatalf("missing submission evidence: %q", output)
	}
	tail := output[receipt:]
	announced := strings.Index(tail, "follow: res-1 (any key stops)")
	if announced < 0 {
		t.Fatalf("send did not arm a live tail after the receipt: %q", output)
	}
	if confirmed := strings.Index(tail, "confirmed result"); confirmed < 0 || confirmed > announced {
		t.Fatalf("tail was armed before the receipt: %q", tail)
	}
	// Entering the session already arms a tail, so the send must not also read a
	// snapshot: the automatic step replaced the one-shot read instead of running
	// beside it.
	if stub.outputCalls != 0 {
		t.Fatalf("snapshot reads=%d want=0 (both the entry and the send arm tails)", stub.outputCalls)
	}
}

// TestUnitSendAutoFollowIsBoundedByTheReplDefaults proves the automatic tail
// never requests an unbounded stream, so a completed send cannot pull an
// arbitrary amount of provider output into the terminal.
func TestUnitSendAutoFollowIsBoundedByTheReplDefaults(t *testing.T) {
	stub := newSendFollowStub()
	if _, diagnostics, _ := runSendREPL(t, stub, []string{"cd host-one/endpoint-1/res-1", `send {"text":"hi"}`, "quit"}); diagnostics != "" {
		t.Fatalf("unexpected diagnostics: %q", diagnostics)
	}
	requests := actionFollowRequests(stub)
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

// TestUnitSendAutoFollowStartsTheStreamOnTheNextPrompt proves the armed intent
// becomes a real stream for the following prompt, so the operator reads live
// output without typing logs -f, and that a keypress stops it.
func TestUnitSendAutoFollowStartsTheStreamOnTheNextPrompt(t *testing.T) {
	stub := newSendFollowStub()
	_, diagnostics, reader := runSendREPL(t, stub, []string{"cd host-one/endpoint-1/res-1", `send {"text":"hi"}`, "quit"})
	if diagnostics != "" {
		t.Fatalf("unexpected diagnostics: %q", diagnostics)
	}
	// Two streams open: the entry transition's tail on the prompt after cd, and
	// the send's tail on the prompt after the send.
	if stub.followCount() != 2 {
		t.Fatalf("streams opened=%d want=2 (entry and send)", stub.followCount())
	}
	sessions, _ := reader.recorded()
	if len(sessions) < 3 {
		t.Fatalf("prompts=%d, want at least three", len(sessions))
	}
	// The prompt after the send is the one that carries the send's stream.
	stream := sessions[2]
	if stream == nil {
		t.Fatal("the prompt after the send did not carry a stream")
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

// TestUnitSendAutoFollowDegradesToASnapshotWithoutStreaming proves a client that
// cannot stream still shows the effect of the send, and says why it is a
// snapshot. A snapshot presented as a stream would look complete while silently
// missing everything written after it.
func TestUnitSendAutoFollowDegradesToASnapshotWithoutStreaming(t *testing.T) {
	stub := scopeStub()
	output, diagnostics, _ := runSendREPL(t, stub, []string{"cd host-one/endpoint-1/res-1", `send {"text":"hi"}`, "quit"})
	if diagnostics != "" {
		t.Fatalf("a degraded automatic step must not be an error: %q", diagnostics)
	}
	if stub.admit != 1 {
		t.Fatalf("admitted %d commands, want 1", stub.admit)
	}
	if requests := sendOutputRequests(stub); len(requests) != 1 {
		t.Fatalf("post-send snapshot reads=%+v, want exactly one", requests)
	}
	if !strings.Contains(output, "send completed; automatic follow unavailable:") {
		t.Fatalf("missing degradation diagnostic: %q", output)
	}
	if !strings.Contains(output, "rendered one bounded snapshot instead") {
		t.Fatalf("degradation did not name the substitute: %q", output)
	}
}

// TestUnitSendAutoFollowDegradesWithoutAKeypressSeam proves a reader that cannot
// observe a keypress never arms a tail it could not stop, and reports the
// substitute instead of silently doing nothing.
func TestUnitSendAutoFollowDegradesWithoutAKeypressSeam(t *testing.T) {
	stub := newSendFollowStub()
	output, diagnostics := runScope(t, stub, sendScenario, ColorPolicy{})
	if diagnostics != "" {
		t.Fatalf("a degraded automatic step must not be an error: %q", diagnostics)
	}
	if stub.followCount() != 0 {
		t.Fatalf("streams opened=%d, want none without a keypress seam", stub.followCount())
	}
	if requests := sendOutputRequests(&stub.interactiveStub); len(requests) != 1 {
		t.Fatalf("post-send snapshot reads=%+v, want exactly one", requests)
	}
	if !strings.Contains(output, "send completed; automatic follow unavailable:") {
		t.Fatalf("missing degradation diagnostic: %q", output)
	}
}

// TestUnitSendAutoFollowKeepsTheExplicitLogsRead proves the automatic step does
// not replace the explicit command: an operator who asks for logs still gets a
// second read with its own limit.
func TestUnitSendAutoFollowKeepsTheExplicitLogsRead(t *testing.T) {
	stub := newSendFollowStub()
	input := "cd host-one/endpoint-1/res-1\nsend {\"text\":\"hi\"}\nlogs -n 7\nquit\n"
	if _, diagnostics, _ := runSendREPL(t, stub, []string{"cd host-one/endpoint-1/res-1", `send {"text":"hi"}`, "logs -n 7", "quit"}); diagnostics != "" {
		t.Fatalf("unexpected diagnostics: %q", diagnostics)
	}
	_ = input
	// The entry transition arms a tail instead of reading a snapshot, so the only
	// snapshot read in the run is the explicit one.
	requests := stub.outputRequests
	if len(requests) != 1 {
		t.Fatalf("snapshot reads=%+v, want only the explicit read", requests)
	}
	if got := requests[0].maxLines; got != 7 {
		t.Fatalf("explicit read maxLines=%d want=7", got)
	}
	if got := len(actionFollowRequests(stub)); got != 1 {
		t.Fatalf("action follow requests=%d, want the automatic tail only", got)
	}
}

// TestUnitSendAutoFollowSkipsEveryRejectedSend proves the tail is triggered by a
// completed send only: a declined confirmation, an invalid payload, an uncertain
// admission, a capability change and a generation change all arm nothing.
func TestUnitSendAutoFollowSkipsEveryRejectedSend(t *testing.T) {
	cases := []struct {
		name  string
		stub  func() InteractiveAPI
		input string
	}{
		{
			name:  "declined confirmation",
			stub:  func() InteractiveAPI { return scopeStub() },
			input: "cd host-one/endpoint-1/res-1\nsend\nhi\nEOF\nn\nexit\n",
		},
		{
			name:  "invalid payload",
			stub:  func() InteractiveAPI { return scopeStub() },
			input: "cd host-one/endpoint-1/res-1\nsend {\nexit\n",
		},
		{
			name: "uncertain admission",
			stub: func() InteractiveAPI {
				stub := scopeStub()
				stub.admitErr = errors.New("transport timeout")
				return stub
			},
			input: "cd host-one/endpoint-1/res-1\nsend {\"text\":\"hi\"}\nexit\n",
		},
		{
			name: "capability change",
			stub: func() InteractiveAPI {
				return &inputCapabilitySequenceStub{
					interactiveStub: *inputStub(),
					revisions:       []string{"r1", "r2"},
				}
			},
			input: "cd endpoint-1/session-1\nsend\nhi\nEOF\ny\nexit\n",
		},
		{
			name: "generation change",
			stub: func() InteractiveAPI {
				// Startup list, cd, then the send revalidation: only that read
				// reports a new generation for the pinned session.
				stub := inputStub()
				stub.changeAfter = 3
				return stub
			},
			input: "cd endpoint-1/session-1\nsend {\"text\":\"hi\"}\nexit\n",
		},
	}
	for _, testCase := range cases {
		t.Run(testCase.name, func(t *testing.T) {
			api := testCase.stub()
			stub, ok := api.(*interactiveStub)
			if !ok {
				// The capability stub embeds the shared stub, so the recorded
				// requests are reachable through the embedded value.
				stub = &api.(*inputCapabilitySequenceStub).interactiveStub
			}
			runScope(t, api, testCase.input, ColorPolicy{})
			if requests := sendOutputRequests(stub); len(requests) != 0 {
				t.Fatalf("%s reached the output API: %+v", testCase.name, requests)
			}
			// These stubs cannot stream, so the entry transition degrades to a
			// snapshot and a rejected send must add no read of its own. The tail
			// path for a rejected send is covered by the streaming tests above,
			// which use a client that can stream; asserting it here would need a
			// streaming stub this matrix deliberately does not use.
		})
	}
}

// TestUnitSendAutoFollowReportsAStartFailureAsADiagnostic proves a tail that
// cannot start never turns an accepted send into a failure: the receipt stays,
// and the failure is reported through the armed session instead of being
// swallowed by the command that armed it.
func TestUnitSendAutoFollowReportsAStartFailureAsADiagnostic(t *testing.T) {
	stub := newSendFollowStub()
	stub.followErr = errors.New("transport unavailable")
	output, diagnostics, reader := runSendREPL(t, stub, []string{"cd host-one/endpoint-1/res-1", `send {"text":"hi"}`, "quit"})
	if diagnostics != "" {
		t.Fatalf("a failed automatic tail must not be an error: %q", diagnostics)
	}
	if stub.admit != 1 {
		t.Fatalf("admitted %d commands, want 1", stub.admit)
	}
	if !strings.Contains(output, "command submitted:") || !strings.Contains(output, "confirmed result") {
		t.Fatalf("receipt was lost: %q", output)
	}
	sessions, _ := reader.recorded()
	if len(sessions) < 3 || sessions[2] == nil {
		t.Fatalf("the prompt after the send did not carry the armed tail: %+v", sessions)
	}
	payload, err := sessions[2].Idle()
	if err != nil {
		t.Fatalf("Idle: %v", err)
	}
	if !strings.Contains(string(payload), "follow failed: transport unavailable") {
		t.Fatalf("missing start-failure diagnostic: %q", payload)
	}
	// The REPL keeps running: the session prompt is rendered again after the
	// receipt, and quit then returns to workspace scope as usual.
	if !strings.Contains(output, "session[host-one/provider-res-1]>") {
		t.Fatalf("the REPL did not return to the session prompt: %q", output)
	}
	if got := lastPrompt(output); got != "workspace>" {
		t.Fatalf("final prompt = %q, want workspace after quit", got)
	}
}

// TestUnitSendAutoFollowKeepsTheForcedCollection proves the send still forces
// exactly one collection for the selected Endpoint, and that the tail is armed
// first because it is bound to the generation validated before the send while a
// refresh can replace it.
func TestUnitSendAutoFollowKeepsTheForcedCollection(t *testing.T) {
	stub := newSendFollowStub()
	output, diagnostics, _ := runSendREPL(t, stub, []string{"cd host-one/endpoint-1/res-1", `send {"text":"hi"}`, "quit"})
	if diagnostics != "" {
		t.Fatalf("unexpected diagnostics: %q", diagnostics)
	}
	if len(stub.refreshCalls) != 1 || stub.refreshCalls[0] != "endpoint-1" {
		t.Fatalf("forced collections=%v, want exactly one for endpoint-1", stub.refreshCalls)
	}
	// The entry transition opens the first tail, the send arms its intent without
	// opening a stream yet, the refresh runs, and the send's stream opens on the
	// following prompt. The intent is therefore armed before the refresh, which is
	// what keeps it bound to the generation the send validated.
	want := []string{"follow", "refresh", "follow"}
	got := stub.automaticSteps()
	if len(got) != len(want) {
		t.Fatalf("automatic steps=%v, want %v", got, want)
	}
	for index := range want {
		if got[index] != want[index] {
			t.Fatalf("automatic steps=%v, want %v", got, want)
		}
	}
	if !strings.Contains(output, "follow: res-1 (any key stops)") {
		t.Fatalf("the tail was not armed before the refresh: %q", output)
	}
	if !strings.Contains(output, "command submitted:") {
		t.Fatalf("receipt was lost: %q", output)
	}
}

// TestUnitSendAutoFollowIsCancelledWhenTheRefreshReplacesTheSession proves a
// refresh that reports a new generation drops the armed tail instead of
// streaming a session instance the operator no longer addresses.
func TestUnitSendAutoFollowIsCancelledWhenTheRefreshReplacesTheSession(t *testing.T) {
	stub := newSendFollowStub()
	stub.fresh["endpoint-1"] = scopeInventory("res-1", "generation-2")
	output, diagnostics, _ := runSendREPL(t, stub, []string{"cd host-one/endpoint-1/res-1", `send {"text":"hi"}`, "quit"})
	if diagnostics != "" {
		t.Fatalf("unexpected diagnostics: %q", diagnostics)
	}
	if len(stub.refreshCalls) != 1 {
		t.Fatalf("forced collections=%v, want exactly one", stub.refreshCalls)
	}
	if !strings.Contains(output, "selected session generation changed") {
		t.Fatalf("missing generation diagnostic: %q", output)
	}
	if !strings.Contains(output, "automatic follow cancelled: the selected session was replaced") {
		t.Fatalf("missing cancellation diagnostic: %q", output)
	}
	// Only the entry transition's tail opened; the send's intent was cancelled
	// before its stream could start, so the replaced generation is never streamed.
	if stub.followCount() != 1 {
		t.Fatalf("streams opened=%d, want only the entry tail for a replaced session", stub.followCount())
	}
	// The invalidated prompt is rendered before quit returns to workspace scope,
	// so the operator sees that the selection can no longer be addressed.
	if !strings.Contains(output, "session[host-one/provider-res-1!]>") {
		t.Fatalf("missing invalidated session prompt: %q", output)
	}
}

// TestUnitSendAutoFollowDoesNotTriggerOnOtherActions proves the send trigger
// stays scoped to send: interrupt, resume and stop keep their previous behaviour
// and arm no tail of their own. btw is covered separately, because context
// injection does arm a tail.
func TestUnitSendAutoFollowDoesNotTriggerOnOtherActions(t *testing.T) {
	cases := []struct {
		name  string
		input string
	}{
		{name: "interrupt", input: "cd host-one/endpoint-1/res-1\ninterrupt {\"action\":\"soft_interrupt\"}\ny\nexit\n"},
		{name: "resume", input: "cd host-one/endpoint-1/res-1\nresume\ny\nexit\n"},
		{name: "stop", input: "cd host-one/endpoint-1/res-1\nstop\ny\nexit\n"},
	}
	for _, testCase := range cases {
		t.Run(testCase.name, func(t *testing.T) {
			stub := stopScopeStub()
			if testCase.name == "resume" {
				// resume requires an authoritative absence before and after confirmation.
				stub.sessionPresenceSequence = []bool{true, true, false, false, false}
			}
			runScope(t, stub, testCase.input, ColorPolicy{})
			if requests := sendOutputRequests(stub); len(requests) != 0 {
				t.Fatalf("%s reached the output API: %+v", testCase.name, requests)
			}
			// These stubs cannot stream, so the entry transition degrades to a
			// snapshot and the action must add no read of its own. A tail cannot be
			// armed without the streaming seam, so the snapshot assertion is the
			// complete check available to this matrix.
		})
	}
}

// TestUnitSendAutoFollowInheritsTheSendPrefixAlias proves the ">" alias runs the
// same automatic step as send, because it dispatches to the same handler and must
// not become a path that skips the tail or the forced collection.
func TestUnitSendAutoFollowInheritsTheSendPrefixAlias(t *testing.T) {
	stub := newSendFollowStub()
	if _, diagnostics, _ := runSendREPL(t, stub, []string{"cd host-one/endpoint-1/res-1", "> hello world", "quit"}); diagnostics != "" {
		t.Fatalf("unexpected diagnostics: %q", diagnostics)
	}
	if stub.admit != 1 {
		t.Fatalf("admitted %d commands, want 1", stub.admit)
	}
	if requests := actionFollowRequests(stub); len(requests) != 1 {
		t.Fatalf("follow requests=%+v, want exactly one", requests)
	}
	if len(stub.refreshCalls) != 1 || stub.refreshCalls[0] != "endpoint-1" {
		t.Fatalf("forced collections=%v, want exactly one for endpoint-1", stub.refreshCalls)
	}
}

// TestUnitSendAutoFollowUsesItsOwnBudget proves the automatic step does not reuse
// the command context: the local wait may already have exhausted that deadline,
// and reusing it would report an unavailable output for a healthy session.
func TestUnitSendAutoFollowUsesItsOwnBudget(t *testing.T) {
	stub := &sendBudgetStub{interactiveStub: scopeStub()}
	if _, diagnostics := runScope(t, stub, sendScenario, ColorPolicy{}); diagnostics != "" {
		t.Fatalf("unexpected diagnostics: %q", diagnostics)
	}
	if !stub.commandHasDeadline || !stub.outputHasDeadline {
		t.Fatalf("missing deadlines: command=%v output=%v", stub.commandHasDeadline, stub.outputHasDeadline)
	}
	if !stub.outputDeadline.After(stub.commandDeadline) {
		t.Fatalf("automatic read deadline=%v is not later than the command deadline=%v", stub.outputDeadline, stub.commandDeadline)
	}
	if stub.outputErr != nil {
		t.Fatalf("automatic read ran on a finished context: %v", stub.outputErr)
	}
}

// sendBudgetStub records the command context deadline and the deadline of the
// degraded automatic snapshot, so the test can prove they are different budgets.
type sendBudgetStub struct {
	*interactiveStub
	commandDeadline    time.Time
	commandHasDeadline bool
	outputDeadline     time.Time
	outputHasDeadline  bool
	outputErr          error
}

func (s *sendBudgetStub) AdmitCommand(ctx context.Context, intent protocol.ImmutableIntent) (map[string]any, error) {
	if deadline, ok := ctx.Deadline(); ok {
		s.commandDeadline = deadline
		s.commandHasDeadline = true
	}
	return s.interactiveStub.AdmitCommand(ctx, intent)
}

func (s *sendBudgetStub) GetOutput(ctx context.Context, endpointID, resourceID, generation string, maxBytes, maxLines int) (protocol.OutputSnapshotResponse, error) {
	// The first read is the entry snapshot; the second is the degraded
	// automatic read.
	if s.outputCalls == 1 {
		if deadline, ok := ctx.Deadline(); ok {
			s.outputDeadline = deadline
			s.outputHasDeadline = true
		}
		s.outputErr = ctx.Err()
	}
	return s.interactiveStub.GetOutput(ctx, endpointID, resourceID, generation, maxBytes, maxLines)
}
