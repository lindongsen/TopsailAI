package tui

import (
	"bytes"
	"context"
	"errors"
	"strings"
	"testing"

	"topsailai_agent_cluster/internal/protocol"
)

func TestListRowsCoversMissingReportEmptyReportAndFilter(t *testing.T) {
	last := int64(7)
	endpoints := []protocol.Endpoint{{EndpointID: "e1"}, {EndpointID: "e2"}}
	reports := map[string]protocol.InventoryReport{
		"e1": {CollectionStatus: protocol.CollectionSucceeded, Adapters: []protocol.AdapterSummary{{AdapterID: "a1", LastSuccessAtMS: &last}}, Sessions: nil},
	}
	rows := ListRows(endpoints, reports, "")
	if len(rows) != 2 || rows[0].State != "no sessions" || rows[1].CollectionStatus != "unknown" {
		t.Fatalf("rows=%#v", rows)
	}
	if filtered := ListRows(endpoints, reports, "e2"); len(filtered) != 1 || filtered[0].EndpointID != "e2" {
		t.Fatalf("filtered rows=%#v", filtered)
	}
}

func TestFindSessionReturnsEndpointSessionAndError(t *testing.T) {
	endpoints := []protocol.Endpoint{{EndpointID: "e1"}}
	reports := map[string]protocol.InventoryReport{"e1": {Sessions: []protocol.Session{{SessionID: "s1"}}}}
	endpoint, _, session, err := FindSession("e1", endpoints, reports)
	if err != nil || endpoint.EndpointID != "e1" || session != nil {
		t.Fatalf("endpoint result=%#v session=%#v err=%v", endpoint, session, err)
	}
	_, _, session, err = FindSession("s1", endpoints, reports)
	if err != nil || session == nil || session.SessionID != "s1" {
		t.Fatalf("session=%#v err=%v", session, err)
	}
	if _, _, _, err = FindSession("missing", endpoints, reports); err == nil {
		t.Fatal("missing session unexpectedly found")
	}
}

func TestStatusLabelCoversEvidenceStates(t *testing.T) {
	cases := []struct {
		status  protocol.CommandStatus
		receipt protocol.ExecutionReceipt
		want    string
	}{
		{protocol.StatusEndpointAdmitted, protocol.ExecutionReceipt{}, "endpoint received"},
		{protocol.StatusExecuting, protocol.ExecutionReceipt{EffectCertainty: protocol.EffectUnknown}, "effect unknown"},
		{protocol.StatusExecuting, protocol.ExecutionReceipt{}, "executing"},
		{protocol.StatusRejected, protocol.ExecutionReceipt{}, "failed"},
		{protocol.StatusCancelled, protocol.ExecutionReceipt{}, string(protocol.StatusCancelled)},
	}
	for _, tc := range cases {
		if got := StatusLabel(tc.status, tc.receipt); got != tc.want {
			t.Errorf("StatusLabel(%q)=%q, want %q", tc.status, got, tc.want)
		}
	}
}

func TestRenderFunctionsProduceStableEvidence(t *testing.T) {
	var jsonOut bytes.Buffer
	if err := RenderJSON(&jsonOut, map[string]string{"status": "ok"}); err != nil || !strings.Contains(jsonOut.String(), "\"status\": \"ok\"") {
		t.Fatalf("json=%q err=%v", jsonOut.String(), err)
	}
	var rowsOut bytes.Buffer
	RenderRows(&rowsOut, []SessionRow{{EndpointID: "e1", State: "idle", Stale: true, LastSuccessAtMS: ptr(3)}})
	if !strings.Contains(rowsOut.String(), "stale") || !strings.Contains(rowsOut.String(), "last_success_at_ms=3") {
		t.Fatalf("rows=%q", rowsOut.String())
	}
	var detailOut bytes.Buffer
	RenderDetail(&detailOut, Detail{Endpoint: protocol.Endpoint{EndpointID: "e1"}, Inventory: protocol.InventoryReport{}, CommandHistory: nil})
	if !strings.Contains(detailOut.String(), "no commands") {
		t.Fatalf("detail=%q", detailOut.String())
	}
	var snapshotOut bytes.Buffer
	RenderSnapshot(&snapshotOut, 9, "output", true)
	if !strings.Contains(snapshotOut.String(), "truncated: true") {
		t.Fatalf("snapshot=%q", snapshotOut.String())
	}
	if got := ReceiptForStatus(map[string]any{"outcome": "finished"}); got.Outcome != "finished" {
		t.Fatalf("receipt=%#v", got)
	}
}

func TestWaitForTerminalHandlesReaderErrorAndNilReader(t *testing.T) {
	reader := &errorStateReader{err: errors.New("unavailable")}
	if _, err := WaitForTerminal(context.Background(), reader, "c1", 0); err == nil {
		t.Fatal("expected initial reader error")
	}
	if IsTerminalState(map[string]any{"status": "executing"}) {
		t.Fatal("executing reported terminal")
	}
}

type errorStateReader struct{ err error }

func (r *errorStateReader) GetCommand(context.Context, string) (map[string]any, error) {
	return nil, r.err
}

func ptr(value int64) *int64 { return &value }
