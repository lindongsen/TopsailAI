package protocol

import (
	"encoding/json"
	"strings"
	"testing"
)

// TestHistoryRowCarriesNoRoutingIdentity pins the invariant that makes the whole
// design safe: a history row is never a routing identity. If a resource ID or a
// generation ever appears in this document, a fabricated generation could reach
// Inspect, revalidateGeneration or ReadOutput and silently mis-authorize a target.
func TestHistoryRowCarriesNoRoutingIdentity(t *testing.T) {
	row := HistoryRow{
		ProviderSessionID:        "wa-6cee12a5f2a0",
		ProviderDisplayName:      "session",
		ProviderProjectWorkspace: "/tmp/project",
		Task:                     "task",
		ProviderStatus:           "Idle",
		CreatedAtMS:              1,
		ModifiedAtMS:             2,
		ProviderNo:               1,
		Resumable:                true,
	}
	data, err := json.Marshal(row)
	if err != nil {
		t.Fatalf("marshal history row: %v", err)
	}
	// Exact key comparison, not substring matching: "session_id" is a substring of
	// "provider_session_id", so a substring check would reject the legitimate key.
	var fields map[string]json.RawMessage
	if err := json.Unmarshal(data, &fields); err != nil {
		t.Fatalf("decode history row: %v", err)
	}
	for _, forbidden := range []string{"resource_id", "generation", "session_id"} {
		if _, exists := fields[forbidden]; exists {
			t.Fatalf("history row must not carry the %q key: %s", forbidden, data)
		}
	}
	if _, exists := fields["provider_session_id"]; !exists {
		t.Fatalf("history row must carry the provider session key: %s", data)
	}
}

// TestHistoryResultEmptyRowsIsNotAnError keeps an empty provider answer distinct
// from a failed call, so an Endpoint with no history is never reported as broken.
func TestHistoryResultEmptyRowsIsNotAnError(t *testing.T) {
	result := HistoryResult{Rows: []HistoryRow{}, ObservedAtMS: 1}
	data, err := json.Marshal(result)
	if err != nil {
		t.Fatalf("marshal history result: %v", err)
	}
	if !strings.Contains(string(data), `"rows":[]`) {
		t.Fatalf("empty history must serialize an empty row list: %s", data)
	}
	if strings.Contains(string(data), "error_code") {
		t.Fatalf("an empty successful result must not carry an error code: %s", data)
	}
}

// TestHistoryBoundsAreBounded guards against an unbounded operator-facing window.
func TestHistoryBoundsAreBounded(t *testing.T) {
	if MaxHistoryRows <= 0 || MaxHistoryRows > 10000 {
		t.Fatalf("unexpected row bound %d", MaxHistoryRows)
	}
	if MaxHistoryBytes <= 0 || MaxHistoryBytes > 4<<20 {
		t.Fatalf("unexpected byte bound %d", MaxHistoryBytes)
	}
	if MaxHistoryTaskBytes <= 0 || MaxHistoryTaskBytes > 64<<10 {
		t.Fatalf("unexpected task bound %d", MaxHistoryTaskBytes)
	}
}
