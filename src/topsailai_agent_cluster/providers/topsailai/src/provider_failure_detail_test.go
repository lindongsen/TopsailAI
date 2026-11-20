package main

import (
	"context"
	"encoding/json"
	"errors"
	"strings"
	"testing"
)

// TestModelCatalogReportsTheProviderReasonOnRejection proves a rejected control call
// reports the provider's own reason instead of an empty stderr.
//
// The provider states a control-call failure inside its JSON document and leaves
// stderr empty, so formatting only stderr produced `exit status 6: ` with no cause.
// The operator then read a 502 that named neither the call nor the reason, and the
// only way to learn the cause was to reproduce the provider argv by hand. This is the
// exact shape observed on the live cluster: a session whose agent process predates the
// provider's `kwargs` support rejects the named `json` parameter.
func TestModelCatalogReportsTheProviderReasonOnRejection(t *testing.T) {
	const reason = "instruction failed: select_model() got an unexpected keyword argument 'json'"
	runner := &scriptedRunner{t: t, answers: map[string][]runnerAnswer{
		"runtime\x00control\x00call_instruction\x00-s\x00s-1\x00-p\x0077\x00-a\x00{\"instruction\":\"agent.models\",\"kwargs\":{\"json\":\"1\"}}\x00--json": {{
			stdout: `{"ok":false,"exit_code":6,"error_code":"control_rejected","message":"Runtime operation failed","response":{"status":"error","error":"` + reason + `"}}`,
			stderr: "",
			err:    errors.New("exit status 6"),
		}},
	}}
	slot, err := encodeProviderTarget(providerSessionTarget{SessionID: "s-1", PID: 77, ProviderRowKey: "row"})
	if err != nil {
		t.Fatal(err)
	}
	target := sessionTarget(t)
	target.ProviderTarget = slot
	_, err = fixedProvider(runner).models(context.Background(), target, json.RawMessage(`{}`))
	if err == nil {
		t.Fatal("models succeeded, want a provider failure")
	}
	if !strings.Contains(err.Error(), reason) {
		t.Fatalf("error = %q, want it to contain the provider reason %q", err.Error(), reason)
	}
	// The classification must not change: this is still a provider failure, not a
	// not-found or an invalid request, so the Cluster keeps answering 502.
	if code := errorCode(err); code != "provider_error" {
		t.Fatalf("code = %q, want provider_error", code)
	}
}

// TestProviderFailureDetailPrefersTheDocumentAndFallsBackToStderr proves the reason
// source order, so a document that carries no reason cannot silence stderr.
func TestProviderFailureDetailPrefersTheDocumentAndFallsBackToStderr(t *testing.T) {
	cases := []struct {
		name   string
		stdout string
		stderr string
		want   string
	}{
		{
			name:   "control envelope reason wins over stderr",
			stdout: `{"ok":false,"response":{"status":"error","error":"instruction failed: boom"}}`,
			stderr: "noise",
			want:   "instruction failed: boom",
		},
		{
			name:   "business read code and message",
			stdout: `{"error_code":"session_not_found","message":"Session not found: s-1"}`,
			stderr: "noise",
			want:   "session_not_found: Session not found: s-1",
		},
		{
			name:   "document without a reason falls back to stderr",
			stdout: `{"ok":false}`,
			stderr: "broken",
			want:   "broken",
		},
		{
			name:   "empty document falls back to stderr",
			stdout: "",
			stderr: "exec: not found",
			want:   "exec: not found",
		},
		{
			name:   "non-JSON document falls back to stderr",
			stdout: "plain text",
			stderr: "boom",
			want:   "boom",
		},
	}
	for _, testCase := range cases {
		t.Run(testCase.name, func(t *testing.T) {
			got := providerFailureDetail([]byte(testCase.stdout), []byte(testCase.stderr))
			if got != testCase.want {
				t.Fatalf("detail = %q, want %q", got, testCase.want)
			}
		})
	}
}
