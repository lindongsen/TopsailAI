package tui

import (
	"strings"
	"testing"

	"topsailai_agent_cluster/internal/protocol"
)

// TestStatusSummaryNamesTheUnverifiedSubset proves the summary distinguishes an
// unverified session from any other unknown state. Both land in the unknown
// bucket, so without the subset label an operator cannot tell "the provider
// restarted and every session needs a resume" from "the provider reported an
// unknown state".
func TestStatusSummaryNamesTheUnverifiedSubset(t *testing.T) {
	rows := []SessionRow{
		{SessionID: "a", State: "running"},
		{SessionID: "b", State: "unknown", Unverified: true},
		{SessionID: "c", State: "unknown", Unverified: true},
		{SessionID: "d", State: "unknown"},
	}
	var out strings.Builder
	if err := writeStatusSummary(&out, rows, ColorPolicy{}); err != nil {
		t.Fatal(err)
	}
	summary := out.String()
	if !strings.Contains(summary, "unknown(3)") {
		t.Fatalf("unknown bucket must still count every unknown row, got %q", summary)
	}
	if !strings.Contains(summary, "unverified(2)") {
		t.Fatalf("summary must name the unverified subset, got %q", summary)
	}
	if !strings.Contains(summary, "running(1)") {
		t.Fatalf("summary lost the running bucket, got %q", summary)
	}
}

// TestStatusSummaryOmitsUnverifiedWhenAbsent keeps the summary unchanged for a
// fleet with no unverified session, so the label never appears as noise.
func TestStatusSummaryOmitsUnverifiedWhenAbsent(t *testing.T) {
	rows := []SessionRow{
		{SessionID: "a", State: "running"},
		{SessionID: "b", State: "unknown"},
	}
	var out strings.Builder
	if err := writeStatusSummary(&out, rows, ColorPolicy{}); err != nil {
		t.Fatal(err)
	}
	if strings.Contains(out.String(), "unverified") {
		t.Fatalf("summary must not mention unverified when none exist, got %q", out.String())
	}
}

// TestListRowsDerivesUnverifiedFromStateReason proves the flag comes from the
// reported reason rather than from the state alone, because an unknown state
// with another reason is a different condition.
func TestListRowsDerivesUnverifiedFromStateReason(t *testing.T) {
	endpoints := []protocol.Endpoint{{EndpointID: "endpoint-1", ConnectionState: "online"}}
	reports := map[string]protocol.InventoryReport{
		"endpoint-1": {
			CollectionStatus: protocol.CollectionSucceeded,
			Adapters:         []protocol.AdapterSummary{{AdapterID: "adapter", DataKnown: true}},
			Sessions: []protocol.Session{
				{SessionID: "unverified", AdapterID: "adapter", State: protocol.SessionStateUnknown, StateReason: protocol.StateReasonLivenessUnverified},
				{SessionID: "other", AdapterID: "adapter", State: protocol.SessionStateUnknown, StateReason: "provider_reported"},
			},
		},
	}
	rows := ListRows(endpoints, reports, "")
	if len(rows) != 2 {
		t.Fatalf("row count=%d want 2", len(rows))
	}
	if !rows[0].Unverified {
		t.Fatalf("liveness_unverified row must be marked unverified: %+v", rows[0])
	}
	if rows[1].Unverified {
		t.Fatalf("a different unknown reason must not be marked unverified: %+v", rows[1])
	}
}
