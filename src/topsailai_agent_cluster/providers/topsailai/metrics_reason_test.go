package main

import (
	"context"
	"strings"
	"testing"
)

// TestSessionMetricsReportsTheProviderReason proves that a runtime record which
// refused the read reports the provider's own reason instead of a generic message.
//
// The provider publishes an envelope: State says whether the row's process answered,
// ErrorCode carries why it refused, and Data carries the answer. A row whose process
// refused has a State other than "ok", no Data, and a populated ErrorCode. Measured
// on this host for a real session:
//
//	{"state": "rejected", "error_code": "control_rejected", "pid": 367681, "data": null}
//
// Before this test the reader discarded ErrorCode and returned "provider did not
// report runtime message counts", which is true of every non-ok state and therefore
// names none of them. The operator saw a metrics column that stayed empty and a log
// line that said the provider reported nothing, while the provider had in fact said
// exactly why it refused. The reason existed and was thrown away.
func TestSessionMetricsReportsTheProviderReason(t *testing.T) {
	document := `{"items":[{"session_id":"s-1","filename":"s-1.42.session.stdout",` +
		`"is_task":false,"runtime":{"state":"rejected","error_code":"control_rejected","pid":42,` +
		`"data":null}}],"total":1}`
	key := "workspace\x00list\x00--json\x00--local\x00-s\x00s-1\x00--include-runtime"
	r := &scriptedRunner{t: t, answers: map[string][]runnerAnswer{key: answer(document)}}
	response := fixedProvider(r).dispatch(context.Background(), queryRequest(
		querySessionMetrics, &target{ResourceKind: resourceSession, ProviderResourceKey: "s-1"}, `{}`))

	if response.OK || response.Error == nil {
		t.Fatalf("response=%+v, want a provider failure", response)
	}
	if !strings.Contains(response.Error.Message, "control_rejected") {
		t.Fatalf("message=%q does not name the provider's reason, so the operator cannot tell why the read was refused",
			response.Error.Message)
	}
	if !strings.Contains(response.Error.Message, "rejected") {
		t.Fatalf("message=%q does not name the runtime state, so the operator cannot tell which condition occurred",
			response.Error.Message)
	}
}

// TestSessionMetricsReportsAMissingRuntimeRecord proves the case where the provider
// published no runtime record at all keeps its own distinct message.
//
// Without this, a fix that always interpolated a reason would report an empty reason
// for a row the provider never described, and the two conditions would collapse into
// one message again.
func TestSessionMetricsReportsAMissingRuntimeRecord(t *testing.T) {
	document := `{"items":[{"session_id":"s-1","filename":"s-1.42.session.stdout",` +
		`"is_task":false,"runtime":null}],"total":1}`
	key := "workspace\x00list\x00--json\x00--local\x00-s\x00s-1\x00--include-runtime"
	r := &scriptedRunner{t: t, answers: map[string][]runnerAnswer{key: answer(document)}}
	response := fixedProvider(r).dispatch(context.Background(), queryRequest(
		querySessionMetrics, &target{ResourceKind: resourceSession, ProviderResourceKey: "s-1"}, `{}`))

	if response.OK || response.Error == nil {
		t.Fatalf("response=%+v, want a provider failure", response)
	}
	if response.Error.Message != "provider did not report runtime message counts" {
		t.Fatalf("message=%q, want the absent-record message for a row with no runtime record",
			response.Error.Message)
	}
}
