package tui

import (
	"context"
	"io"
	"strings"
	"testing"
	"time"

	"topsailai_agent_cluster/internal/protocol"
)

// watchMetricsFixture builds one loaded report with a single addressable session,
// so a render can be driven through the real entry point.
func watchMetricsFixture() reportLoad {
	return reportLoad{
		endpoints: []protocol.Endpoint{{EndpointID: "endpoint-1", DisplayName: "host-1", ConnectionState: "online"}},
		reports: map[string]protocol.InventoryReport{"endpoint-1": {
			CollectionStatus: protocol.CollectionSucceeded,
			Sessions: []protocol.Session{{
				ClusterSessionID:    "res_1",
				ProviderSessionID:   "provider-session-1",
				ProviderDisplayName: "demo",
				State:               "running",
			}},
		}},
		errors: map[string]error{},
	}
}

// newMetricsStub builds a stub that reports the given counts for every session.
func newMetricsStub(inbound, outbound int) *metricsStubAPI {
	return &metricsStubAPI{
		counts: map[string]protocol.MessageCounts{"provider-session-1": {Inbound: inbound, Outbound: outbound}},
		fail:   map[string]error{},
		code:   map[string]string{},
	}
}

// TestCachedMetricsEnricherReadsOnceWithinTheTTL proves the cache is what makes a
// timer affordable. Two consecutive renders inside the TTL must cost exactly one
// provider read, and both must print the counts.
//
// This is the property the whole change exists for: without it a watch tick would
// fire one provider read per row per tick, which is the cost the architecture
// document forbids.
func TestCachedMetricsEnricherReadsOnceWithinTheTTL(t *testing.T) {
	api := newMetricsStub(7, 3)
	cache := NewMetricsCache()
	enricher := CachedMetricsEnricher(context.Background(), api, cache)
	if enricher == nil {
		t.Fatal("cached enricher is nil for a capable API with a cache")
	}

	for render := 1; render <= 3; render++ {
		var out, diagnostics strings.Builder
		options := TableOptions{Location: time.UTC, EnrichRows: enricher}
		if err := renderListRows(&out, &diagnostics, watchMetricsFixture(), "", false, options); err != nil {
			t.Fatalf("render %d: %v", render, err)
		}
		if !strings.Contains(out.String(), "7/3") {
			t.Fatalf("render %d did not print the counts: %q", render, out.String())
		}
	}
	if got := len(api.queried()); got != 1 {
		t.Fatalf("three renders inside the TTL read the provider %d times, want 1", got)
	}
}

// TestCachedMetricsEnricherRereadsAfterTheTTL proves the cache expires, so a
// cached column cannot present a measurement forever. The clock is advanced by
// storing an entry with an old observation time, because the TTL is a constant
// and a test must not sleep for it.
func TestCachedMetricsEnricherRereadsAfterTheTTL(t *testing.T) {
	api := newMetricsStub(7, 3)
	cache := NewMetricsCache()
	// Seed an expired entry directly, so the next render must treat it as a miss.
	cache.store(metricsCacheKey("endpoint-1", "provider-session-1"),
		protocol.MessageCounts{Inbound: 1, Outbound: 1},
		time.Now().Add(-metricsCacheTTL-time.Second))

	var out, diagnostics strings.Builder
	options := TableOptions{Location: time.UTC, EnrichRows: CachedMetricsEnricher(context.Background(), api, cache)}
	if err := renderListRows(&out, &diagnostics, watchMetricsFixture(), "", false, options); err != nil {
		t.Fatalf("renderListRows: %v", err)
	}
	if got := len(api.queried()); got != 1 {
		t.Fatalf("an expired entry was reused: %d provider reads, want 1", got)
	}
	if !strings.Contains(out.String(), "7/3") {
		t.Fatalf("expired entry was printed instead of the fresh read: %q", out.String())
	}
}

// TestCachedMetricsEnricherIsNilWithoutACache proves a periodic surface that
// forgot to own a cache cannot silently degrade into one provider read per row
// per tick. Returning nil keeps the renderer's "no enrichment" path, which is
// visible as a dash rather than as an unbounded cost.
func TestCachedMetricsEnricherIsNilWithoutACache(t *testing.T) {
	if got := CachedMetricsEnricher(context.Background(), newMetricsStub(1, 1), nil); got != nil {
		t.Fatal("cached enricher without a cache is not nil, so a tick would read every row")
	}
	if got := CachedMetricsEnricher(context.Background(), nil, NewMetricsCache()); got != nil {
		t.Fatal("cached enricher without the capability is not nil")
	}
}

