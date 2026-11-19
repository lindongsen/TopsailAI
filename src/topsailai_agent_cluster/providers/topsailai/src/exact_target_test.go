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

// TestDetailUsesTheExactProviderTargetForRuntime proves one exact row costs one
// provider call, and that the call's document is split across both seams.
//
// `runtime info` publishes the row's whole record and its runtime observation in
// one document, so asking `session info` first would spend a second call to
// recover fields the first document already carried. The `runtime` member is the
// runtime seam and every other member is the metadata seam.
func TestDetailUsesTheExactProviderTargetForRuntime(t *testing.T) {
	document := `{"session_id":"s-1","session_name":"demo","pid":77,` +
		`"metafile":{"pid":77,"status":"running"},` +
		`"runtime":{"state":"ok","pid":77,"data":{"ok":true}}}`
	runner := &scriptedRunner{t: t, answers: map[string][]runnerAnswer{
		"runtime\x00info\x00-s\x00s-1\x00-p\x0077": answer(document),
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
	if len(runner.calls) != 1 {
		t.Fatalf("calls=%v, want one runtime info call", runner.calls)
	}
	var result detailResult
	if err := json.Unmarshal(response.QueryResult, &result); err != nil {
		t.Fatal(err)
	}
	wantMetadata := `{"session_id":"s-1","session_name":"demo","pid":77,` +
		`"metafile":{"pid":77,"status":"running"}}`
	if result.ProviderMetadata != wantMetadata {
		t.Fatalf("provider_metadata=%q, want the document minus runtime", result.ProviderMetadata)
	}
	wantRuntime := `{"state":"ok","pid":77,"data":{"ok":true}}`
	if result.ProviderRuntime != wantRuntime {
		t.Fatalf("provider_runtime=%q, want the runtime member verbatim", result.ProviderRuntime)
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
