package tui

import (
	"context"
	"sync"
	"time"

	"topsailai_agent_cluster/internal/protocol"
)

// metricsReader is the optional API capability that reads one session's live
// message counts.
//
// It is a separate interface rather than a method on CommandAPI, because a
// surface that cannot read counts must still satisfy the command surface. A
// client that does not implement it renders "-" instead of failing, so one
// missing capability never breaks every list.
type metricsReader interface {
	GetMetrics(context.Context, string, string) (protocol.SessionMetrics, error)
}

// maxMetricsRows bounds how many rows one list render enriches. The counts are a
// live provider read, so an unbounded fan-out would turn one list into one
// provider call per session in the fleet. A longer table keeps its first rows
// measured and renders the rest as "-", which is an honest unmeasured value
// rather than a wrong one.
const maxMetricsRows = 50

// metricsWorkers bounds how many provider reads one list render runs at once, so
// a wide table cannot open one provider process per row.
const metricsWorkers = 8

// metricsRowBudget bounds one row's read. It is short because the counts are an
// addition to a table that is already rendered from committed inventory: a slow
// provider must cost one cell, never the whole command.
const metricsRowBudget = 5 * time.Second

// MetricsEnricher returns the closure a list render passes as
// TableOptions.EnrichRows, or nil when the API cannot read message counts.
//
// Returning nil rather than a no-op closure is deliberate: the renderer then
// skips the enrichment entirely, so a client without the capability pays nothing
// and cannot accidentally be treated as having measured every row.
//
// The context is captured here because the caller owns the command budget. A
// render must not invent a deadline, and a per-row deadline is derived from this
// one so a slow provider costs one cell rather than the whole command.
func MetricsEnricher(ctx context.Context, api CommandAPI) func([]SessionRow) {
	if _, ok := api.(metricsReader); !ok {
		return nil
	}
	return func(rows []SessionRow) {
		enrichMessages(ctx, api, rows)
	}
}

// enrichMessages attaches live message counts to the rows a list render is about
// to print.
//
// Only the rows passed here are read, which is the point of the seam: the caller
// hands over the exact slice it will render, so a filtered or brief table never
// pays for a row it does not show. A failed read leaves the row unmeasured
// instead of failing the command, because the table is built from committed
// inventory and a live count is an addition to it, not a precondition.
func enrichMessages(parent context.Context, api CommandAPI, rows []SessionRow) {
	reader, ok := api.(metricsReader)
	if !ok {
		return
	}
	targets := make([]int, 0, len(rows))
	for index := range rows {
		if len(targets) == maxMetricsRows {
			break
		}
		// A row with no provider session identifier cannot be addressed by the
		// provider, so it stays unmeasured rather than being queried with an
		// empty target.
		if rows[index].ProviderSessionID == "" {
			continue
		}
		targets = append(targets, index)
	}
	if len(targets) == 0 {
		return
	}
	slots := make(chan struct{}, metricsWorkers)
	var wait sync.WaitGroup
	for _, index := range targets {
		wait.Add(1)
		go func(index int) {
			defer wait.Done()
			slots <- struct{}{}
			defer func() { <-slots }()
			ctx, cancel := context.WithTimeout(parent, metricsRowBudget)
			defer cancel()
			metrics, err := reader.GetMetrics(ctx, rows[index].EndpointID, rows[index].ProviderSessionID)
			// A provider that reports an error code has not measured the session,
			// so the row keeps no counts. Presenting the zero value would state a
			// measurement nobody made.
			if err != nil || metrics.ErrorCode != "" {
				return
			}
			counts := metrics.Messages
			rows[index].Messages = &counts
		}(index)
	}
	wait.Wait()
}

// metricsCacheTTL bounds how long one remembered message count stays usable.
//
// The counts are a live provider read costing about 1.25 s per session, so a
// periodic surface cannot read them on every tick. A TTL turns that cost from
// "one read per row per tick" into "one read per row per TTL", which is the only
// shape that lets a timer show the column at all. Thirty seconds is chosen
// against the five-second default watch interval: the counts refresh every sixth
// tick, so the numbers stay useful while the provider cost stays bounded.
//
// It is a constant rather than a flag because the watch interval is already the
// operator's control over freshness, and a second knob for one column would be a
// configuration surface nobody asked for.
const metricsCacheTTL = 30 * time.Second

// metricsCacheEntry is one remembered measurement and when it was taken.
type metricsCacheEntry struct {
	counts     protocol.MessageCounts
	observedAt time.Time
}

// MetricsCache remembers message counts across the renders of one periodic
// surface.
//
// It exists because a timer and an explicit command have different cost models.
// An explicit list may read the provider every time, because the operator asked
// for current data. A watch tick may not, because the tick rate would multiply
// the provider cost by itself. The cache is therefore owned by the loop that
// needs it and discarded with that loop, so no stale count can outlive the
// surface that produced it.
//
// The cache is not shared between surfaces and is not process-global: a second
// watch loop, or a list run beside a watch, must not inherit a measurement taken
// for a different render.
type MetricsCache struct {
	mu      sync.Mutex
	entries map[string]metricsCacheEntry
}

