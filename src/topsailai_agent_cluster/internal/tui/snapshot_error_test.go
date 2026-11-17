package tui

import (
	"bytes"
	"context"
	"strings"
	"testing"

	"topsailai_agent_cluster/internal/protocol"
)

// snapshotErrorStub serves one output snapshot carrying an error code and no data,
// which is what the Endpoint returns when the read failed.
//
// It exists because the failure path had no test at all: the renderer wrote the code
// to stdout and returned nil, so a provider failure was indistinguishable from a
// successful read whose content happened to be the code word.
type snapshotErrorStub struct {
	*unitCAPI
	response protocol.OutputSnapshotResponse
}

func (s *snapshotErrorStub) GetOutput(context.Context, string, string, string, int, int) (protocol.OutputSnapshotResponse, error) {
	return s.response, nil
}

// TestRenderSessionSnapshotReportsAnErrorCodeAsAFailure proves that a snapshot
// carrying an error code is reported as a failure rather than printed as content.
//
// The exit status is the only machine-readable signal a script has. Before this test
// the renderer wrote the code to stdout and returned nil, so `logs` exited 0 while the
// read had failed, and a script that checked the status concluded the read succeeded.
// The operator saw a bare token such as "unknown_resource" with no explanation.
//
// The assertion is on both halves, because either one alone can pass for the wrong
// reason: returning an error while still printing the token would leave the output
// looking like data, and printing nothing while returning nil would look like an
// empty successful read.
func TestRenderSessionSnapshotReportsAnErrorCodeAsAFailure(t *testing.T) {
	stub := &snapshotErrorStub{
		unitCAPI: newUnitCAPI(),
		response: protocol.OutputSnapshotResponse{ErrorCode: "unknown_resource"},
	}
	runner := CommandRunner{API: stub, Policy: InteractivePolicy}
	var out bytes.Buffer

	err := runner.RenderSessionSnapshot(context.Background(), &out, "ac.ai-dev", "res_1", "gen_1", 0, 0, ColorPolicy{})

	if err == nil {
		t.Fatalf("a snapshot carrying error code %q was reported as success, so a script cannot tell a failed read from a successful one", "unknown_resource")
	}
	if !strings.Contains(err.Error(), "unknown_resource") {
		t.Fatalf("the failure does not name the error code, so the operator cannot tell what failed: %v", err)
	}
	if out.Len() != 0 {
		t.Fatalf("the error code was written to stdout as content (%q), so the output looks like data instead of a failure", out.String())
	}
}

// TestRenderSessionSnapshotStillRendersSuccessfulData proves the change did not
// affect the success path.
//
// Without this, a fix that returned an error for every snapshot would pass the test
// above while breaking every successful read.
func TestRenderSessionSnapshotStillRendersSuccessfulData(t *testing.T) {
	stub := &snapshotErrorStub{
		unitCAPI: newUnitCAPI(),
		response: protocol.OutputSnapshotResponse{Data: "line one\nline two", ObservedAtMS: 1794470400000},
	}
	runner := CommandRunner{API: stub, Policy: InteractivePolicy}
	var out bytes.Buffer

	if err := runner.RenderSessionSnapshot(context.Background(), &out, "ac.ai-dev", "res_1", "gen_1", 0, 0, ColorPolicy{}); err != nil {
		t.Fatalf("a successful snapshot was reported as a failure: %v", err)
	}
	if !strings.Contains(out.String(), "line one") {
		t.Fatalf("the snapshot body was not rendered, so a successful read produced no output: %q", out.String())
	}
}
