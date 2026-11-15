package main

import (
	"os"
	"strings"
	"testing"

	"topsailai_agent_cluster/internal/protocol"
)

// TestInventoryCapabilityRevisionReadsTheReport pins the endpoint row's
// capability revision to the value the endpoint actually declared.
//
// The row is what the operator reads in the endpoint table, so a fixed value
// would report "unknown" for an endpoint that declared a revision. The last
// adapter that declared one wins, which is the same rule the capability API
// handler applies to the same report.
func TestInventoryCapabilityRevisionReadsTheReport(t *testing.T) {
	cases := []struct {
		name     string
		adapters []protocol.AdapterSummary
		want     string
	}{
		{
			name: "no adapters",
			want: capabilityRevisionUnknown,
		},
		{
			name:     "one adapter declares a revision",
			adapters: []protocol.AdapterSummary{{AdapterID: "a1", Capabilities: protocol.CapabilityDescriptor{Revision: "mock-manual-r1"}}},
			want:     "mock-manual-r1",
		},
		{
			name: "an adapter declares no revision",
			adapters: []protocol.AdapterSummary{
				{AdapterID: "a1"},
				{AdapterID: "a2", Capabilities: protocol.CapabilityDescriptor{Revision: "rev-2"}},
			},
			want: "rev-2",
		},
		{
			name: "the last declaring adapter wins",
			adapters: []protocol.AdapterSummary{
				{AdapterID: "a1", Capabilities: protocol.CapabilityDescriptor{Revision: "rev-1"}},
				{AdapterID: "a2", Capabilities: protocol.CapabilityDescriptor{Revision: "rev-2"}},
			},
			want: "rev-2",
		},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			got := inventoryCapabilityRevision(protocol.InventoryReport{Adapters: tc.adapters})
			if got != tc.want {
				t.Fatalf("inventoryCapabilityRevision = %q, want %q", got, tc.want)
			}
		})
	}
}

// TestEndpointIdentityIsStoredWithTheReportedRevision guards the production
// wiring: the inventory frame handler must read the revision from the decoded
// report instead of writing a fixed value into the endpoint row.
func TestEndpointIdentityIsStoredWithTheReportedRevision(t *testing.T) {
	source, err := os.ReadFile("main.go")
	if err != nil {
		t.Fatalf("read main.go: %v", err)
	}
	text := string(source)

	if !strings.Contains(text, "CapabilityRevision: inventoryCapabilityRevision(report)") {
		t.Fatal("main.go does not store the reported capability revision on the endpoint row")
	}
	if strings.Contains(text, `CapabilityRevision: "unknown"`) {
		t.Fatal("main.go still writes a fixed capability revision into the endpoint row")
	}
}
