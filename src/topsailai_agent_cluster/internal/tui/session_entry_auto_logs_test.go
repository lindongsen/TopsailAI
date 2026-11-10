package tui

import (
	"context"
	"errors"
	"strings"
	"testing"

	"topsailai_agent_cluster/internal/protocol"
)

// sessionEntryScenario enters one session of the shared two-endpoint fixture and
// then leaves the REPL, so the entry transition is the only automatic output step
// in the run. The fixture hostname is host-one.
const sessionEntryScenario = "cd host-one/endpoint-1/res-1\nquit\n"

// sessionEntryScenarioHostA is the same transition for the single-host fixture,
// whose hostname is ai-dev. A cd that names the wrong hostname never enters the
// session, so the scenario and the fixture must agree or the test proves nothing.
// It ends with exit rather than quit, because quit returns to workspace scope and
// would replace the session prompt this scenario asserts.
const sessionEntryScenarioHostA = "cd ai-dev/endpoint-1/res-1\nexit\n"

// degradedFollowDiagnostic is the exact wording a client that cannot stream, or a
// reader that cannot observe a keypress, prints instead of arming a live tail.
const degradedFollowDiagnostic = "session selected; automatic follow unavailable: this input mode cannot stop a live tail; rendered one bounded snapshot instead"

// failingOutputStub fails every output read so the degraded snapshot error branch
// is reachable without changing the shared navigation stub.
type failingOutputStub struct {
	*navStub
}

func (s *failingOutputStub) GetOutput(context.Context, string, string, string, int, int) (protocol.OutputSnapshotResponse, error) {
	s.outputCalls++
	return protocol.OutputSnapshotResponse{}, errors.New("output unavailable")
}

// unverifiedGenerationStub serves one session whose liveness was never verified,
// which the provider reports with an empty generation.
func unverifiedGenerationStub() *navStub {
	return &navStub{
		endpoints: []protocol.Endpoint{{EndpointID: "endpoint-1", Hostname: "ai-dev", DisplayName: "host-a"}},
		reports:   map[string]protocol.InventoryReport{"endpoint-1": navInventory("res-1", "")},
	}
}

// TestUnitSessionEntryArmsOneLiveTail proves that entering a session arms exactly
// one live tail for the identity the transition already validated, and that it
// arms the same intent logs -f arms. A one-shot snapshot stops at the moment it
// was read while the agent keeps writing, so the operator would read a complete
// looking panel that silently missed everything written afterwards.
func TestUnitSessionEntryArmsOneLiveTail(t *testing.T) {
	stub := newSendFollowStub()
	output, diagnostics, reader := runSendREPL(t, stub, []string{"cd host-one/endpoint-1/res-1", "quit"})
	if diagnostics != "" {
		t.Fatalf("unexpected diagnostics: %q", diagnostics)
	}
	requests := stub.followRequests()
	if len(requests) != 1 {
		t.Fatalf("follow requests=%+v, want exactly one", requests)
	}
	request := requests[0]
	if request.endpointID != "endpoint-1" || request.resourceID != "res-1" || request.generation != "generation-1" {
		t.Fatalf("wrong follow identity tuple: %+v", request)
	}
	// The automatic tail must carry the REPL budget. Without it the adapter would
	// clamp the tail to 20 lines, so the operator would read a 300-line entry tail
	// followed by a stream that only tailed 20.
	if request.maxLines != DefaultInteractiveMaxLines {
		t.Fatalf("follow maxLines=%d want=%d", request.maxLines, DefaultInteractiveMaxLines)
	}
	if request.maxBytes != 64<<10 {
		t.Fatalf("follow maxBytes=%d want=%d", request.maxBytes, 64<<10)
	}
	// The tail replaced the snapshot instead of running beside it, so the entry
	// transition must not have read a snapshot at all.
	if stub.outputCalls != 0 {
		t.Fatalf("snapshot reads=%d want=0 (the entry transition must arm a tail only)", stub.outputCalls)
	}
	if !strings.Contains(output, "log.follow> res-1 (any key stops)") {
		t.Fatalf("entry did not announce the live tail: %q", output)
	}
	armed := armedFollowSession(t, reader)
	if armed == nil {
		t.Fatal("no prompt carried the armed stream")
	}
}

// TestUnitSessionEntryDegradesToSnapshotWithoutStreaming proves that a client
// without the streaming seam still shows the entry output, and says why it is a
// snapshot. A snapshot presented as a stream would look complete while silently
// missing everything written after it, so the degradation must be announced.
func TestUnitSessionEntryDegradesToSnapshotWithoutStreaming(t *testing.T) {
	stub := singleHostStub()
	output, _ := runNav(t, stub, sessionEntryScenarioHostA)
	if stub.outputCalls != 1 {
		t.Fatalf("snapshot reads=%d want=1", stub.outputCalls)
	}
	if got := stub.outputRequests[0].resourceID; got != "res-1" {
		t.Fatalf("snapshot resource=%q want=res-1", got)
	}
	if !strings.Contains(output, degradedFollowDiagnostic) {
		t.Fatalf("output missing the degradation reason: %q", output)
	}
	if !strings.Contains(lastPrompt(output), "session[") {
		t.Fatalf("prompt after entry = %q, want session scope", lastPrompt(output))
	}
}

