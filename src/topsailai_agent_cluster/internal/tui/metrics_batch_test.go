package tui

import (
	"context"
	"errors"
	"strings"
	"sync"
	"testing"

	"topsailai_agent_cluster/internal/protocol"
)

// batchCall records one set read, so a test can prove how many provider reads a
// render cost and which sessions each one asked about.
type batchCall struct {
	endpointID string
	sessionIDs []string
}

// metricsBatchStubAPI is a client that can read a set of message counts in one
// call. It embeds the per-row stub so the fallback path is observable on the same
// object: a test can then assert that a set read happened and that no per-row read
// did, which is the property the batch path exists for.
type metricsBatchStubAPI struct {
	*metricsStubAPI

	batchMutex sync.Mutex
	batchCalls []batchCall
	// answer holds the counts the set read reports. A session absent from this map
	// is omitted from the result, which is how a provider says "asked but not
	// measurable".
	answer map[string]protocol.MessageCounts
	// memberCode holds a per-member error code, which must be dropped rather than
	// recorded as a measurement.
	memberCode map[string]string
	// fail makes the whole set read fail, which must degrade to per-row reads.
	fail error
	// batchCode makes the whole set read report a top-level error code.
	batchCode string
}

// newMetricsBatchStub returns a stub that answers nothing until a test says so.
func newMetricsBatchStub() *metricsBatchStubAPI {
	return &metricsBatchStubAPI{
		metricsStubAPI: newMetricsStub(0, 0),
		answer:         map[string]protocol.MessageCounts{},
		memberCode:     map[string]string{},
	}
}

// GetMetricsBatch records the set read and returns the configured outcome.
func (s *metricsBatchStubAPI) GetMetricsBatch(_ context.Context, endpointID string, sessionIDs []string) (protocol.SessionMetricsBatch, error) {
	s.batchMutex.Lock()
	s.batchCalls = append(s.batchCalls, batchCall{endpointID: endpointID, sessionIDs: append([]string(nil), sessionIDs...)})
	s.batchMutex.Unlock()
	if s.fail != nil {
		return protocol.SessionMetricsBatch{}, s.fail
	}
	if s.batchCode != "" {
		return protocol.SessionMetricsBatch{ErrorCode: s.batchCode}, nil
	}
	results := make([]protocol.SessionMetrics, 0, len(sessionIDs))
	for _, sessionID := range sessionIDs {
		if code, ok := s.memberCode[sessionID]; ok {
			results = append(results, protocol.SessionMetrics{ProviderSessionID: sessionID, ErrorCode: code})
			continue
		}
		counts, ok := s.answer[sessionID]
		if !ok {
			continue
		}
		results = append(results, protocol.SessionMetrics{ProviderSessionID: sessionID, Messages: counts})
	}
	return protocol.SessionMetricsBatch{Results: results}, nil
}

// batches returns the recorded set reads in a stable order.
func (s *metricsBatchStubAPI) batches() []batchCall {
	s.batchMutex.Lock()
	defer s.batchMutex.Unlock()
	return append([]batchCall(nil), s.batchCalls...)
}

// batchOnlyAPI is a client that can read a set but not a single row. It exists so
// the "adapter has the set capability only" case is proven rather than assumed,
// and it deliberately does not embed the per-row stub, because that embedding
// would promote GetMetrics and hide the case.
type batchOnlyAPI struct {
	CommandAPI

	mutex  sync.Mutex
	calls  []batchCall
	answer map[string]protocol.MessageCounts
}

// GetMetricsBatch records the set read and answers from the configured map.
func (s *batchOnlyAPI) GetMetricsBatch(_ context.Context, endpointID string, sessionIDs []string) (protocol.SessionMetricsBatch, error) {
	s.mutex.Lock()
	s.calls = append(s.calls, batchCall{endpointID: endpointID, sessionIDs: append([]string(nil), sessionIDs...)})
	s.mutex.Unlock()
	results := make([]protocol.SessionMetrics, 0, len(sessionIDs))
	for _, sessionID := range sessionIDs {
		counts, ok := s.answer[sessionID]
		if !ok {
			continue
		}
		results = append(results, protocol.SessionMetrics{ProviderSessionID: sessionID, Messages: counts})
	}
	return protocol.SessionMetricsBatch{Results: results}, nil
}

