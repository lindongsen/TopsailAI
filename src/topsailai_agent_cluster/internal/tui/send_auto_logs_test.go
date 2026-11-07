package tui

import (
	"context"
	"errors"
	"strings"
	"testing"
	"time"

	"topsailai_agent_cluster/internal/protocol"
)

// sendScenario is the confirmed send used by the trigger tests. Entering the
// session already renders one bounded snapshot, so the automatic post-send read
// is the second output request and the first one is the entry snapshot.
const sendScenario = "cd host-one/endpoint-1/res-1\nsend {\"text\":\"hi\"}\ny\nquit\n"

// sendOutputRequests returns the recorded output requests after the entry
// snapshot, which are the reads the send itself caused.
func sendOutputRequests(stub *interactiveStub) []outputRequest {
	if len(stub.outputRequests) <= 1 {
		return nil
	}
	return stub.outputRequests[1:]
}

// TestUnitSendAutoLogsRendersOneSnapshotAfterTheReceipt proves a completed send
// reads the selected session's output exactly once, for the identity the send
// already validated, and only after the durable receipt was rendered.
func TestUnitSendAutoLogsRendersOneSnapshotAfterTheReceipt(t *testing.T) {
	stub := scopeStub()
	output, diagnostics := runScope(t, stub, sendScenario, ColorPolicy{})
	if diagnostics != "" {
		t.Fatalf("unexpected diagnostics: %q", diagnostics)
	}
	if stub.admit != 1 {
		t.Fatalf("admitted %d commands, want 1", stub.admit)
	}
	requests := sendOutputRequests(stub)
	if len(requests) != 1 {
		t.Fatalf("post-send output requests=%+v, want exactly one", requests)
	}
	request := requests[0]
	if request.endpointID != "endpoint-1" || request.resourceID != "res-1" || request.generation != "generation-1" {
		t.Fatalf("wrong output identity tuple: %+v", request)
	}
	receipt := strings.Index(output, "command submitted:")
	if receipt < 0 {
		t.Fatalf("missing submission evidence: %q", output)
	}
	tail := output[receipt:]
	snapshot := strings.Index(tail, "observed_at_ms:")
	if snapshot < 0 {
		t.Fatalf("send did not render a snapshot after the receipt: %q", output)
	}
	if confirmed := strings.Index(tail, "confirmed result"); confirmed < 0 || confirmed > snapshot {
		t.Fatalf("snapshot was not rendered after the receipt: %q", tail)
	}
}

// TestUnitSendAutoLogsIsBoundedByTheReplDefaults proves the automatic read never
// requests an unbounded snapshot, so a completed send cannot pull an arbitrary
// amount of provider output into the terminal.
func TestUnitSendAutoLogsIsBoundedByTheReplDefaults(t *testing.T) {
	stub := scopeStub()
	if _, diagnostics := runScope(t, stub, sendScenario, ColorPolicy{}); diagnostics != "" {
		t.Fatalf("unexpected diagnostics: %q", diagnostics)
	}
	requests := sendOutputRequests(stub)
	if len(requests) != 1 {
		t.Fatalf("post-send output requests=%+v, want exactly one", requests)
	}
	if got := requests[0].maxLines; got != 100 {
		t.Fatalf("post-send maxLines=%d want=100", got)
	}
	if got := requests[0].maxBytes; got != 64<<10 {
		t.Fatalf("post-send maxBytes=%d want=%d", got, 64<<10)
	}
}