// TestCachedMetricsEnricherDoesNotCacheAFailure proves a failed read is not
// remembered. Caching a failure would present it as a measurement for the whole
// TTL, so a transient provider error would blank the column for thirty seconds.
func TestCachedMetricsEnricherDoesNotCacheAFailure(t *testing.T) {
	api := newMetricsStub(7, 3)
	api.code["provider-session-1"] = protocol.MetricsUnavailable
	cache := NewMetricsCache()
	enricher := CachedMetricsEnricher(context.Background(), api, cache)

	var out, diagnostics strings.Builder
	options := TableOptions{Location: time.UTC, EnrichRows: enricher}
	if err := renderListRows(&out, &diagnostics, watchMetricsFixture(), "", false, options); err != nil {
		t.Fatalf("renderListRows: %v", err)
	}
	if strings.Contains(out.String(), "7/3") {
		t.Fatalf("a provider error code was rendered as a measurement: %q", out.String())
	}

	// The next render must retry, because nothing was cached.
	api.mutex.Lock()
	api.code = map[string]string{}
	api.mutex.Unlock()
	out.Reset()
	diagnostics.Reset()
	if err := renderListRows(&out, &diagnostics, watchMetricsFixture(), "", false, options); err != nil {
		t.Fatalf("second renderListRows: %v", err)
	}
	if got := len(api.queried()); got != 2 {
		t.Fatalf("a failed read was cached: %d provider reads, want 2", got)
	}
	if !strings.Contains(out.String(), "7/3") {
		t.Fatalf("recovered read did not print the counts: %q", out.String())
	}
}

// TestMetricsCacheRetainPrunesDepartedSessions proves the cache cannot grow
// without bound. A session that leaves the table must lose its entry, because a
// long watch over a churning fleet would otherwise accumulate one entry per
// session ever seen.
//
// The test drives the real enrichment path across two renders instead of calling
// retain directly. A direct call would prove the method works while proving
// nothing about whether the enricher still calls it, and the call site is the
// only thing that actually bounds the map.
func TestMetricsCacheRetainPrunesDepartedSessions(t *testing.T) {
	api := newMetricsStub(7, 3)
	api.counts["provider-session-2"] = protocol.MessageCounts{Inbound: 4, Outbound: 5}
	cache := NewMetricsCache()
	enricher := CachedMetricsEnricher(context.Background(), api, cache)

	// The first render contains two sessions, so both are measured and cached.
	both := watchMetricsFixture()
	both.reports["endpoint-1"] = protocol.InventoryReport{
		CollectionStatus: protocol.CollectionSucceeded,
		Sessions: []protocol.Session{
			{ClusterSessionID: "res_1", ProviderSessionID: "provider-session-1", State: "running"},
			{ClusterSessionID: "res_2", ProviderSessionID: "provider-session-2", State: "running"},
		},
	}
	var out, diagnostics strings.Builder
	options := TableOptions{Location: time.UTC, EnrichRows: enricher}
	if err := renderListRows(&out, &diagnostics, both, "", false, options); err != nil {
		t.Fatalf("first renderListRows: %v", err)
	}
	if got := len(api.queried()); got != 2 {
		t.Fatalf("first render read %d rows, want 2", got)
	}

	// The second render no longer contains provider-session-2, so its entry must
	// be pruned rather than remembered for the life of the loop.
	out.Reset()
	diagnostics.Reset()
	if err := renderListRows(&out, &diagnostics, watchMetricsFixture(), "", false, options); err != nil {
		t.Fatalf("second renderListRows: %v", err)
	}

	now := time.Now()
	if _, fresh := cache.lookup(metricsCacheKey("endpoint-1", "provider-session-1"), now); !fresh {
		t.Fatal("the enricher dropped an entry that is still rendered")
	}
	if _, fresh := cache.lookup(metricsCacheKey("endpoint-1", "provider-session-2"), now); fresh {
		t.Fatal("the enricher kept an entry for a session that left the table")
	}
}

// TestMetricsCacheKeySeparatesEndpoints proves the key carries the Endpoint. Two
// Endpoints can report the same provider session identifier, and a key without
// the Endpoint would show one machine's counts on another machine's row.
func TestMetricsCacheKeySeparatesEndpoints(t *testing.T) {
	cache := NewMetricsCache()
	now := time.Now()
	cache.store(metricsCacheKey("endpoint-1", "shared"), protocol.MessageCounts{Inbound: 5, Outbound: 6}, now)

	if _, fresh := cache.lookup(metricsCacheKey("endpoint-2", "shared"), now); fresh {
		t.Fatal("a count measured on one Endpoint was reused for another")
	}
}

