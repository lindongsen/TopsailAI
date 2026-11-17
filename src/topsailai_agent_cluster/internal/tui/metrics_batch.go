package tui

import (
	"context"
	"sync"
	"time"

	"topsailai_agent_cluster/internal/protocol"
)

// metricsBatchReader is the optional API capability that reads message counts for
// a set of sessions on one Endpoint in a single call.
//
// It is a separate interface rather than a method on metricsReader, because the
// two capabilities have different costs and a client may honestly support one
// without the other. A client that implements only metricsReader still renders
// every row, just at one provider read per row.
type metricsBatchReader interface {
	GetMetricsBatch(context.Context, string, []string) (protocol.SessionMetricsBatch, error)
}

// metricsBatchBudget bounds one set read for one Endpoint.
//
// It is longer than metricsRowBudget because it replaces many row reads, and
// shorter than the command budget so the column degrades before the command does.
// The layering is deliberate: the Endpoint reports its own failure at 8 seconds,
// the channel at 9, and this surface at 10, so the innermost component is always
// the one that explains the failure.
const metricsBatchBudget = 10 * time.Second

// metricsTarget names one row whose counts are wanted.
//
// The row index travels with the address because the answer is applied back to the
// slice the caller is about to render. Keeping the index here means the resolution
// code never has to search for the row it just measured.
type metricsTarget struct {
	index      int
	endpointID string
	sessionID  string
}

// readMetrics resolves message counts for the given targets.
//
// It prefers one set read per Endpoint and falls back to per-row reads only for
// what the set did not answer. The preference is the whole point: reaching a
// provider costs a fixed amount that does not depend on how many sessions are
// asked about, so a table costs one read per Endpoint instead of one per row.
//
// The fallback is not a second implementation of the same decision. It covers two
// distinct cases that the set read cannot: a client whose adapter has no batch
// capability, and a session the provider was asked about but could not measure.
// Both must still render, so both are read the old way.
func readMetrics(parent context.Context, api CommandAPI, targets []metricsTarget) map[int]protocol.MessageCounts {
	resolved := make(map[int]protocol.MessageCounts, len(targets))
	if len(targets) == 0 {
		return resolved
	}
	var mu sync.Mutex
	slots := make(chan struct{}, metricsWorkers)
	var wait sync.WaitGroup
	for _, group := range groupTargetsByEndpoint(targets) {
		wait.Add(1)
		go func(group []metricsTarget) {
			defer wait.Done()
			slots <- struct{}{}
			defer func() { <-slots }()
			for index, counts := range resolveEndpointGroup(parent, api, group) {
				mu.Lock()
				resolved[index] = counts
				mu.Unlock()
			}
		}(group)
	}
	wait.Wait()
	return resolved
}

// groupTargetsByEndpoint splits targets into one group per Endpoint, preserving
// the order in which each Endpoint first appeared.
//
// The grouping is what makes the set read possible: a batch request is scoped to
// one Endpoint, so a table that spans Endpoints costs one read per Endpoint rather
// than one read for the whole table. Preserving order keeps the work deterministic,
// which matters because the groups are resolved concurrently.
func groupTargetsByEndpoint(targets []metricsTarget) [][]metricsTarget {
	order := make([]string, 0, len(targets))
	byEndpoint := make(map[string][]metricsTarget, len(targets))
	for _, target := range targets {
		if _, seen := byEndpoint[target.endpointID]; !seen {
			order = append(order, target.endpointID)
		}
		byEndpoint[target.endpointID] = append(byEndpoint[target.endpointID], target)
	}
	groups := make([][]metricsTarget, 0, len(order))
	for _, endpointID := range order {
		groups = append(groups, byEndpoint[endpointID])
	}
	return groups
}