// TestUnitSendAutoLogsKeepsTheExplicitLogsRead proves the automatic read does not
// replace the explicit command: an operator who asks for logs still gets a second
// read with its own limit.
func TestUnitSendAutoLogsKeepsTheExplicitLogsRead(t *testing.T) {
	stub := scopeStub()
	input := "cd host-one/endpoint-1/res-1\nsend {\"text\":\"hi\"}\ny\nlogs -n 7\nquit\n"
	if _, diagnostics := runScope(t, stub, input, ColorPolicy{}); diagnostics != "" {
		t.Fatalf("unexpected diagnostics: %q", diagnostics)
	}
	requests := sendOutputRequests(stub)
	if len(requests) != 2 {
		t.Fatalf("post-send output requests=%+v, want the automatic read then the explicit read", requests)
	}
	if got := requests[0].maxLines; got != 100 {
		t.Fatalf("automatic read maxLines=%d want=100", got)
	}
	if got := requests[1].maxLines; got != 7 {
		t.Fatalf("explicit read maxLines=%d want=7", got)
	}
}

// TestUnitSendAutoLogsSkipsEveryRejectedSend proves the read is triggered by a
// completed send only: a declined confirmation, an invalid payload, an uncertain
// admission, a capability change and a generation change all read nothing.
func TestUnitSendAutoLogsSkipsEveryRejectedSend(t *testing.T) {
	cases := []struct {
		name  string
		stub  func() InteractiveAPI
		input string
	}{
		{
			name:  "declined confirmation",
			stub:  func() InteractiveAPI { return scopeStub() },
			input: "cd host-one/endpoint-1/res-1\nsend {\"text\":\"hi\"}\nn\nquit\n",
		},
		{
			name:  "invalid payload",
			stub:  func() InteractiveAPI { return scopeStub() },
			input: "cd host-one/endpoint-1/res-1\nsend {\nquit\n",
		},
		{
			name: "uncertain admission",
			stub: func() InteractiveAPI {
				stub := scopeStub()
				stub.admitErr = errors.New("transport timeout")
				return stub
			},
			input: "cd host-one/endpoint-1/res-1\nsend {\"text\":\"hi\"}\ny\nquit\n",
		},
		{
			name: "capability change",
			stub: func() InteractiveAPI {
				return &inputCapabilitySequenceStub{
					interactiveStub: *inputStub(),
					revisions:       []string{"r1", "r2"},
				}
			},
			input: "cd endpoint-1/session-1\nsend {\"text\":\"hi\"}\ny\nquit\n",
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
			input: "cd endpoint-1/session-1\nsend {\"text\":\"hi\"}\ny\nquit\n",
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
		})
	}
}

// TestUnitSendAutoLogsReportsAFailedReadAsADiagnostic proves a failed follow-up
// read never turns an accepted send into a failure: the receipt stays, the
// failure is named, and the REPL keeps running.
func TestUnitSendAutoLogsReportsAFailedReadAsADiagnostic(t *testing.T) {
	stub := &failAfterOutputStub{interactiveStub: scopeStub(), succeed: 1}
	output, diagnostics := runScope(t, stub, sendScenario, ColorPolicy{})
	if diagnostics != "" {
		t.Fatalf("a failed automatic read must not be an error: %q", diagnostics)
	}
	if stub.admit != 1 {
		t.Fatalf("admitted %d commands, want 1", stub.admit)
	}
	if !strings.Contains(output, "command submitted:") || !strings.Contains(output, "confirmed result") {
		t.Fatalf("receipt was lost: %q", output)
	}
	if !strings.Contains(output, "send completed; automatic logs failed: output unavailable") {
		t.Fatalf("missing failure diagnostic: %q", output)
	}
	if got := lastPrompt(output); got != "session[host-one/provider-res-1]>" {
		t.Fatalf("final prompt = %q, want session prompt", got)
	}
}

// TestUnitSendAutoLogsUsesItsOwnBudget proves the automatic read does not reuse
// the command context: the local wait may already have exhausted that deadline,
// and reusing it would report an unavailable output for a healthy session.
func TestUnitSendAutoLogsUsesItsOwnBudget(t *testing.T) {
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

// TestUnitSendAutoLogsDoesNotTriggerOnOtherActions proves the trigger stays
// scoped to send: inject, interrupt, resume and stop keep their previous
// behaviour and read no output of their own.
func TestUnitSendAutoLogsDoesNotTriggerOnOtherActions(t *testing.T) {
	cases := []struct {
		name  string
		input string
	}{
		{name: "inject", input: "cd host-one/endpoint-1/res-1\ninject {\"text\":\"hi\"}\ny\nquit\n"},
		{name: "interrupt", input: "cd host-one/endpoint-1/res-1\ninterrupt {\"action\":\"soft_interrupt\"}\ny\nquit\n"},
		{name: "resume", input: "cd host-one/endpoint-1/res-1\nresume\ny\nquit\n"},
		{name: "stop", input: "cd host-one/endpoint-1/res-1\nstop\ny\nquit\n"},
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
		})
	}
}