// NewMetricsCache returns an empty cache. An empty cache reads every row on the
// first render, which is exactly the behaviour of an uncached list.
func NewMetricsCache() *MetricsCache {
	return &MetricsCache{entries: make(map[string]metricsCacheEntry)}
}

// metricsCacheKey identifies one measurement. The pair is the address the
// metrics read uses, so two rows that would read the same session share one
// entry and a row that changes Endpoint does not reuse the previous answer.
func metricsCacheKey(endpointID, sessionID string) string {
	return endpointID + "\x00" + sessionID
}

// lookup returns the remembered counts and whether they are still fresh. An
// expired entry is reported as a miss rather than deleted here, so the caller
// decides when to prune and the lock is held for one map read.
func (c *MetricsCache) lookup(key string, now time.Time) (protocol.MessageCounts, bool) {
	c.mu.Lock()
	defer c.mu.Unlock()
	entry, ok := c.entries[key]
	if !ok {
		return protocol.MessageCounts{}, false
	}
	if now.Sub(entry.observedAt) >= metricsCacheTTL {
		return protocol.MessageCounts{}, false
	}
	return entry.counts, true
}

// store records one measurement taken at the given time.
func (c *MetricsCache) store(key string, counts protocol.MessageCounts, now time.Time) {
	c.mu.Lock()
	defer c.mu.Unlock()
	c.entries[key] = metricsCacheEntry{counts: counts, observedAt: now}
}

// retain drops every entry whose key is not in keep.
//
// A long watch over a churning fleet would otherwise grow the map without bound,
// because a session that left the table would keep its entry forever. Pruning to
// the rows of the current render makes the cache size follow the table size,
// which is the only bound the loop can actually observe.
func (c *MetricsCache) retain(keep map[string]bool) {
	c.mu.Lock()
	defer c.mu.Unlock()
	for key := range c.entries {
		if !keep[key] {
			delete(c.entries, key)
		}
	}
}

// CachedMetricsEnricher returns the closure a periodic render passes as
// TableOptions.EnrichRows, or nil when the API cannot read message counts or no
// cache was supplied.
//
// Returning nil rather than a no-op closure keeps the existing contract: a
// client without the capability pays nothing and can never be mistaken for
// having measured every row. A nil cache is treated the same way, because a
// periodic surface that forgot to own a cache must not silently fall back to one
// provider read per row per tick.
func CachedMetricsEnricher(ctx context.Context, api CommandAPI, cache *MetricsCache) func([]SessionRow) {
	if cache == nil {
		return nil
	}
	if _, ok := api.(metricsReader); !ok {
		return nil
	}
	return func(rows []SessionRow) {
		enrichMessagesCached(ctx, api, cache, rows)
	}
}

// enrichMessagesCached attaches message counts to the rows a periodic render is
// about to print, reading the provider only for rows whose cached value expired.
//
// A fresh entry is applied without any provider call, which is what makes a
// timer affordable. A miss is read exactly as an uncached list reads it, so a
// failed read still leaves the row unmeasured instead of failing the render, and
// a provider error code still means "not measured" rather than zero.
//
// The read budget applies per miss, not per render, so a slow provider costs one
// cell rather than the whole tick.
func enrichMessagesCached(parent context.Context, api CommandAPI, cache *MetricsCache, rows []SessionRow) {
	reader, ok := api.(metricsReader)
	if !ok {
		return
	}
	now := time.Now()
	keep := make(map[string]bool, len(rows))
	misses := make([]int, 0, len(rows))
	for index := range rows {
		// A row with no provider session identifier cannot be addressed by the
		// provider, so it stays unmeasured and is never cached.
		if rows[index].ProviderSessionID == "" {
			continue
		}
		key := metricsCacheKey(rows[index].EndpointID, rows[index].ProviderSessionID)
		keep[key] = true
		if counts, fresh := cache.lookup(key, now); fresh {
			cached := counts
			rows[index].Messages = &cached
			continue
		}
		// The cap bounds provider reads, not filled cells: a cached hit costs
		// nothing, so a long table still shows every count it already knows.
		if len(misses) == maxMetricsRows {
			continue
		}
		misses = append(misses, index)
	}
	cache.retain(keep)
	if len(misses) == 0 {
		return
	}
	slots := make(chan struct{}, metricsWorkers)
	var wait sync.WaitGroup
	for _, index := range misses {
		wait.Add(1)
		go func(index int) {
			defer wait.Done()
			slots <- struct{}{}
			defer func() { <-slots }()
			ctx, cancel := context.WithTimeout(parent, metricsRowBudget)
			defer cancel()
			metrics, err := reader.GetMetrics(ctx, rows[index].EndpointID, rows[index].ProviderSessionID)
			// A provider that reports an error code has not measured the session,
			// so the row keeps no counts and nothing is cached. Caching the
			// failure would present it as a measurement for the whole TTL.
			if err != nil || metrics.ErrorCode != "" {
				return
			}
			counts := metrics.Messages
			rows[index].Messages = &counts
			cache.store(metricsCacheKey(rows[index].EndpointID, rows[index].ProviderSessionID), counts, time.Now())
		}(index)
	}
	wait.Wait()
}
