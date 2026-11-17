package tui

import (
	"context"
	"strings"
	"testing"
	"time"

	"topsailai_agent_cluster/internal/protocol"
)

// briefEnrichmentLoad is one online endpoint with one addressable session, so a
// render has exactly one row that could be measured.
func briefEnrichmentLoad() reportLoad {
	return reportLoad{
		endpoints: []protocol.Endpoint{{EndpointID: "endpoint-1", DisplayName: "host-1", ConnectionState: "online"}},
		reports: map[string]protocol.InventoryReport{"endpoint-1": {
			CollectionStatus: protocol.CollectionSucceeded,
			Sessions: []protocol.Session{{
				ClusterSessionID:  "res_1",
				ProviderSessionID: "provider-session-1",
				State:             "running",
			}},
		}},
		errors: map[string]error{},
	}
}

// briefEnrichmentAPI is a metricsReader that records every provider read, so a
// test can prove a render did not pay for a column it never printed.
func briefEnrichmentAPI() *metricsStubAPI {
	return &metricsStubAPI{
		counts: map[string]protocol.MessageCounts{"provider-session-1": {Inbound: 7, Outbound: 3}},
		fail:   map[string]error{},
		code:   map[string]string{},
	}
}

// TestBriefRenderDoesNotReadMessageCounts proves a brief table pays nothing for
// the messages column it does not print.
//
// The defect this guards was measured, not hypothetical: `list --brief` took
// 9-10 s against a fleet whose full table took the same, because the enrichment
// ran unconditionally and every measured count was then discarded by the brief
// column set. The assertion is on the provider read count rather than on the
// elapsed time, because a read count is deterministic and a duration is not.
func TestBriefRenderDoesNotReadMessageCounts(t *testing.T) {
	api := briefEnrichmentAPI()
	var out, diagnostics strings.Builder
	options := TableOptions{Location: time.UTC, Brief: true, EnrichRows: MetricsEnricher(context.Background(), api)}
	if err := renderListRows(&out, &diagnostics, briefEnrichmentLoad(), "", false, options); err != nil {
		t.Fatalf("renderListRows: %v", err)
	}
	if got := api.queried(); len(got) != 0 {
		t.Fatalf("brief render read message counts for %v, want no provider read", got)
	}
	if strings.Contains(out.String(), "MESSAGES") {
		t.Fatalf("brief render printed a MESSAGES header: %q", out.String())
	}
}

// TestFullRenderStillReadsMessageCounts is the paired case. Without it the guard
// could be "skip enrichment always" and the brief test would still pass, so this
// test is what makes the pair prove the condition rather than the removal.
func TestFullRenderStillReadsMessageCounts(t *testing.T) {
	api := briefEnrichmentAPI()
	var out, diagnostics strings.Builder
	options := TableOptions{Location: time.UTC, EnrichRows: MetricsEnricher(context.Background(), api)}
	if err := renderListRows(&out, &diagnostics, briefEnrichmentLoad(), "", false, options); err != nil {
		t.Fatalf("renderListRows: %v", err)
	}
	if got, want := strings.Join(api.queried(), ","), "endpoint-1/provider-session-1"; got != want {
		t.Fatalf("full render read %q, want %q", got, want)
	}
	if !strings.Contains(out.String(), "7/3") {
		t.Fatalf("full render did not print the measured counts: %q", out.String())
	}
}

// TestBriefRenderStillStagesRows proves the guard skips only the measurement and
// not the row staging. A brief render still has to publish its rows, because row
// selection and the next command resolve against them.
func TestBriefRenderStillStagesRows(t *testing.T) {
	api := briefEnrichmentAPI()
	var out, diagnostics strings.Builder
	var staged []SessionRow
	options := TableOptions{
		Location:   time.UTC,
		Brief:      true,
		EnrichRows: MetricsEnricher(context.Background(), api),
		OnRows:     func(rows []SessionRow) { staged = append(staged, rows...) },
	}
	if err := renderListRows(&out, &diagnostics, briefEnrichmentLoad(), "", false, options); err != nil {
		t.Fatalf("renderListRows: %v", err)
	}
	if len(staged) != 1 {
		t.Fatalf("brief render staged %d rows, want 1", len(staged))
	}
	if staged[0].ClusterSessionID != "res_1" {
		t.Fatalf("brief render staged %q, want res_1", staged[0].ClusterSessionID)
	}
	if staged[0].Messages != nil {
		t.Fatalf("brief render staged measured counts %+v, want unmeasured", staged[0].Messages)
	}
}

// TestLayoutPrintsColumnFollowsTheLayout pins the helper the guard is built on.
//
// The guard must ask the layout rather than the flag, because the flag is an
// input and the layout is the decision. This test states both directions so a
// future column-set change cannot silently invert the guard.
func TestLayoutPrintsColumnFollowsTheLayout(t *testing.T) {
	for _, tc := range []struct {
		name    string
		options TableOptions
		key     string
		want    bool
	}{
		{name: "full layout prints messages", options: TableOptions{}, key: columnMessages, want: true},
		{name: "brief layout drops messages", options: TableOptions{Brief: true}, key: columnMessages, want: false},
		{name: "brief layout keeps the row number", options: TableOptions{Brief: true}, key: columnNo, want: true},
		{name: "brief layout keeps the name", options: TableOptions{Brief: true}, key: columnName, want: true},
		{name: "brief layout keeps the endpoint", options: TableOptions{Brief: true}, key: columnEndpoint, want: true},
		{name: "hidden session id is absent", options: TableOptions{HideSessionID: true}, key: columnID, want: false},
	} {
		t.Run(tc.name, func(t *testing.T) {
			if got := layoutPrintsColumn(tc.options, tc.key); got != tc.want {
				t.Fatalf("layoutPrintsColumn(%q)=%v want=%v", tc.key, got, tc.want)
			}
		})
	}
}