// failAfterOutputStub succeeds for the first reads and fails afterwards, so the
// entry snapshot stays healthy while the post-send read fails.
type failAfterOutputStub struct {
	*interactiveStub
	succeed int
}

func (s *failAfterOutputStub) GetOutput(_ context.Context, endpointID, resourceID, generation string, maxBytes, maxLines int) (protocol.OutputSnapshotResponse, error) {
	if s.outputCalls >= s.succeed {
		s.outputCalls++
		s.outputRequests = append(s.outputRequests, outputRequest{endpointID: endpointID, resourceID: resourceID, generation: generation, maxBytes: maxBytes, maxLines: maxLines})
		return protocol.OutputSnapshotResponse{}, errors.New("output unavailable")
	}
	return s.interactiveStub.GetOutput(context.Background(), endpointID, resourceID, generation, maxBytes, maxLines)
}

// sendBudgetStub records the command context deadline and the deadline of the
// post-send output read, so the test can prove they are different budgets.
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
	// The first read is the entry snapshot; the second is the post-send read.
	if s.outputCalls == 1 {
		if deadline, ok := ctx.Deadline(); ok {
			s.outputDeadline = deadline
			s.outputHasDeadline = true
		}
		s.outputErr = ctx.Err()
	}
	return s.interactiveStub.GetOutput(ctx, endpointID, resourceID, generation, maxBytes, maxLines)
}

// sendRefreshStub records forced collections and the order of the automatic
// steps, so a test can prove the refresh runs once, for the selected Endpoint,
// and only after the logs read.
type sendRefreshStub struct {
	interactiveStub
	refreshCalls    []string
	refreshErr      error
	refreshDeadline time.Time
	refreshHasLimit bool
	steps           []string
	fresh           map[string]protocol.InventoryReport
}

func newSendRefreshStub() *sendRefreshStub {
	base := scopeStub()
	return &sendRefreshStub{
		interactiveStub: *base,
		fresh:           make(map[string]protocol.InventoryReport),
	}
}

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

func (s *sendRefreshStub) GetOutput(ctx context.Context, endpointID, resourceID, generation string, maxBytes, maxLines int) (protocol.OutputSnapshotResponse, error) {
	s.steps = append(s.steps, "logs")
	return s.interactiveStub.GetOutput(ctx, endpointID, resourceID, generation, maxBytes, maxLines)
}

// TestUnitSendAutoRefreshForcesOneCollectionAfterTheLogs proves a completed send
// forces exactly one collection for the selected Endpoint, and that the read of
// the pre-send generation happens first because a refresh can replace it.
func TestUnitSendAutoRefreshForcesOneCollectionAfterTheLogs(t *testing.T) {
	stub := newSendRefreshStub()
	output, diagnostics := runScope(t, stub, sendScenario, ColorPolicy{})
	if diagnostics != "" {
		t.Fatalf("unexpected diagnostics: %q", diagnostics)
	}
	if stub.admit != 1 {
		t.Fatalf("admitted %d commands, want 1", stub.admit)
	}
	if len(stub.refreshCalls) != 1 || stub.refreshCalls[0] != "endpoint-1" {
		t.Fatalf("forced collections=%v, want exactly one for endpoint-1", stub.refreshCalls)
	}
	// The entry snapshot is the first read, so the send's own read is the second.
	want := []string{"logs", "logs", "refresh"}
	if len(stub.steps) != len(want) {
		t.Fatalf("automatic steps=%v, want %v", stub.steps, want)
	}
	for index := range want {
		if stub.steps[index] != want[index] {
			t.Fatalf("automatic steps=%v, want %v", stub.steps, want)
		}
	}
	if !strings.Contains(output, "command submitted:") {
		t.Fatalf("receipt was lost: %q", output)
	}
}