// resolveEndpointGroup resolves one Endpoint's targets, preferring the set read.
func resolveEndpointGroup(parent context.Context, api CommandAPI, group []metricsTarget) map[int]protocol.MessageCounts {
	resolved := make(map[int]protocol.MessageCounts, len(group))
	remaining := group
	if batch, ok := api.(metricsBatchReader); ok {
		answered := readEndpointBatch(parent, batch, group)
		for index, counts := range answered {
			resolved[index] = counts
		}
		remaining = unansweredTargets(group, answered)
	}
	if len(remaining) == 0 {
		return resolved
	}
	reader, ok := api.(metricsReader)
	if !ok {
		return resolved
	}
	for index, counts := range readTargetsIndividually(parent, reader, remaining) {
		resolved[index] = counts
	}
	return resolved
}

// readEndpointBatch performs one set read for one Endpoint and returns the counts
// it answered, keyed by row index.
//
// A whole-request failure returns nothing, which sends every target in the group to
// the per-row fallback. That is the correct degradation: an adapter without the
// capability, a refused caller and an unreachable Endpoint all mean "this set was
// not answered", and none of them is a reason to leave the column blank.
//
// A member that carries its own error code is dropped rather than recorded, because
// an error code is not a measurement. The member is then absent from the answer, so
// the caller renders it unmeasured instead of as zero.
func readEndpointBatch(parent context.Context, batch metricsBatchReader, group []metricsTarget) map[int]protocol.MessageCounts {
	answered := make(map[int]protocol.MessageCounts, len(group))
	ids := make([]string, 0, len(group))
	seen := make(map[string]bool, len(group))
	for _, target := range group {
		if seen[target.sessionID] {
			continue
		}
		seen[target.sessionID] = true
		ids = append(ids, target.sessionID)
	}
	ctx, cancel := context.WithTimeout(parent, metricsBatchBudget)
	defer cancel()
	result, err := batch.GetMetricsBatch(ctx, group[0].endpointID, ids)
	if err != nil || result.ErrorCode != "" {
		return answered
	}
	bySession := make(map[string]protocol.MessageCounts, len(result.Results))
	for _, member := range result.Results {
		if member.ErrorCode != "" {
			continue
		}
		bySession[member.ProviderSessionID] = member.Messages
	}
	for _, target := range group {
		if counts, ok := bySession[target.sessionID]; ok {
			answered[target.index] = counts
		}
	}
	return answered
}

// unansweredTargets returns the targets the set read did not answer.
func unansweredTargets(group []metricsTarget, answered map[int]protocol.MessageCounts) []metricsTarget {
	remaining := make([]metricsTarget, 0, len(group))
	for _, target := range group {
		if _, ok := answered[target.index]; ok {
			continue
		}
		remaining = append(remaining, target)
	}
	return remaining
}

// readTargetsIndividually reads each target with its own provider call.
//
// This is the original per-row path, kept because it is the only path that works
// for a client whose adapter has no batch capability and for a session the provider
// could not measure in a set. Each read keeps its own short budget, so a slow
// provider still costs one cell rather than the whole render.
func readTargetsIndividually(parent context.Context, reader metricsReader, targets []metricsTarget) map[int]protocol.MessageCounts {
	resolved := make(map[int]protocol.MessageCounts, len(targets))
	var mu sync.Mutex
	slots := make(chan struct{}, metricsWorkers)
	var wait sync.WaitGroup
	for _, target := range targets {
		wait.Add(1)
		go func(target metricsTarget) {
			defer wait.Done()
			slots <- struct{}{}
			defer func() { <-slots }()
			ctx, cancel := context.WithTimeout(parent, metricsRowBudget)
			defer cancel()
			metrics, err := reader.GetMetrics(ctx, target.endpointID, target.sessionID)
			// A provider that reports an error code has not measured the session,
			// so the row keeps no counts. Presenting the zero value would state a
			// measurement nobody made.
			if err != nil || metrics.ErrorCode != "" {
				return
			}
			mu.Lock()
			resolved[target.index] = metrics.Messages
			mu.Unlock()
		}(target)
	}
	wait.Wait()
	return resolved
}