// TestWatchRenderPrintsCachedCounts drives the real watch render path, so the
// wiring is proven rather than the helper. A test that only called the enricher
// would pass even if watch never assigned it.
func TestWatchRenderPrintsCachedCounts(t *testing.T) {
	api := newMetricsStub(7, 3)
	controller := &watchController{
		api:          api,
		request:      watchRequest{Interval: defaultWatchInterval},
		color:        ColorPolicy{},
		layoutSource: func() TableLayout { return TableLayout{Width: 200} },
		ctx:          context.Background(),
		metrics:      NewMetricsCache(),
	}
	_, output, err := controller.render(watchMetricsFixture())
	if err != nil {
		t.Fatalf("watch render: %v", err)
	}
	if !strings.Contains(string(output), "7/3") {
		t.Fatalf("watch render did not print the counts: %q", string(output))
	}
	if got := len(api.queried()); got != 1 {
		t.Fatalf("watch render read %d rows, want 1", got)
	}

	// A second tick inside the TTL must reuse the cached value.
	_, output, err = controller.render(watchMetricsFixture())
	if err != nil {
		t.Fatalf("second watch render: %v", err)
	}
	if !strings.Contains(string(output), "7/3") {
		t.Fatalf("second watch render lost the counts: %q", string(output))
	}
	if got := len(api.queried()); got != 1 {
		t.Fatalf("second tick read the provider again: %d reads, want 1", got)
	}
}

// TestWatchRenderWithoutMetricsCapabilityStillRenders proves the column degrades
// to a dash instead of failing the loop when the client cannot read counts. A
// watch that stopped on a missing optional capability would be worse than an
// empty column.
func TestWatchRenderWithoutMetricsCapabilityStillRenders(t *testing.T) {
	controller := &watchController{
		api:          struct{ CommandAPI }{},
		request:      watchRequest{Interval: defaultWatchInterval},
		color:        ColorPolicy{},
		layoutSource: func() TableLayout { return TableLayout{Width: 200} },
		ctx:          context.Background(),
		metrics:      NewMetricsCache(),
	}
	_, output, err := controller.render(watchMetricsFixture())
	if err != nil {
		t.Fatalf("watch render without the capability: %v", err)
	}
	if !strings.Contains(string(output), "MESSAGES") {
		t.Fatalf("watch render dropped the column: %q", string(output))
	}
	if strings.Contains(string(output), "7/3") {
		t.Fatalf("watch render invented counts: %q", string(output))
	}
}

// TestRefreshRenderEnrichesUncached proves refresh reads the counts without a
// cache. A refresh exists to produce current data, so reusing a remembered value
// would make the command answer with an older measurement.
//
// The test drives interactiveRefreshWithArguments rather than building its own
// TableOptions, because the wiring is the part that can be missing. A test that
// set EnrichRows itself would pass even if refresh never assigned it.
func TestRefreshRenderEnrichesUncached(t *testing.T) {
	metrics := newMetricsStub(7, 3)
	// scopeStub names its sessions provider-res-1 and provider-res-2, so the
	// stub must answer for those identifiers rather than for a fixture name.
	metrics.counts["provider-res-1"] = protocol.MessageCounts{Inbound: 7, Outbound: 3}
	metrics.counts["provider-res-2"] = protocol.MessageCounts{Inbound: 7, Outbound: 3}
	stub := &refreshMetricsStub{interactiveStub: scopeStub(), metricsStubAPI: metrics}
	state := interactiveState{}
	state.enterWorkspace()
	var out, diagnostics strings.Builder
	if err := interactiveRefreshWithArguments(context.Background(), stub, &state, refreshArguments{}, &out, &diagnostics, ColorPolicy{}); err != nil {
		t.Fatalf("interactiveRefreshWithArguments: %v", err)
	}
	if !strings.Contains(out.String(), "7/3") {
		t.Fatalf("refresh did not print the counts: %q", out.String())
	}
	if got := len(stub.queried()); got == 0 {
		t.Fatal("refresh never read the provider, so the column cannot be filled")
	}
}

// refreshMetricsStub is an InteractiveAPI that also implements metricsReader, so
// the refresh path can be driven through its real entry point.
type refreshMetricsStub struct {
	*interactiveStub
	*metricsStubAPI
}

// TestTableOptionsForStillNeverEnriches keeps the original guard intact. The
// shared builder must stay neutral: only a surface that decided its own cost
// model may opt in, so a future caller cannot inherit enrichment by accident.
func TestTableOptionsForStillNeverEnriches(t *testing.T) {
	options := tableOptionsFor(io.Discard, ColorPolicy{}, listArguments{}, nil)
	if options.EnrichRows != nil {
		t.Fatal("tableOptionsFor set EnrichRows, so every periodic redraw would enrich")
	}
}
