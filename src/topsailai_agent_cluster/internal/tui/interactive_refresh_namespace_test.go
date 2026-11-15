package tui

import (
	"testing"

	"topsailai_agent_cluster/internal/protocol"
)

// TestInteractiveRefreshRestoresLiveNamespaceAfterHistory proves a refresh
// reclaims the row numbers exactly as a list render does.
//
// A refresh renders the live table, so the history namespace must not survive it.
// When it did, a number typed at the fresh table still resolved against the
// history rows the operator could no longer see, and the transition reported a
// history-row error instead of entering the visible row.
func TestInteractiveRefreshRestoresLiveNamespaceAfterHistory(t *testing.T) {
	stub := historyScenarioStub(
		[]protocol.HistoryRow{{ProviderSessionID: "wa-past", Resumable: true, ResourceID: "res-past"}},
		historyReport(historyLiveSession("res-live", "wa-live", "gen-1")),
	)

	output, diagnostics := runScope(t, stub, "history endpoint-1\nrefresh\ncd 1\nexit\n", ColorPolicy{})
	if diagnostics != "" {
		t.Fatalf("unexpected diagnostics: %q", diagnostics)
	}
	if got := lastPrompt(output); got != "session[host-one/wa-live]>" {
		t.Fatalf("prompt=%q, want the refreshed live row rather than the history row", got)
	}
}
