package tui

import (
	"context"
	"errors"
	"strings"
	"testing"

	"topsailai_agent_cluster/internal/protocol"
)

// failingOutputStub fails every output read so the automatic snapshot error
// branch is reachable without changing the shared navigation stub.
type failingOutputStub struct {
	*navStub
}

func (s *failingOutputStub) GetOutput(context.Context, string, string, string, int, int) (protocol.OutputSnapshotResponse, error) {
	s.outputCalls++
	return protocol.OutputSnapshotResponse{}, errors.New("output unavailable")
}

// TestUnitU5LeavingSessionScopeEmitsNoSnapshot proves that leaving session scope
// does not trigger another automatic read: only the entry transition reads.
func TestUnitU5LeavingSessionScopeEmitsNoSnapshot(t *testing.T) {
	stub := singleHostStub()
	output, _ := runNav(t, stub, "cd ai-dev/endpoint-1/res-1\ncd ..\nquit\n")
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
	output, _ := runNav(t, stub, "cd ai-dev/endpoint-1/res-1\ncd res-1\nquit\n")
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
	output, _ := runNav(t, stub, "cd ai-dev/endpoint-1/res-1\nquit\n")
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
