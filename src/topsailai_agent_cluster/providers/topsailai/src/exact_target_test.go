package main

import (
	"context"
	"encoding/json"
	"testing"
)

func exactSessionTarget(t *testing.T, pid int64) *target {
	t.Helper()
	value := sessionTarget(t)
	slot, err := encodeProviderTarget(providerSessionTarget{SessionID: "s-1", ProviderRowKey: "row", PID: pid})
	if err != nil {
		t.Fatal(err)
	}
	value.ProviderTarget = slot
	return value
}

// TestReadOutputUsesTheExactProviderTarget proves snapshot reads do not scan to
// reconstruct identity when the Cluster returns the Provider's own slot.
func TestReadOutputUsesTheExactProviderTarget(t *testing.T) {
	runner := &scriptedRunner{t: t, answers: map[string][]runnerAnswer{
		"runtime\x00logs\x00-s\x00s-1\x00-p\x0077\x00-n\x0020\x00--json": answer(`{"ok":true,"response":{"lines":["line"],"truncated":false,"scan_limited":false}}`),
	}}
	request := validRequest(functionReadOutput)
	request.Target = exactSessionTarget(t, 77)
	request.Payload = json.RawMessage(`{"max_bytes":64,"max_lines":20}`)
	response := fixedProvider(runner).dispatch(context.Background(), request)
	if !response.OK || response.Output == nil || response.Output.Content != "line" {
		t.Fatalf("response=%+v", response)
	}
	if len(runner.calls) != 1 {
		t.Fatalf("calls=%v", runner.calls)
	}
}

// TestDetailUsesTheExactProviderTargetForRuntime proves metadata remains
// session-scoped while runtime addresses the exact process row.
func TestDetailUsesTheExactProviderTargetForRuntime(t *testing.T) {
	runner := &scriptedRunner{t: t, answers: map[string][]runnerAnswer{
		"session\x00info\x00s-1\x00--json":         answer(`{"session_id":"s-1"}`),
		"runtime\x00info\x00-s\x00s-1\x00-p\x0077": answer(`{"state":"ok","pid":77}`),
	}}
	target := &target{ResourceKind: resourceSession, ProviderResourceKey: "s-1"}
	slot, err := encodeProviderTarget(providerSessionTarget{SessionID: "s-1", ProviderRowKey: "row", PID: 77})
	if err != nil {
		t.Fatal(err)
	}
	target.ProviderTarget = slot
	request := queryRequest(querySessionDetail, target, `{}`)
	response := fixedProvider(runner).dispatch(context.Background(), request)
	if !response.OK || len(response.QueryResult) == 0 {
		t.Fatalf("response=%+v", response)
	}
	if len(runner.calls) != 2 {
		t.Fatalf("calls=%v", runner.calls)
	}
}

// TestReadOutputRejectsAProviderTargetForAnotherRow proves client-carried exact
// evidence cannot retarget a Cluster resource mapping.
func TestReadOutputRejectsAProviderTargetForAnotherRow(t *testing.T) {
	runner := &scriptedRunner{t: t, answers: map[string][]runnerAnswer{}}
	request := validRequest(functionReadOutput)
	request.Target = sessionTarget(t)
	slot, err := encodeProviderTarget(providerSessionTarget{SessionID: "other", ProviderRowKey: "other-row", PID: 88})
	if err != nil {
		t.Fatal(err)
	}
	request.Target.ProviderTarget = slot
	request.Payload = json.RawMessage(`{"max_bytes":64,"max_lines":20}`)
	response := fixedProvider(runner).dispatch(context.Background(), request)
	if response.OK || response.Error == nil {
		t.Fatalf("response=%+v, want rejection", response)
	}
	if len(runner.calls) != 0 {
		t.Fatalf("calls=%v, want none", runner.calls)
	}
}

// TestDetailRejectsAProviderTargetForAnotherSession proves an exact runtime slot
// cannot replace the session-scoped metadata target.
func TestDetailRejectsAProviderTargetForAnotherSession(t *testing.T) {
	runner := &scriptedRunner{t: t, answers: map[string][]runnerAnswer{}}
	target := &target{ResourceKind: resourceSession, ProviderResourceKey: "s-1"}
	slot, err := encodeProviderTarget(providerSessionTarget{SessionID: "other", ProviderRowKey: "row", PID: 77})
	if err != nil {
		t.Fatal(err)
	}
	target.ProviderTarget = slot
	response := fixedProvider(runner).dispatch(context.Background(), queryRequest(querySessionDetail, target, `{}`))
	if response.OK || response.Error == nil {
		t.Fatalf("response=%+v, want rejection", response)
	}
	if len(runner.calls) != 0 {
		t.Fatalf("calls=%v, want none", runner.calls)
	}
}