// TestUnitSendAutoRefreshUsesTheForcedCollectionBudget proves the refresh waits
// on the forced-collection budget, which exceeds the Server budget so the Server
// reports its own explicit failure first.
func TestUnitSendAutoRefreshUsesTheForcedCollectionBudget(t *testing.T) {
	stub := newSendRefreshStub()
	if _, diagnostics := runScope(t, stub, sendScenario, ColorPolicy{}); diagnostics != "" {
		t.Fatalf("unexpected diagnostics: %q", diagnostics)
	}
	if !stub.refreshHasLimit {
		t.Fatal("forced collection ran without a deadline")
	}
	if remaining := time.Until(stub.refreshDeadline); remaining < 20*time.Second {
		t.Fatalf("forced collection budget=%v, want the refresh budget", remaining)
	}
}

// TestUnitSendAutoRefreshSkipsEveryRejectedSend proves the refresh is triggered
// by a completed send only, so a rejected intent never causes a collection.
func TestUnitSendAutoRefreshSkipsEveryRejectedSend(t *testing.T) {
	cases := []struct {
		name  string
		input string
		admit error
	}{
		{name: "declined confirmation", input: "cd host-one/endpoint-1/res-1\nsend {\"text\":\"hi\"}\nn\nquit\n"},
		{name: "invalid payload", input: "cd host-one/endpoint-1/res-1\nsend {\nquit\n"},
		{name: "uncertain admission", input: "cd host-one/endpoint-1/res-1\nsend {\"text\":\"hi\"}\ny\nquit\n", admit: errors.New("transport timeout")},
	}
	for _, testCase := range cases {
		t.Run(testCase.name, func(t *testing.T) {
			stub := newSendRefreshStub()
			stub.admitErr = testCase.admit
			runScope(t, stub, testCase.input, ColorPolicy{})
			if len(stub.refreshCalls) != 0 {
				t.Fatalf("%s forced a collection: %v", testCase.name, stub.refreshCalls)
			}
		})
	}
}

// TestUnitSendAutoRefreshDoesNotTriggerOnOtherActions proves the refresh stays
// scoped to send, so a message-free action never forces a collection.
func TestUnitSendAutoRefreshDoesNotTriggerOnOtherActions(t *testing.T) {
	cases := []struct {
		name  string
		input string
	}{
		{name: "inject", input: "cd host-one/endpoint-1/res-1\ninject {\"text\":\"hi\"}\ny\nquit\n"},
		{name: "interrupt", input: "cd host-one/endpoint-1/res-1\ninterrupt {\"action\":\"soft_interrupt\"}\ny\nquit\n"},
		{name: "resume", input: "cd host-one/endpoint-1/res-1\nresume\ny\nquit\n"},
		{name: "stop", input: "cd host-one/endpoint-1/res-1\nstop\ny\nquit\n"},
	}
	for _, testCase := range cases {
		t.Run(testCase.name, func(t *testing.T) {
			stub := newSendRefreshStub()
			if testCase.name == "resume" {
				stub.sessionPresenceSequence = []bool{true, true, false, false, false}
			}
			runScope(t, stub, testCase.input, ColorPolicy{})
			if len(stub.refreshCalls) != 0 {
				t.Fatalf("%s forced a collection: %v", testCase.name, stub.refreshCalls)
			}
		})
	}
}

