package tui

import (
	"strings"
	"testing"
)

// btwScenario enters a session and injects context, so the automatic post-btw
// step is the second output action and the first one is the entry snapshot.
const btwScenario = "cd host-one/endpoint-1/res-1\nbtw {\"text\":\"hi\"}\ny\nexit\n"

// armedFollowSession returns the last recorded prompt session that carries an
// armed follow, which is the tail the action under test armed. Entering a session
// arms a tail of its own, so "exactly one armed prompt" is no longer true and the
// last one is the action's. It fails when none was armed, so a test never has to
// hardcode a prompt index: the confirmation answer consumes a prompt slot of its
// own, which makes the index differ from the send path.
func armedFollowSession(t *testing.T, reader *watchRecordingReader) WatchSession {
	t.Helper()
	sessions, _ := reader.recorded()
	var armed []WatchSession
	for _, session := range sessions {
		if session != nil {
			armed = append(armed, session)
		}
	}
	if len(armed) == 0 {
		t.Fatalf("no prompt carried a stream: %+v", sessions)
	}
	return armed[len(armed)-1]
}

// TestUnitBtwAutoFollowArmsOneLiveTailAfterTheReceipt proves a completed context
// injection arms exactly one live tail for the identity the injection already
// validated, and that it does so after the durable receipt was rendered. The
// injected context usually makes the agent keep working, so a one-shot snapshot
// would stop at the moment it was read while the agent kept writing.
func TestUnitBtwAutoFollowArmsOneLiveTailAfterTheReceipt(t *testing.T) {
	stub := newSendFollowStub()
	output, diagnostics, _ := runSendREPL(t, stub, []string{"cd host-one/endpoint-1/res-1", `btw {"text":"hi"}`, "y", "quit"})
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
	// btw renders its receipt through renderInteractiveStartResult, so the
	// durable evidence is the CommandID line rather than the send wording.
	receipt := strings.Index(output, "CommandID:")
	if receipt < 0 {
		t.Fatalf("missing submission evidence: %q", output)
	}
	tail := output[receipt:]
	announced := strings.Index(tail, "follow: res-1 (any key stops)")
	if announced < 0 {
		t.Fatalf("btw did not arm a live tail after the receipt: %q", output)
	}
	// EffectCertainty is the last line of the receipt, so the tail must be armed
	// after it: an announcement before the receipt would describe a command the
	// operator has not been told about yet.
	if confirmed := strings.Index(tail, "EffectCertainty:"); confirmed < 0 || confirmed > announced {
		t.Fatalf("tail was armed before the receipt: %q", tail)
	}
	// Entering the session already arms a tail, so the injection must not also
	// read a snapshot: the automatic step replaced the one-shot read instead of
	// running beside it.
	if stub.outputCalls != 0 {
		t.Fatalf("snapshot reads=%d want=0 (both the entry and the injection arm tails)", stub.outputCalls)
	}
}

