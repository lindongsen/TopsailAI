package topsailai

import (
	"context"
	"errors"
	"strings"
	"testing"
	"time"

	"topsailai_agent_cluster/internal/protocol"
)

// historyAdapter builds an adapter whose provider answers with one fixed document.
func historyAdapter(t *testing.T, runner *fakeRunner) *Adapter {
	t.Helper()
	result, err := newWithRunner(Config{AdapterID: "a1", Executable: "/provider", MaxOutput: 1 << 20, ResourceMapper: newFakeMapper(), PlatformProbe: func() (PlatformCapabilities, error) {
		return PlatformCapabilities{}, nil
	}}, runner)
	if err != nil {
		t.Fatalf("newWithRunner: %v", err)
	}
	return result
}

// TestHistoryInvokesTheProviderHistorySurface pins the exact argv array. The
// provider surface is `project list_sessions --json`; a shell string or a
// different subcommand would silently read a different dataset.
func TestHistoryInvokesTheProviderHistorySurface(t *testing.T) {
	runner := &fakeRunner{out: []byte(`[]`)}
	adapter := historyAdapter(t, runner)
	if _, err := adapter.History(context.Background(), protocol.HistoryQuery{}); err != nil {
		t.Fatalf("History: %v", err)
	}
	want := []string{"project", "list_sessions", "--json"}
	if len(runner.args) != len(want) {
		t.Fatalf("argv = %v, want %v", runner.args, want)
	}
	for i := range want {
		if runner.args[i] != want[i] {
			t.Fatalf("argv = %v, want %v", runner.args, want)
		}
	}
}

// TestHistoryNormalizesTheDocumentedFields proves the nine documented fields are
// mapped onto the standard row without inventing routing identity.
func TestHistoryNormalizesTheDocumentedFields(t *testing.T) {
	document := `[{"session_id":"wa-6cee12a5f2a0","session_name":"会话问题根因分析","project_workspace":"/TopsailAI/src/topsailai","modified_time_raw":"2026-11-07T10:22:36","create_time_raw":"2026-11-07T10:22:36","task":"分析根本原因","no":1,"modified_time":"11-07 10:22","status":"Idle"}]`
	adapter := historyAdapter(t, &fakeRunner{out: []byte(document)})
	result, err := adapter.History(context.Background(), protocol.HistoryQuery{})
	if err != nil {
		t.Fatalf("History: %v", err)
	}
	if len(result.Rows) != 1 {
		t.Fatalf("rows = %d, want 1", len(result.Rows))
	}
	row := result.Rows[0]
	if row.ProviderSessionID != "wa-6cee12a5f2a0" || row.DisplayName != "会话问题根因分析" || row.ProjectWorkspace != "/TopsailAI/src/topsailai" || row.Task != "分析根本原因" || row.ProviderStatus != "Idle" || row.ProviderNo != 1 {
		t.Fatalf("unexpected row: %+v", row)
	}
	if !row.Resumable || row.ResumeBlockedReason != "" {
		t.Fatalf("idle row must be resumable: %+v", row)
	}
	wantMS := time.Date(2026, 11, 7, 10, 22, 36, 0, time.Local).UnixMilli()
	if row.ModifiedAtMS != wantMS || row.CreatedAtMS != wantMS {
		t.Fatalf("timestamps = %d/%d, want %d", row.CreatedAtMS, row.ModifiedAtMS, wantMS)
	}
	if result.ObservedAtMS <= 0 {
		t.Fatalf("observation time must be set: %+v", result)
	}
}

// TestHistoryRunningRowIsNotResumable proves the adapter's first-line verdict.
func TestHistoryRunningRowIsNotResumable(t *testing.T) {
	document := `[{"session_id":"s1","status":"Running"}]`
	adapter := historyAdapter(t, &fakeRunner{out: []byte(document)})
	result, err := adapter.History(context.Background(), protocol.HistoryQuery{})
	if err != nil {
		t.Fatalf("History: %v", err)
	}
	if result.Rows[0].Resumable || result.Rows[0].ResumeBlockedReason != protocol.ResumeBlockedProviderRunning {
		t.Fatalf("running row must not be resumable: %+v", result.Rows[0])
	}
}

// TestHistoryUnknownStatusIsNotResumable proves an unrecognized status word is
// never presented as resumable. Guessing here would let an operator resume a
// session that may still be running.
func TestHistoryUnknownStatusIsNotResumable(t *testing.T) {
	for _, status := range []string{"", "?", "Paused", "idle"} {
		document := `[{"session_id":"s1","status":"` + status + `"}]`
		adapter := historyAdapter(t, &fakeRunner{out: []byte(document)})
		result, err := adapter.History(context.Background(), protocol.HistoryQuery{})
		if err != nil {
			t.Fatalf("History(%q): %v", status, err)
		}
		if result.Rows[0].Resumable {
			t.Fatalf("status %q must not be resumable", status)
		}
		if result.Rows[0].ResumeBlockedReason != protocol.ResumeBlockedRecordIncomplete {
			t.Fatalf("status %q reason = %q", status, result.Rows[0].ResumeBlockedReason)
		}
	}
}