// TestUnitSendAutoRefreshReportsAFailureAsADiagnostic proves a failed collection
// never turns an accepted send into a failure: the receipt stays, the failure is
// named, and the REPL keeps running.
func TestUnitSendAutoRefreshReportsAFailureAsADiagnostic(t *testing.T) {
	stub := newSendRefreshStub()
	stub.refreshErr = errors.New("endpoint_unavailable")
	output, diagnostics := runScope(t, stub, sendScenario, ColorPolicy{})
	if diagnostics != "" {
		t.Fatalf("a failed automatic refresh must not be an error: %q", diagnostics)
	}
	if !strings.Contains(output, "command submitted:") || !strings.Contains(output, "confirmed result") {
		t.Fatalf("receipt was lost: %q", output)
	}
	if !strings.Contains(output, "send completed; automatic refresh failed: endpoint_unavailable") {
		t.Fatalf("missing failure diagnostic: %q", output)
	}
	if got := lastPrompt(output); got != "session[host-one/provider-res-1]>" {
		t.Fatalf("final prompt = %q, want the unchanged session prompt", got)
	}
}

// TestUnitSendAutoRefreshDegradesWithoutTheSeam proves a client without forced
// collection keeps read-only behaviour: the send still succeeds and reports no
// refresh failure, because the capability is genuinely absent rather than broken.
func TestUnitSendAutoRefreshDegradesWithoutTheSeam(t *testing.T) {
	stub := scopeStub()
	output, diagnostics := runScope(t, stub, sendScenario, ColorPolicy{})
	if diagnostics != "" {
		t.Fatalf("unexpected diagnostics: %q", diagnostics)
	}
	if stub.admit != 1 {
		t.Fatalf("admitted %d commands, want 1", stub.admit)
	}
	if strings.Contains(output, "automatic refresh failed") {
		t.Fatalf("absent capability was reported as a failure: %q", output)
	}
	if requests := sendOutputRequests(stub); len(requests) != 1 {
		t.Fatalf("post-send output requests=%+v, want exactly one", requests)
	}
}

// TestUnitSendAutoRefreshInvalidatesAChangedGeneration proves a refresh that
// reports a new generation invalidates the pinned selection instead of silently
// retargeting the operator's next command at a different session instance.
func TestUnitSendAutoRefreshInvalidatesAChangedGeneration(t *testing.T) {
	stub := newSendRefreshStub()
	stub.fresh["endpoint-1"] = scopeInventory("res-1", "generation-2")
	output, diagnostics := runScope(t, stub, sendScenario, ColorPolicy{})
	if diagnostics != "" {
		t.Fatalf("unexpected diagnostics: %q", diagnostics)
	}
	if len(stub.refreshCalls) != 1 {
		t.Fatalf("forced collections=%v, want exactly one", stub.refreshCalls)
	}
	if !strings.Contains(output, "selected session generation changed") {
		t.Fatalf("missing generation diagnostic: %q", output)
	}
	if got := lastPrompt(output); got != "session[host-one/provider-res-1!]>" {
		t.Fatalf("final prompt = %q, want an invalidated session prompt", got)
	}
}

// TestUnitSendAutoRefreshInheritsTheSendPrefixAlias proves the ">" alias runs
// the same automatic steps as send, because it dispatches to the same handler
// and must not become a path that skips the read or the forced collection.
func TestUnitSendAutoRefreshInheritsTheSendPrefixAlias(t *testing.T) {
	stub := newSendRefreshStub()
	input := "cd host-one/endpoint-1/res-1\n> hello world\ny\nquit\n"
	if _, diagnostics := runScope(t, stub, input, ColorPolicy{}); diagnostics != "" {
		t.Fatalf("unexpected diagnostics: %q", diagnostics)
	}
	if stub.admit != 1 {
		t.Fatalf("admitted %d commands, want 1", stub.admit)
	}
	if requests := sendOutputRequests(&stub.interactiveStub); len(requests) != 1 {
		t.Fatalf("post-send output requests=%+v, want exactly one", requests)
	}
	if len(stub.refreshCalls) != 1 || stub.refreshCalls[0] != "endpoint-1" {
		t.Fatalf("forced collections=%v, want exactly one for endpoint-1", stub.refreshCalls)
	}
}