// batchMetricsFixture builds a two-Endpoint report with two sessions each, so a
// render spans Endpoint groups and the grouping is actually exercised.
func batchMetricsFixture() reportLoad {
	return reportLoad{
		endpoints: []protocol.Endpoint{
			{EndpointID: "endpoint-1", DisplayName: "host-1", ConnectionState: "online"},
			{EndpointID: "endpoint-2", DisplayName: "host-2", ConnectionState: "online"},
		},
		reports: map[string]protocol.InventoryReport{
			"endpoint-1": {
				CollectionStatus: protocol.CollectionSucceeded,
				Sessions: []protocol.Session{
					{ClusterSessionID: "res_1", ProviderSessionID: "provider-session-1", ProviderDisplayName: "one", State: "running"},
					{ClusterSessionID: "res_2", ProviderSessionID: "provider-session-2", ProviderDisplayName: "two", State: "running"},
				},
			},
			"endpoint-2": {
				CollectionStatus: protocol.CollectionSucceeded,
				Sessions: []protocol.Session{
					{ClusterSessionID: "res_3", ProviderSessionID: "provider-session-3", ProviderDisplayName: "three", State: "running"},
					{ClusterSessionID: "res_4", ProviderSessionID: "provider-session-4", ProviderDisplayName: "four", State: "running"},
				},
			},
		},
		errors: map[string]error{},
	}
}

// batchTargets returns the four targets the fixture renders, in table order.
func batchTargets() []metricsTarget {
	return []metricsTarget{
		{index: 0, endpointID: "endpoint-1", sessionID: "provider-session-1"},
		{index: 1, endpointID: "endpoint-1", sessionID: "provider-session-2"},
		{index: 2, endpointID: "endpoint-2", sessionID: "provider-session-3"},
		{index: 3, endpointID: "endpoint-2", sessionID: "provider-session-4"},
	}
}

// TestReadMetricsUsesOneBatchCallPerEndpoint proves the cost model the whole change
// exists for: a table costs one provider read per Endpoint, not one per row.
//
// Four rows across two Endpoints must cost exactly two set reads and zero per-row
// reads. A per-row implementation would cost four, which is the latency this
// replaces.
func TestReadMetricsUsesOneBatchCallPerEndpoint(t *testing.T) {
	api := newMetricsBatchStub()
	for _, sessionID := range []string{"provider-session-1", "provider-session-2", "provider-session-3", "provider-session-4"} {
		api.answer[sessionID] = protocol.MessageCounts{Inbound: 7, Outbound: 3}
	}

	resolved := readMetrics(context.Background(), api, batchTargets())

	if len(resolved) != 4 {
		t.Fatalf("resolved %d rows, want 4", len(resolved))
	}
	if got := len(api.batches()); got != 2 {
		t.Fatalf("four rows across two Endpoints cost %d set reads, want 2", got)
	}
	if got := len(api.queried()); got != 0 {
		t.Fatalf("the set read answered every row but %d per-row reads still ran: %v", got, api.queried())
	}
}

// TestReadMetricsPreservesRowIndexMapping proves each answer lands on the row it
// was asked about. A set read returns members in provider order, so a mapping that
// trusted that order would print one session's counts on another session's row.
func TestReadMetricsPreservesRowIndexMapping(t *testing.T) {
	api := newMetricsBatchStub()
	api.answer["provider-session-1"] = protocol.MessageCounts{Inbound: 1, Outbound: 11}
	api.answer["provider-session-2"] = protocol.MessageCounts{Inbound: 2, Outbound: 22}
	api.answer["provider-session-3"] = protocol.MessageCounts{Inbound: 3, Outbound: 33}
	api.answer["provider-session-4"] = protocol.MessageCounts{Inbound: 4, Outbound: 44}

	resolved := readMetrics(context.Background(), api, batchTargets())

	want := map[int]protocol.MessageCounts{
		0: {Inbound: 1, Outbound: 11},
		1: {Inbound: 2, Outbound: 22},
		2: {Inbound: 3, Outbound: 33},
		3: {Inbound: 4, Outbound: 44},
	}
	for index, counts := range want {
		if resolved[index] != counts {
			t.Fatalf("row %d got %+v, want %+v", index, resolved[index], counts)
		}
	}
}

