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