// TestUnitBtwAutoFollowIsBoundedByTheReplDefaults proves the automatic tail
// carries the REPL budget. Without it the adapter would clamp the tail to 20
// lines, so the operator would see a 300-line entry tail followed by a stream
// that only tailed 20.
func TestUnitBtwAutoFollowIsBoundedByTheReplDefaults(t *testing.T) {
	stub := newSendFollowStub()
	if _, diagnostics, _ := runSendREPL(t, stub, []string{"cd host-one/endpoint-1/res-1", `btw {"text":"hi"}`, "y", "quit"}); diagnostics != "" {
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

// TestUnitBtwAutoFollowStartsTheStreamOnTheNextPrompt proves the armed intent
// becomes a real stream for the following prompt, so the operator reads live
// output without typing logs -f, and that a keypress stops it.
func TestUnitBtwAutoFollowStartsTheStreamOnTheNextPrompt(t *testing.T) {
	stub := newSendFollowStub()
	_, diagnostics, reader := runSendREPL(t, stub, []string{"cd host-one/endpoint-1/res-1", `btw {"text":"hi"}`, "y", "quit"})
	if diagnostics != "" {
		t.Fatalf("unexpected diagnostics: %q", diagnostics)
	}
	// Two streams open: the entry transition's tail on the prompt after cd, and
	// the injection's tail on the prompt after the confirmation.
	if stub.followCount() != 2 {
		t.Fatalf("streams opened=%d want=2 (entry and injection)", stub.followCount())
	}
	stream := armedFollowSession(t, reader)
	labelled, ok := stream.(followStopLabel)
	if !ok {
		t.Fatalf("the armed session does not name itself as a follow: %T", stream)
	}
	if label := labelled.StopLabel(); label != "follow stopped" {
		t.Fatalf("stop label=%q, want the follow wording", label)
	}
	stream.Stop()
}

// TestUnitBtwAutoFollowDegradesToASnapshotWithoutStreaming proves a client that
// cannot stream still shows the effect of the injection, and says why it is a
// snapshot. A snapshot presented as a stream would look complete while silently
// missing everything written after it.
func TestUnitBtwAutoFollowDegradesToASnapshotWithoutStreaming(t *testing.T) {
	stub := scopeStub()
	output, diagnostics, _ := runSendREPL(t, stub, []string{"cd host-one/endpoint-1/res-1", `btw {"text":"hi"}`, "y", "quit"})
	if diagnostics != "" {
		t.Fatalf("a degraded automatic step must not be an error: %q", diagnostics)
	}
	if stub.admit != 1 {
		t.Fatalf("admitted %d commands, want 1", stub.admit)
	}
	if requests := sendOutputRequests(stub); len(requests) != 1 {
		t.Fatalf("post-btw snapshot reads=%+v, want exactly one", requests)
	}
	if !strings.Contains(output, "btw completed; automatic follow unavailable:") {
		t.Fatalf("missing degradation diagnostic: %q", output)
	}
	if !strings.Contains(output, "rendered one bounded snapshot instead") {
		t.Fatalf("degradation did not name the substitute: %q", output)
	}
}

// TestUnitBtwAutoFollowDegradesWithoutAKeypressSeam proves a reader that cannot
// observe a keypress never arms a tail it could not stop, and reports the
// substitute instead of silently doing nothing.
func TestUnitBtwAutoFollowDegradesWithoutAKeypressSeam(t *testing.T) {
	stub := newSendFollowStub()
	output, diagnostics := runScope(t, stub, btwScenario, ColorPolicy{})
	if diagnostics != "" {
		t.Fatalf("a degraded automatic step must not be an error: %q", diagnostics)
	}
	if stub.followCount() != 0 {
		t.Fatalf("streams opened=%d, want none without a keypress seam", stub.followCount())
	}
	if requests := sendOutputRequests(&stub.interactiveStub); len(requests) != 1 {
		t.Fatalf("post-btw snapshot reads=%+v, want exactly one", requests)
	}
	if !strings.Contains(output, "btw completed; automatic follow unavailable:") {
		t.Fatalf("missing degradation diagnostic: %q", output)
	}
}

// TestUnitBtwAutoFollowSkipsARejectedInjection proves the tail is triggered by a
// completed injection only: a declined confirmation arms nothing, because no
// context reached the provider and no new output is expected.
func TestUnitBtwAutoFollowSkipsARejectedInjection(t *testing.T) {
	stub := newSendFollowStub()
	output, diagnostics, _ := runSendREPL(t, stub, []string{"cd host-one/endpoint-1/res-1", `btw {"text":"hi"}`, "n", "quit"})
	if diagnostics != "" {
		t.Fatalf("unexpected diagnostics: %q", diagnostics)
	}
	if stub.admit != 0 {
		t.Fatalf("admitted %d commands, want none", stub.admit)
	}
	if requests := actionFollowRequests(stub); len(requests) != 0 {
		t.Fatalf("follow requests=%+v, want none after a declined confirmation", requests)
	}
	if !strings.Contains(output, "btw cancelled") {
		t.Fatalf("missing cancellation evidence: %q", output)
	}
}

// TestUnitBtwAutoFollowKeepsTheExplicitLogsFollow proves the automatic step does
// not replace the explicit command: an operator who asks for logs -f still gets
// a second stream with its own request.
func TestUnitBtwAutoFollowKeepsTheExplicitLogsFollow(t *testing.T) {
	stub := newSendFollowStub()
	if _, diagnostics, _ := runSendREPL(t, stub, []string{"cd host-one/endpoint-1/res-1", `btw {"text":"hi"}`, "y", "logs -f", "quit"}); diagnostics != "" {
		t.Fatalf("unexpected diagnostics: %q", diagnostics)
	}
	// The entry transition opens the first tail, so the automatic and the explicit
	// ones are the remaining two.
	requests := stub.followRequests()
	if len(requests) != 3 {
		t.Fatalf("follow requests=%+v, want the entry, the automatic and the explicit one", requests)
	}
}