// TestReadMetricsFallsBackForUnansweredMembers proves a member the set read did not
// answer is still measured, and that only that member pays a per-row read.
//
// A provider omits a session it could not measure. Leaving the row blank would
// hide a session that a per-row read can still measure, so the fallback must be
// narrow: the answered rows must not be read again.
func TestReadMetricsFallsBackForUnansweredMembers(t *testing.T) {
	api := newMetricsBatchStub()
	api.answer["provider-session-1"] = protocol.MessageCounts{Inbound: 7, Outbound: 3}
	api.answer["provider-session-3"] = protocol.MessageCounts{Inbound: 7, Outbound: 3}
	api.answer["provider-session-4"] = protocol.MessageCounts{Inbound: 7, Outbound: 3}
	// provider-session-2 is deliberately absent from the set answer.
	api.counts["provider-session-2"] = protocol.MessageCounts{Inbound: 9, Outbound: 4}

	resolved := readMetrics(context.Background(), api, batchTargets())

	if got := len(api.batches()); got != 2 {
		t.Fatalf("cost %d set reads, want 2", got)
	}
	queried := api.queried()
	if len(queried) != 1 || queried[0] != "endpoint-1/provider-session-2" {
		t.Fatalf("per-row fallback read %v, want only endpoint-1/provider-session-2", queried)
	}
	if resolved[1] != (protocol.MessageCounts{Inbound: 9, Outbound: 4}) {
		t.Fatalf("the unanswered row got %+v, want the per-row measurement", resolved[1])
	}
	if resolved[0] != (protocol.MessageCounts{Inbound: 7, Outbound: 3}) {
		t.Fatalf("the answered row got %+v, want the set measurement", resolved[0])
	}
}

// TestReadMetricsFallsBackWhenBatchFails proves a whole-request failure degrades to
// per-row reads instead of blanking the column.
//
// An adapter without the capability, a refused caller and an unreachable Endpoint
// all look like this. None of them is a reason to stop showing counts that a
// per-row read can still obtain.
func TestReadMetricsFallsBackWhenBatchFails(t *testing.T) {
	api := newMetricsBatchStub()
	api.fail = errors.New("endpoint offline")
	for _, sessionID := range []string{"provider-session-1", "provider-session-2", "provider-session-3", "provider-session-4"} {
		api.counts[sessionID] = protocol.MessageCounts{Inbound: 5, Outbound: 6}
	}

	resolved := readMetrics(context.Background(), api, batchTargets())

	if len(resolved) != 4 {
		t.Fatalf("a failed set read left %d of 4 rows measured, want all 4", len(resolved))
	}
	if got := len(api.queried()); got != 4 {
		t.Fatalf("the fallback read %d rows, want 4", got)
	}
}

// TestReadMetricsFallsBackWhenBatchReportsAnErrorCode proves a top-level error code
// is treated as "not answered" rather than as an empty measurement. The two are
// different: an error code proves the request failed, so the rows must be retried
// the old way.
func TestReadMetricsFallsBackWhenBatchReportsAnErrorCode(t *testing.T) {
	api := newMetricsBatchStub()
	api.batchCode = protocol.MetricsUnsupported
	for _, sessionID := range []string{"provider-session-1", "provider-session-2", "provider-session-3", "provider-session-4"} {
		api.counts[sessionID] = protocol.MessageCounts{Inbound: 5, Outbound: 6}
	}

	resolved := readMetrics(context.Background(), api, batchTargets())

	if len(resolved) != 4 {
		t.Fatalf("an unsupported set read left %d of 4 rows measured, want all 4", len(resolved))
	}
	if got := len(api.queried()); got != 4 {
		t.Fatalf("the fallback read %d rows, want 4", got)
	}
}

// TestReadMetricsDropsMembersCarryingAnErrorCode proves a member error code is not
// recorded as a measurement. A member that carries a code was asked about and could
// not be measured, so the row must stay unmeasured rather than print a zero.
func TestReadMetricsDropsMembersCarryingAnErrorCode(t *testing.T) {
	api := newMetricsBatchStub()
	api.answer["provider-session-1"] = protocol.MessageCounts{Inbound: 7, Outbound: 3}
	api.answer["provider-session-3"] = protocol.MessageCounts{Inbound: 7, Outbound: 3}
	api.answer["provider-session-4"] = protocol.MessageCounts{Inbound: 7, Outbound: 3}
	api.memberCode["provider-session-2"] = protocol.MetricsUnavailable
	// The per-row fallback also cannot measure it, so the row must stay absent.
	api.code["provider-session-2"] = protocol.MetricsUnavailable

	resolved := readMetrics(context.Background(), api, batchTargets())

	if _, ok := resolved[1]; ok {
		t.Fatalf("a member error code was recorded as a measurement: %+v", resolved[1])
	}
	if len(resolved) != 3 {
		t.Fatalf("resolved %d rows, want 3 measured", len(resolved))
	}
}

