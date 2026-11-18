package main

import (
	"context"
	"encoding/json"
	"testing"
)

// TestDiscoverReportsMessageCountsFromTheSameDocument proves the discovery ->
// report link.
//
// Discovery collects the runtime record in the same document it already reads,
// so the counts must reach the observation without a second provider call. The
// existing discovery tests only assert the CLI arguments, which is why replacing
// the attach with `_ = counts` left this package green: nothing asserted that a
// measured row actually carried its counts.
func TestDiscoverReportsMessageCountsFromTheSameDocument(t *testing.T) {
	doc := `{"items":[{"session_id":"s-1","filename":"row","pid":42,"process_generation":7,"state":"input",
		"runtime":{"state":"ok","pid":42,"data":{"ok":true,"user2agent":{"messages":4},"agent2llm":{"messages":72}}}}],"total":1}`
	r := &scriptedRunner{t: t, answers: map[string][]runnerAnswer{"workspace\x00list\x00--json\x00--local\x00--include-runtime": answer(doc)}}
	response := fixedProvider(r).dispatch(context.Background(), validRequest(functionDiscover))
	if !response.OK || response.Discovery == nil || len(response.Discovery.Observations) != 1 {
		t.Fatalf("response=%+v", response)
	}
	var attrs sessionAttributes
	if err := json.Unmarshal(response.Discovery.Observations[0].Attributes, &attrs); err != nil {
		t.Fatalf("decode attributes: %v", err)
	}
	if attrs.Messages == nil {
		t.Fatal("measured row reported no message counts")
	}
	// The human listed user2agent first, so inbound is the operator's side and
	// outbound is the model's side. Asserting the pair catches a swap that a
	// single-field check would accept.
	if attrs.Messages.Inbound != 4 || attrs.Messages.Outbound != 72 {
		t.Fatalf("counts=%+v want={4 72}", *attrs.Messages)
	}
	// One provider call proves the counts came from the discovery document
	// rather than from a second read.
	if len(r.calls) != 1 {
		t.Fatalf("provider calls=%d want=1", len(r.calls))
	}
}

// TestDiscoverOmitsMessageCountsForAnUnmeasuredRow proves the other half of the
// contract: a row the provider could not measure keeps an absent value.
//
// Substituting a zero would state a measurement nobody made, and the table would
// render "0/0" for a session whose control channel refused. The three cases are
// separate because they are separate failures, and each must stay absent.
func TestDiscoverOmitsMessageCountsForAnUnmeasuredRow(t *testing.T) {
	cases := []struct {
		name string
		row  string
	}{
		{
			name: "runtime refused the read",
			row:  `"runtime":{"state":"rejected","error_code":"control_channel_closed"}`,
		},
		{
			name: "runtime state ok but no data",
			row:  `"runtime":{"state":"ok","pid":42}`,
		},
		{
			name: "no runtime record at all",
			row:  `"runtime":null`,
		},
		{
			name: "runtime reported no active agent",
			row:  `"runtime":{"state":"ok","pid":42,"data":{"ok":false}}`,
		},
	}
	for _, testCase := range cases {
		t.Run(testCase.name, func(t *testing.T) {
			doc := `{"items":[{"session_id":"s-1","filename":"row","pid":42,"process_generation":7,"state":"input",` + testCase.row + `}],"total":1}`
			r := &scriptedRunner{t: t, answers: map[string][]runnerAnswer{"workspace\x00list\x00--json\x00--local\x00--include-runtime": answer(doc)}}
			response := fixedProvider(r).dispatch(context.Background(), validRequest(functionDiscover))
			if !response.OK || response.Discovery == nil || len(response.Discovery.Observations) != 1 {
				t.Fatalf("response=%+v", response)
			}
			var attrs sessionAttributes
			if err := json.Unmarshal(response.Discovery.Observations[0].Attributes, &attrs); err != nil {
				t.Fatalf("decode attributes: %v", err)
			}
			if attrs.Messages != nil {
				t.Fatalf("unmeasured row gained counts: %+v", *attrs.Messages)
			}
			// The row must still be reported. Dropping the whole observation
			// would hide the session from the Cluster instead of showing "-".
			if response.Discovery.Observations[0].ProviderResourceKey == "" {
				t.Fatal("unmeasured row lost its observation")
			}
		})
	}
}

// TestDiscoverKeepsAMeasuredZeroDistinctFromAnUnmeasuredRow proves the two
// states stay distinguishable end to end.
//
// A session that really has no messages must report a measured zero, because
// that renders as "0/0" while an unmeasured row renders as "-". Collapsing the
// two would make the table claim a measurement the provider never made, or hide
// one it did make.
func TestDiscoverKeepsAMeasuredZeroDistinctFromAnUnmeasuredRow(t *testing.T) {
	doc := `{"items":[{"session_id":"s-1","filename":"row","pid":42,"process_generation":7,"state":"input",
		"runtime":{"state":"ok","pid":42,"data":{"ok":true,"user2agent":{"messages":0},"agent2llm":{"messages":0}}}}],"total":1}`
	r := &scriptedRunner{t: t, answers: map[string][]runnerAnswer{"workspace\x00list\x00--json\x00--local\x00--include-runtime": answer(doc)}}
	response := fixedProvider(r).dispatch(context.Background(), validRequest(functionDiscover))
	if !response.OK || response.Discovery == nil || len(response.Discovery.Observations) != 1 {
		t.Fatalf("response=%+v", response)
	}
	var attrs sessionAttributes
	if err := json.Unmarshal(response.Discovery.Observations[0].Attributes, &attrs); err != nil {
		t.Fatalf("decode attributes: %v", err)
	}
	if attrs.Messages == nil {
		t.Fatal("measured zero was reported as unmeasured")
	}
	if attrs.Messages.Inbound != 0 || attrs.Messages.Outbound != 0 {
		t.Fatalf("counts=%+v want={0 0}", *attrs.Messages)
	}
}