// TestHistoryEmptyListIsASuccess keeps an empty provider answer distinct from a
// failed call, so an Endpoint with no history is not reported as broken.
func TestHistoryEmptyListIsASuccess(t *testing.T) {
	adapter := historyAdapter(t, &fakeRunner{out: []byte(`[]`)})
	result, err := adapter.History(context.Background(), protocol.HistoryQuery{})
	if err != nil {
		t.Fatalf("History: %v", err)
	}
	if len(result.Rows) != 0 || result.ErrorCode != "" {
		t.Fatalf("empty history must be a successful empty result: %+v", result)
	}
}

// TestHistoryMalformedDocumentFails proves a malformed document is an error, not
// an empty successful list.
func TestHistoryMalformedDocumentFails(t *testing.T) {
	adapter := historyAdapter(t, &fakeRunner{out: []byte(`{"not":"a list"}`)})
	if _, err := adapter.History(context.Background(), protocol.HistoryQuery{}); err == nil {
		t.Fatal("malformed document must fail")
	}
}

// TestHistoryProviderFailurePropagates proves a provider failure is not swallowed.
func TestHistoryProviderFailurePropagates(t *testing.T) {
	adapter := historyAdapter(t, &fakeRunner{out: []byte(`[]`), err: errors.New("provider failed")})
	if _, err := adapter.History(context.Background(), protocol.HistoryQuery{}); err == nil {
		t.Fatal("provider failure must propagate")
	}
}

// TestHistoryOversizedDocumentFails proves the byte bound is enforced.
func TestHistoryOversizedDocumentFails(t *testing.T) {
	big := `[{"session_id":"s1","task":"` + strings.Repeat("x", protocol.MaxHistoryBytes) + `"}]`
	adapter := historyAdapter(t, &fakeRunner{out: []byte(big)})
	result, err := adapter.History(context.Background(), protocol.HistoryQuery{})
	if err == nil {
		t.Fatal("oversized document must fail")
	}
	if result.ErrorCode != protocol.HistoryResponseTooLarge {
		t.Fatalf("error code = %q", result.ErrorCode)
	}
}

// TestHistoryLimitNarrowsOnly proves the caller bound narrows the view and never
// raises the provider's own cap.
func TestHistoryLimitNarrowsOnly(t *testing.T) {
	document := `[{"session_id":"s1","status":"Idle"},{"session_id":"s2","status":"Idle"},{"session_id":"s3","status":"Idle"}]`
	adapter := historyAdapter(t, &fakeRunner{out: []byte(document)})
	result, err := adapter.History(context.Background(), protocol.HistoryQuery{Limit: 2})
	if err != nil {
		t.Fatalf("History: %v", err)
	}
	if len(result.Rows) != 2 {
		t.Fatalf("rows = %d, want 2", len(result.Rows))
	}
	// A limit above the returned count must not invent rows.
	result, err = adapter.History(context.Background(), protocol.HistoryQuery{Limit: 99})
	if err != nil {
		t.Fatalf("History: %v", err)
	}
	if len(result.Rows) != 3 {
		t.Fatalf("rows = %d, want 3", len(result.Rows))
	}
}

// TestHistorySkipsRowsWithoutSessionID proves an unaddressable row is dropped
// rather than rendered as a selectable row with an empty identity.
func TestHistorySkipsRowsWithoutSessionID(t *testing.T) {
	document := `[{"session_id":"","status":"Idle"},{"session_id":"s2","status":"Idle"}]`
	adapter := historyAdapter(t, &fakeRunner{out: []byte(document)})
	result, err := adapter.History(context.Background(), protocol.HistoryQuery{})
	if err != nil {
		t.Fatalf("History: %v", err)
	}
	if len(result.Rows) != 1 || result.Rows[0].ProviderSessionID != "s2" {
		t.Fatalf("unexpected rows: %+v", result.Rows)
	}
}

// TestHistoryUnparsableTimeIsZero proves a missing time is never fabricated.
func TestHistoryUnparsableTimeIsZero(t *testing.T) {
	document := `[{"session_id":"s1","status":"Idle","modified_time_raw":"not-a-time","create_time_raw":""}]`
	adapter := historyAdapter(t, &fakeRunner{out: []byte(document)})
	result, err := adapter.History(context.Background(), protocol.HistoryQuery{})
	if err != nil {
		t.Fatalf("History: %v", err)
	}
	if result.Rows[0].ModifiedAtMS != 0 || result.Rows[0].CreatedAtMS != 0 {
		t.Fatalf("unparsable times must be zero: %+v", result.Rows[0])
	}
}

// TestHistoryTaskIsBounded proves one oversized task cannot exceed the bound.
func TestHistoryTaskIsBounded(t *testing.T) {
	document := `[{"session_id":"s1","status":"Idle","task":"` + strings.Repeat("a", protocol.MaxHistoryTaskBytes+100) + `"}]`
	adapter := historyAdapter(t, &fakeRunner{out: []byte(document)})
	result, err := adapter.History(context.Background(), protocol.HistoryQuery{})
	if err != nil {
		t.Fatalf("History: %v", err)
	}
	if len(result.Rows[0].Task) > protocol.MaxHistoryTaskBytes {
		t.Fatalf("task length = %d", len(result.Rows[0].Task))
	}
}