// TestUnitSessionEntryDegradesToSnapshotWithoutWatchReader proves the second half
// of the capability guard independently: a client that can stream still degrades
// when the reader cannot observe a keypress, because such a reader could never
// stop the tail.
func TestUnitSessionEntryDegradesToSnapshotWithoutWatchReader(t *testing.T) {
	stub := newSendFollowStub()
	output, _ := runNav(t, stub, sessionEntryScenario)
	if stub.followCount() != 0 {
		t.Fatalf("streams opened=%d want=0 without a watch-capable reader", stub.followCount())
	}
	if stub.outputCalls != 1 {
		t.Fatalf("snapshot reads=%d want=1", stub.outputCalls)
	}
	if !strings.Contains(output, degradedFollowDiagnostic) {
		t.Fatalf("output missing the degradation reason: %q", output)
	}
}

// TestUnitSessionEntryRefusesUnverifiedSessionAndArmsNothing proves that an
// unverified session is never entered, so no stream is ever armed for a
// generation that cannot prove which process it would reach. The refusal names
// resume as the recovery step, because the record really exists.
func TestUnitSessionEntryRefusesUnverifiedSessionAndArmsNothing(t *testing.T) {
	stub := unverifiedGenerationStub()
	output, diagnostics := runNav(t, stub, sessionEntryScenarioHostA)
	if stub.outputCalls != 0 {
		t.Fatalf("snapshot reads=%d want=0 (the entry was refused)", stub.outputCalls)
	}
	if !strings.Contains(diagnostics, "is unverified on endpoint") || !strings.Contains(diagnostics, "use resume to resume it") {
		t.Fatalf("diagnostics missing the unverified refusal: %q", diagnostics)
	}
	if !strings.Contains(lastPrompt(output), "workspace>") {
		t.Fatalf("prompt after refused entry = %q, want workspace scope", lastPrompt(output))
	}
}

// TestUnitU5LeavingSessionScopeEmitsNoSnapshot proves that leaving session scope
// does not trigger another automatic read: only the entry transition reads.
func TestUnitU5LeavingSessionScopeEmitsNoSnapshot(t *testing.T) {
	stub := singleHostStub()
	output, _ := runNav(t, stub, "cd ai-dev/endpoint-1/res-1\ncd ..\nexit\n")
	if stub.outputCalls != 1 {
		t.Fatalf("output requests after entering and leaving session scope = %d, want 1", stub.outputCalls)
	}
	if got := stub.outputRequests[0].resourceID; got != "res-1" {
		t.Fatalf("automatic read resource = %q, want res-1", got)
	}
	if !strings.Contains(lastPrompt(output), "endpoint[") {
		t.Fatalf("prompt after cd .. = %q, want endpoint scope", lastPrompt(output))
	}
}

// TestUnitU7ReselectingSameSessionEmitsNoSnapshot proves that re-selecting the
// session already in scope is not a transition and therefore reads nothing.
func TestUnitU7ReselectingSameSessionEmitsNoSnapshot(t *testing.T) {
	stub := singleHostStub()
	output, _ := runNav(t, stub, "cd ai-dev/endpoint-1/res-1\ncd res-1\nexit\n")
	if stub.outputCalls != 1 {
		t.Fatalf("output requests after re-selecting the same session = %d, want 1", stub.outputCalls)
	}
	if !strings.Contains(lastPrompt(output), "session[") {
		t.Fatalf("prompt after re-selecting the same session = %q, want session scope", lastPrompt(output))
	}
}

// TestUnitU8FailedAutomaticReadReportsDiagnostic proves that a failed automatic
// read is reported and does not roll back the already validated selection.
func TestUnitU8FailedAutomaticReadReportsDiagnostic(t *testing.T) {
	stub := &failingOutputStub{navStub: singleHostStub()}
	output, _ := runNav(t, stub, "cd ai-dev/endpoint-1/res-1\nexit\n")
	if stub.outputCalls != 1 {
		t.Fatalf("output requests = %d, want 1", stub.outputCalls)
	}
	if !strings.Contains(output, "session selected; automatic logs failed: output unavailable") {
		t.Fatalf("output missing failure diagnostic: %q", output)
	}
	if !strings.Contains(lastPrompt(output), "session[") {
		t.Fatalf("prompt after failed automatic read = %q, want session scope preserved", lastPrompt(output))
	}
}
