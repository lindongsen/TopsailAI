package topsailai

import (
	"context"
	"reflect"
	"testing"

	"topsailai_agent_cluster/internal/adapter"
	"topsailai_agent_cluster/internal/protocol"
)

// TestReadOutputEnvelope checks the real runtime logs transport contract, not a flat mock.
func TestReadOutputEnvelope(t *testing.T) {
	for _, c := range []struct {
		name, body           string
		lines                []string
		truncated, scan, bad bool
	}{
		{"content", `{"ok":true,"response":{"lines":["Hello","你好"],"truncated":false}}`, []string{"Hello", "你好"}, false, false, false},
		{"empty", `{"ok":true,"response":{"lines":[]}}`, []string{}, false, false, false},
		{"truncated", `{"ok":true,"response":{"lines":["tail"],"truncated":true}}`, []string{"tail"}, true, false, false},
		{"scan", `{"ok":true,"response":{"lines":["tail"],"scan_limited":true}}`, []string{"tail"}, true, true, false},
		{"flat", `{"lines":["lost"]}`, nil, false, false, true},
		{"missing", `{"ok":true}`, nil, false, false, true},
		{"missing lines", `{"ok":true,"response":{}}`, nil, false, false, true},
		{"null lines", `{"ok":true,"response":{"lines":null}}`, nil, false, false, true},
		{"failure", `{"ok":false,"error_code":"not_found","response":{"lines":[]}}`, nil, false, false, true},
		{"error code", `{"ok":true,"error_code":"failed","response":{"lines":[]}}`, nil, false, false, true},
		{"wrong shape", `{"ok":true,"response":{"lines":"text"}}`, nil, false, false, true},
		{"malformed", `{`, nil, false, false, true},
	} {
		t.Run(c.name, func(t *testing.T) {
			runner := &fakeRunner{out: []byte(`{"items":[{"session_id":"s","process_generation":"g"}]}`)}
			a := newTestAdapter(t, runner)
			inventory, err := a.Discover(context.Background(), adapter.DiscoverRequest{})
			if err != nil {
				t.Fatal(err)
			}
			runner.out = []byte(c.body)
			got, err := a.ReadOutput(context.Background(), adapter.OutputRequest{Target: protocol.CommandTarget{ResourceID: inventory.Sessions[0].ClusterSessionID}})
			if (err != nil) != c.bad {
				t.Fatalf("result=%+v err=%v", got, err)
			}
			if !c.bad && (!reflect.DeepEqual(got.Lines, c.lines) || got.Truncated != c.truncated || got.ScanLimited != c.scan || got.ObservedAtMS == 0) {
				t.Fatalf("unexpected result: %+v", got)
			}
		})
	}
}