// TestReadMetricsDeduplicatesRepeatedSessions proves one session named twice in a
// group is asked about once. A provider session identifier can appear on several
// rows, and sending it twice would make the provider do the same work twice.
func TestReadMetricsDeduplicatesRepeatedSessions(t *testing.T) {
	api := newMetricsBatchStub()
	api.answer["provider-session-1"] = protocol.MessageCounts{Inbound: 7, Outbound: 3}

	targets := []metricsTarget{
		{index: 0, endpointID: "endpoint-1", sessionID: "provider-session-1"},
		{index: 1, endpointID: "endpoint-1", sessionID: "provider-session-1"},
	}
	resolved := readMetrics(context.Background(), api, targets)

	batches := api.batches()
	if len(batches) != 1 {
		t.Fatalf("cost %d set reads, want 1", len(batches))
	}
	if len(batches[0].sessionIDs) != 1 {
		t.Fatalf("the set read asked about %v, want one deduplicated identifier", batches[0].sessionIDs)
	}
	if len(resolved) != 2 {
		t.Fatalf("resolved %d rows, want both rows measured from one answer", len(resolved))
	}
}

// TestReadMetricsWorksForBatchOnlyClient proves a client that can read a set but not
// a single row still fills the column for what the set answered, and does not panic
// on what it did not.
func TestReadMetricsWorksForBatchOnlyClient(t *testing.T) {
	api := &batchOnlyAPI{answer: map[string]protocol.MessageCounts{
		"provider-session-1": {Inbound: 7, Outbound: 3},
		"provider-session-3": {Inbound: 8, Outbound: 4},
	}}

	resolved := readMetrics(context.Background(), api, batchTargets())

	if len(resolved) != 2 {
		t.Fatalf("resolved %d rows, want the 2 the set answered", len(resolved))
	}
	if resolved[0] != (protocol.MessageCounts{Inbound: 7, Outbound: 3}) {
		t.Fatalf("row 0 got %+v", resolved[0])
	}
	if resolved[2] != (protocol.MessageCounts{Inbound: 8, Outbound: 4}) {
		t.Fatalf("row 2 got %+v", resolved[2])
	}
}

// TestListRenderPrintsBatchCounts drives the real list render, so the wiring is
// proven rather than the helper.
//
// A helper test alone would pass even if the renderer never called readMetrics, and
// the rendered bytes are the only evidence that the counts reached the table. The
// test also asserts the cost, because a render that printed the counts by reading
// every row would satisfy the output assertion while defeating the change.
func TestListRenderPrintsBatchCounts(t *testing.T) {
	api := newMetricsBatchStub()
	for _, sessionID := range []string{"provider-session-1", "provider-session-2", "provider-session-3", "provider-session-4"} {
		api.answer[sessionID] = protocol.MessageCounts{Inbound: 7, Outbound: 3}
	}

	var out, diagnostics strings.Builder
	options := TableOptions{EnrichRows: MetricsEnricher(context.Background(), api)}
	if err := renderListRows(&out, &diagnostics, batchMetricsFixture(), "", false, options); err != nil {
		t.Fatalf("renderListRows: %v", err)
	}

	rendered := out.String()
	if got := strings.Count(rendered, "7/3"); got != 4 {
		t.Fatalf("the table printed %d of 4 counts: %q", got, rendered)
	}
	if got := len(api.batches()); got != 2 {
		t.Fatalf("the render cost %d set reads, want one per Endpoint (2)", got)
	}
	if got := len(api.queried()); got != 0 {
		t.Fatalf("the render also ran %d per-row reads: %v", got, api.queried())
	}
}

// TestListRenderLeavesUnmeasuredRowsBlank proves a row the provider could not
// measure renders as unmeasured rather than as zero. A zero is a measurement, and
// printing one nobody made is worse than printing nothing.
func TestListRenderLeavesUnmeasuredRowsBlank(t *testing.T) {
	api := newMetricsBatchStub()
	api.answer["provider-session-1"] = protocol.MessageCounts{Inbound: 7, Outbound: 3}
	api.answer["provider-session-3"] = protocol.MessageCounts{Inbound: 7, Outbound: 3}
	api.answer["provider-session-4"] = protocol.MessageCounts{Inbound: 7, Outbound: 3}
	api.code["provider-session-2"] = protocol.MetricsUnavailable

	var out, diagnostics strings.Builder
	options := TableOptions{EnrichRows: MetricsEnricher(context.Background(), api)}
	if err := renderListRows(&out, &diagnostics, batchMetricsFixture(), "", false, options); err != nil {
		t.Fatalf("renderListRows: %v", err)
	}

	rendered := out.String()
	if got := strings.Count(rendered, "7/3"); got != 3 {
		t.Fatalf("the table printed %d of 3 measurable counts: %q", got, rendered)
	}
	if strings.Contains(rendered, "0/0") {
		t.Fatalf("an unmeasured row was printed as a zero count: %q", rendered)
	}
}
