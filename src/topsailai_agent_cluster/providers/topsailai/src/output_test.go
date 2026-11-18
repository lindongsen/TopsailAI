package main

import (
	"context"
	"encoding/json"
	"testing"
)

// TestReadOutputEnvelopeClasses pins the runtime logs transport contract the
// manual harness procedure cites as its automated coverage for ERR-08.
//
// The twelve classes are the ones the deleted in-process adapter test covered.
// They are re-established here because the provider is now the only component
// that decodes the envelope, so a class that stops failing closed would let a
// malformed provider document reach the operator as an empty but successful
// snapshot.
func TestReadOutputEnvelopeClasses(t *testing.T) {
	tests := []struct {
		name      string
		body      string
		content   string
		truncated bool
		wantErr   bool
	}{
		{"content", `{"ok":true,"response":{"lines":["Hello","你好"],"truncated":false}}`, "Hello\n你好", false, false},
		{"empty", `{"ok":true,"response":{"lines":[]}}`, "", false, false},
		{"truncated", `{"ok":true,"response":{"lines":["tail"],"truncated":true}}`, "tail", true, false},
		{"scan", `{"ok":true,"response":{"lines":["tail"],"scan_limited":true}}`, "tail", true, false},
		{"flat", `{"lines":["lost"]}`, "", false, true},
		{"missing", `{"ok":true}`, "", false, true},
		{"missing lines", `{"ok":true,"response":{}}`, "", false, true},
		{"null lines", `{"ok":true,"response":{"lines":null}}`, "", false, true},
		{"failure", `{"ok":false,"error_code":"not_found","response":{"lines":[]}}`, "", false, true},
		{"error code", `{"ok":true,"error_code":"failed","response":{"lines":[]}}`, "", false, true},
		{"wrong shape", `{"ok":true,"response":{"lines":"text"}}`, "", false, true},
		{"malformed", `{`, "", false, true},
	}
	for _, test := range tests {
		t.Run(test.name, func(t *testing.T) {
			r := &scriptedRunner{t: t, answers: map[string][]runnerAnswer{
				"workspace\x00list\x00--json\x00--local":                         answer(`{"items":[{"session_id":"s-1","filename":"row","pid":77}]}`),
				"runtime\x00logs\x00-s\x00s-1\x00-p\x0077\x00-n\x0020\x00--json": answer(test.body),
			}}
			request := validRequest(functionReadOutput)
			request.Target = sessionTarget(t)
			request.Payload = json.RawMessage(`{"max_bytes":0,"max_lines":0}`)
			response := fixedProvider(r).dispatch(context.Background(), request)
			if test.wantErr {
				if response.OK || response.Error == nil {
					t.Fatalf("response=%+v", response)
				}
				return
			}
			if !response.OK || response.Output == nil {
				t.Fatalf("response=%+v", response)
			}
			if response.Output.Content != test.content || response.Output.Truncated != test.truncated {
				t.Fatalf("output=%+v", response.Output)
			}
		})
	}
}
