package tui

import (
	"bytes"
	"context"
	"strings"
	"testing"

	"topsailai_agent_cluster/internal/protocol"
)

// logsFailureStub serves one inventory row and one output snapshot carrying an
// error code, which is what the Endpoint returns when the read failed.
//
// It exists because the JSON form of logs had no failure test at all. The human
// form was guarded and the JSON form was not, so the same failed read exited 2 in
// one form and 0 in the other. A script that checked the exit status read the JSON
// form as an empty successful read.
type logsFailureStub struct {
	*unitCAPI
	response protocol.OutputSnapshotResponse
}

func (s *logsFailureStub) GetOutput(context.Context, string, string, string, int, int) (protocol.OutputSnapshotResponse, error) {
	return s.response, nil
}

// TestLogsJSONReportsAnErrorCodeAsAFailure proves the JSON form of logs reports a
// failed read as a failure instead of printing the error code as a document.
//
// The assertion is on both halves, because either one alone can pass for the wrong
// reason: returning an error while still writing the document would leave stdout
// looking like a successful answer, and writing nothing while returning nil would
// look like an empty successful read.
func TestLogsJSONReportsAnErrorCodeAsAFailure(t *testing.T) {
	stub := &logsFailureStub{
		unitCAPI: newUnitCAPI(),
		response: protocol.OutputSnapshotResponse{ErrorCode: "unknown_resource"},
	}
	runner := CommandRunner{API: stub, Policy: LegacyPolicy}
	var out bytes.Buffer

	err := runner.Logs(context.Background(), &out, "endpoint-1", "res_1", 0, 3, true, ColorPolicy{})

	if err == nil {
		t.Fatalf("the JSON form reported a snapshot carrying error code %q as success, so a script cannot tell a failed read from an empty successful one", "unknown_resource")
	}
	if !strings.Contains(err.Error(), "unknown_resource") {
		t.Fatalf("the failure does not name the error code, so the operator cannot tell what failed: %v", err)
	}
	if out.Len() != 0 {
		t.Fatalf("the JSON form wrote a document for a failed read (%q), so stdout looks like a successful answer", out.String())
	}
}

// TestLogsHumanFormReportsAnErrorCodeAsAFailure proves the human form keeps the
// behaviour it already had, so the shared guard did not replace one form's defect
// with the other form's defect.
func TestLogsHumanFormReportsAnErrorCodeAsAFailure(t *testing.T) {
	stub := &logsFailureStub{
		unitCAPI: newUnitCAPI(),
		response: protocol.OutputSnapshotResponse{ErrorCode: "unknown_resource"},
	}
	runner := CommandRunner{API: stub, Policy: LegacyPolicy}
	var out bytes.Buffer

	err := runner.Logs(context.Background(), &out, "endpoint-1", "res_1", 0, 3, false, ColorPolicy{})

	if err == nil {
		t.Fatalf("the human form reported a snapshot carrying error code %q as success", "unknown_resource")
	}
	if out.Len() != 0 {
		t.Fatalf("the human form wrote output for a failed read: %q", out.String())
	}
}

// TestLogsJSONStillRendersSuccessfulData proves the shared guard did not turn every
// JSON read into a failure.
//
// Without this, a guard that rejected every snapshot would pass both tests above
// while breaking every successful read.
func TestLogsJSONStillRendersSuccessfulData(t *testing.T) {
	stub := &logsFailureStub{
		unitCAPI: newUnitCAPI(),
		response: protocol.OutputSnapshotResponse{Data: "line one", ObservedAtMS: 1794470400000},
	}
	runner := CommandRunner{API: stub, Policy: LegacyPolicy}
	var out bytes.Buffer

	if err := runner.Logs(context.Background(), &out, "endpoint-1", "res_1", 0, 3, true, ColorPolicy{}); err != nil {
		t.Fatalf("a successful JSON read was reported as a failure: %v", err)
	}
	if !strings.Contains(out.String(), "line one") {
		t.Fatalf("the JSON form did not render the snapshot body: %q", out.String())
	}
}
