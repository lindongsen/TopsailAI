package tui

import (
	"context"
	"io"
	"strings"
	"testing"

	"topsailai_agent_cluster/internal/protocol"
)

// TestInteractiveTableHidesSessionIDColumn proves the interactive table drops the
// SESSION_ID column. The provider session identifier is a long opaque value that
// only widens the table, while the operator selects a session by row number or
// name, so printing it costs width without adding a usable selector.
func TestInteractiveTableHidesSessionIDColumn(t *testing.T) {
	output, diagnostics := runScope(t, scopeStub(), "list\nexit\n", ColorPolicy{})
	if diagnostics != "" {
		t.Fatalf("unexpected diagnostics: %q", diagnostics)
	}
	if strings.Contains(output, "SESSION_ID") {
		t.Fatalf("interactive table still prints the SESSION_ID header: %q", output)
	}
	if strings.Contains(output, "provider-res-1") {
		t.Fatalf("interactive table still prints the provider session ID cell: %q", output)
	}
	// The remaining columns must still be rendered, so the column is hidden rather
	// than the whole table being suppressed.
	if !strings.Contains(output, "SESSION_NAME") || !strings.Contains(output, "DATA_STATUS") {
		t.Fatalf("interactive table lost unrelated columns: %q", output)
	}
}

// TestStandaloneListKeepsSessionIDColumn proves the standalone command keeps the
// column. Its output is the scripting surface parsed by tests and automation, so
// hiding the column there would silently break every consumer that reads it.
func TestStandaloneListKeepsSessionIDColumn(t *testing.T) {
	api := &runnerStubAPI{
		endpoints: []protocol.Endpoint{{EndpointID: "ep"}},
		reports: map[string]protocol.InventoryReport{"ep": {
			CollectionStatus: protocol.CollectionSucceeded,
			Adapters:         []protocol.AdapterSummary{{AdapterID: "adapter", DataKnown: true, CollectionStatus: protocol.CollectionSucceeded}},
			Sessions: []protocol.Session{{
				SessionID:         "session",
				ProviderSessionID: "provider-session",
				AdapterID:         "adapter",
				Generation:        "generation",
				State:             "running",
				CollectionStatus:  protocol.CollectionSucceeded,
			}},
		}},
	}
	var out strings.Builder
	if err := (CommandRunner{API: api}).ListWithOptions(context.Background(), &out, io.Discard, "", false, TableOptions{}); err != nil {
		t.Fatalf("ListWithOptions: %v", err)
	}
	rendered := out.String()
	if !strings.Contains(rendered, "SESSION_ID") {
		t.Fatalf("standalone list dropped the SESSION_ID header: %q", rendered)
	}
	if !strings.Contains(rendered, "provider-session") {
		t.Fatalf("standalone list dropped the provider session ID cell: %q", rendered)
	}
}

// TestHiddenSessionIDStillResolvesInStandaloneShow proves hiding the column is a
// presentation choice only. The provider session identifier stays on the row, so
// the standalone show command must still resolve it to the same resource;
// otherwise the operator would lose a selector the documentation advertises.
func TestHiddenSessionIDStillResolvesInStandaloneShow(t *testing.T) {
	api := &runnerStubAPI{
		endpoints: []protocol.Endpoint{{EndpointID: "ep", Hostname: "host-one"}},
		reports: map[string]protocol.InventoryReport{"ep": {
			CollectionStatus: protocol.CollectionSucceeded,
			Adapters:         []protocol.AdapterSummary{{AdapterID: "adapter", DataKnown: true, CollectionStatus: protocol.CollectionSucceeded}},
			Sessions: []protocol.Session{{
				SessionID:         "res-1",
				ProviderSessionID: "provider-res-1",
				AdapterID:         "adapter",
				Generation:        "generation-1",
				State:             "running",
				CollectionStatus:  protocol.CollectionSucceeded,
			}},
		}},
	}
	var out strings.Builder
	if err := (CommandRunner{API: api}).Show(context.Background(), &out, "provider-res-1", false); err != nil {
		t.Fatalf("Show by provider session ID: %v", err)
	}
	if !strings.Contains(out.String(), "session: res-1") {
		t.Fatalf("provider session ID did not resolve to the same resource: %q", out.String())
	}
}

// TestHiddenSessionIDStillNamesTheStopConfirmation proves the confirmation
// question keeps naming the provider session identifier. The question is now the
// only place the operator sees that value, so dropping it would leave the operator
// confirming an action against an identifier they never saw.
func TestHiddenSessionIDStillNamesTheStopConfirmation(t *testing.T) {
	output, diagnostics := runScope(t, scopeStub(), "list\nstop 1\ny\nexit\n", ColorPolicy{})
	if diagnostics != "" {
		t.Fatalf("unexpected diagnostics: %q", diagnostics)
	}
	if !strings.Contains(output, "stop session provider-res-1 (res-1)? Confirm stop?") {
		t.Fatalf("confirmation question lost the provider session ID: %q", output)
	}
}

// TestStandaloneHistoryKeepsSessionIDColumn proves the standalone history command
// keeps the column. Only the interactive surface hides it, because the standalone
// output is the scripting surface parsed by tests and automation.
func TestStandaloneHistoryKeepsSessionIDColumn(t *testing.T) {
	api := &historyStubAPI{
		endpoints: []protocol.Endpoint{{EndpointID: "ep", Hostname: "host-one"}},
		reports:   map[string]protocol.InventoryReport{"ep": historyReport()},
		history: map[string]protocol.HistoryResult{"ep": {Rows: []protocol.HistoryRow{
			{ProviderSessionID: "provider-past", Resumable: true},
		}}},
	}
	var out strings.Builder
	if err := (CommandRunner{API: api}).History(context.Background(), &out, io.Discard, "ep", false, TableOptions{}); err != nil {
		t.Fatalf("History: %v", err)
	}
	rendered := out.String()
	if !strings.Contains(rendered, "SESSION_ID") {
		t.Fatalf("standalone history dropped the SESSION_ID header: %q", rendered)
	}
	if !strings.Contains(rendered, "provider-past") {
		t.Fatalf("standalone history dropped the provider session ID cell: %q", rendered)
	}
}
