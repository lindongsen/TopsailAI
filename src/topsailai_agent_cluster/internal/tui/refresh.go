package tui

import (
	"context"
	"fmt"
	"io"
	"sync"
	"time"

	"topsailai_agent_cluster/internal/protocol"
)

// InventoryRefresher forces one fresh Endpoint collection and returns the committed report.
// It is an optional seam, so a client without forced collection keeps read-only behaviour.
type InventoryRefresher interface {
	RefreshInventory(context.Context, string) (protocol.InventoryReport, error)
}

// refreshCommandTimeout exceeds the Server forced-collection budget, so the Server
// reports its own explicit failure before the client gives up waiting.
const refreshCommandTimeout = 35 * time.Second

// RefreshCommandTimeout exposes the forced-collection client budget so every
// entry point waits longer than the Server before giving up.
func RefreshCommandTimeout() time.Duration {
	return refreshCommandTimeout
}

// Refresh forces one fresh Endpoint collection and renders the committed inventory.
// Unlike the interactive command it refuses to degrade to a read-only projection,
// because a command named refresh must never silently return cached data.
func (r CommandRunner) Refresh(ctx context.Context, out, errors io.Writer, filter string, jsonMode bool, options TableOptions) error {
	return r.RefreshWithProgress(ctx, out, errors, filter, jsonMode, options, nil)
}

// RefreshWithProgress forces one fresh collection and reports each Endpoint as it
// completes. A forced collection is the longest silent wait on the read surface,
// so it benefits from the same progress block as a command. The reporter is
// presentation only, so a nil reporter keeps the previous behaviour exactly.
func (r CommandRunner) RefreshWithProgress(ctx context.Context, out, errors io.Writer, filter string, jsonMode bool, options TableOptions, progress *ActionProgress) error {
	if _, ok := r.API.(InventoryRefresher); !ok {
		return fmt.Errorf("forced collection is unavailable: the API client does not support refresh")
	}
	loaded, err := forceCollectionWithProgress(ctx, r.API, filter, progress)
	if err != nil {
		return err
	}
	if filter != "" {
		if refreshErr, failed := loaded.errors[filter]; failed {
			return refreshErr
		}
		if len(loaded.reports) == 0 {
			return fmt.Errorf("endpoint %q not found", filter)
		}
	}
	return renderListRows(out, errors, loaded, filter, jsonMode, options)
}

// RefreshAfterStart forces one fresh collection for the Endpoint that accepted a
// start, so the operator's next list already contains the launched session instead
// of waiting for the periodic collection. The collection is scoped to that single
// Endpoint because a workspace-wide collection would multiply provider discovery
// cost by the fleet size for one launch.
//
// A request the provider did not apply is not collected, because no session was
// created. A client without the forced-collection seam keeps its read-only
// behaviour. A collection failure is written to diagnostics and never returned as
// an error, because the admission already succeeded and reporting a failure would
// deny a launch that happened.
func (r CommandRunner) RefreshAfterStart(ctx context.Context, out, diagnostics io.Writer, endpointID string, result map[string]any, jsonMode bool, options TableOptions) error {
	if ReceiptForStatus(result).EffectCertainty == protocol.EffectNotApplied {
		return nil
	}
	if _, ok := r.API.(InventoryRefresher); !ok {
		return nil
	}
	// The pre-refresh projection is read from the Server, so it costs no provider
	// discovery. It is the baseline for deciding whether the launch became visible.
	before, baselineKnown := sessionIDs(ctx, r.API, endpointID)
	loaded, err := forceCollection(ctx, r.API, endpointID)
	if err != nil {
		return startRefreshDiagnostic(diagnostics, err)
	}
	if refreshErr, failed := loaded.errors[endpointID]; failed {
		return startRefreshDiagnostic(diagnostics, refreshErr)
	}
	// Only the started Endpoint was collected, so the table is filtered to it.
	// Rendering the whole fleet here would print every other Endpoint as having no
	// sessions. A JSON caller receives the receipt alone, so the table is skipped
	// rather than corrupting the machine-readable document.
	if !jsonMode {
		if err := renderListRows(out, diagnostics, loaded, endpointID, false, options); err != nil {
			return startRefreshDiagnostic(diagnostics, err)
		}
	}
	if baselineKnown && !appearedSince(before, loaded.reports[endpointID]) {
		// The provider reports a background launch as submitted, not started, and a
		// session only becomes routable once its process is observed holding the
		// output file. A collection issued immediately after start can therefore
		// legitimately omit the new session. Reporting that as a failure would deny a
		// launch that did happen, so it is reported as pending visibility instead.
		_, _ = fmt.Fprintf(diagnostics, "session submitted but not yet visible; the next collection will show it\n")
	}
	return nil
}

// refreshConcurrency bounds how many Endpoints are collected at once. The Server
// admits at most 64 pending forced collections, so a larger pool would only turn
// capacity into rejections; 16 keeps a fleet refresh well inside that budget while
// bounding the provider discovery load one operator command can create.
const refreshConcurrency = 16

// refreshEndpointTimeout bounds one Endpoint's forced collection. It exceeds the
// Server's own 30-second budget so the Server reports its explicit failure first,
// and it stays below the command budget so one hung Endpoint cannot consume the
// whole command.
const refreshEndpointTimeout = 32 * time.Second

// endpointResult is one Endpoint's forced-collection outcome. Results are stored
// by index, so the rendered order never depends on completion order.
type endpointResult struct {
	endpointID string
	report     *protocol.InventoryReport
	err        error
}

// forceCollection asks every Endpoint in scope to collect a fresh inventory and
// returns the committed documents. Endpoints are collected concurrently, because
// a serial loop makes the command cost the sum of every Endpoint instead of the
// slowest one. A failed Endpoint keeps its last committed document and is reported
// through the load errors, so one slow or offline Endpoint never hides the others.
func forceCollection(ctx context.Context, api InteractiveAPI, filter string) (reportLoad, error) {
	return forceCollectionWithProgress(ctx, api, filter, nil)
}

// forceCollectionWithProgress is forceCollection with a progress reporter. Each
// completed Endpoint is reported as one stage row, so a fleet refresh shows which
// Endpoints have answered instead of a single opaque wait. The reporter is
// presentation only, so a nil reporter keeps the previous behaviour exactly.
func forceCollectionWithProgress(ctx context.Context, api InteractiveAPI, filter string, progress *ActionProgress) (reportLoad, error) {
	endpoints, err := api.ListEndpoints(ctx)
	if err != nil {
		return reportLoad{}, err
	}
	loaded := reportLoad{endpoints: endpoints, reports: make(map[string]protocol.InventoryReport), errors: make(map[string]error)}
	scoped := make([]protocol.Endpoint, 0, len(endpoints))
	for _, endpoint := range endpoints {
		if filter != "" && endpoint.EndpointID != filter {
			continue
		}
		scoped = append(scoped, endpoint)
	}
	refresher, forced := api.(InventoryRefresher)
	if !forced {
		// A client without the forced-collection seam keeps the read-only path.
		for _, endpoint := range scoped {
			report, fetchErr := api.GetInventory(ctx, endpoint.EndpointID)
			if fetchErr != nil {
				loaded.errors[endpoint.EndpointID] = fetchErr
				continue
			}
			loaded.reports[endpoint.EndpointID] = report
		}
		return loaded, nil
	}
	// Each Endpoint is collected exactly once. The Endpoint serializes its own
	// collection cycles, so a second request for the same Endpoint would only run
	// provider discovery twice without producing newer data.
	results := make([]endpointResult, len(scoped))
	workers := refreshConcurrency
	if workers > len(scoped) {
		workers = len(scoped)
	}
	slots := make(chan struct{}, workers)
	var wg sync.WaitGroup
	for index := range scoped {
		wg.Add(1)
		go func(index int) {
			defer wg.Done()
			slots <- struct{}{}
			defer func() { <-slots }()
			results[index] = collectEndpoint(ctx, api, refresher, scoped[index].EndpointID)
			progress.Stage(progressEndpointStage(results[index]))
		}(index)
	}
	wg.Wait()
	progress.Tick()
	for _, result := range results {
		if result.err != nil {
			loaded.errors[result.endpointID] = result.err
		}
		if result.report != nil {
			loaded.reports[result.endpointID] = *result.report
		}
	}
	return loaded, nil
}

// progressEndpointStage describes one completed Endpoint collection. A failed
// Endpoint is reported as failed rather than omitted, because a silent gap would
// let the operator believe every Endpoint answered.
func progressEndpointStage(result endpointResult) string {
	name := sanitizeInlineText(result.endpointID)
	if result.err != nil {
		return name + ": collection failed"
	}
	return name + ": collected"
}

// collectEndpoint forces one collection for a single Endpoint. The committed
// report the Server returns is used directly, because the Server re-reads it from
// storage after the commit, so a following read would return the same document.
func collectEndpoint(parent context.Context, api InteractiveAPI, refresher InventoryRefresher, endpointID string) endpointResult {
	ctx, cancel := context.WithTimeout(parent, refreshEndpointTimeout)
	defer cancel()
	report, err := refresher.RefreshInventory(ctx, endpointID)
	if err != nil {
		result := endpointResult{endpointID: endpointID, err: err}
		// The last committed document stays visible, labelled by the failure. The
		// read uses the parent budget, because the per-Endpoint budget may already
		// be exhausted by the failed collection itself.
		if last, fetchErr := api.GetInventory(parent, endpointID); fetchErr == nil {
			result.report = &last
		}
		return result
	}
	return endpointResult{endpointID: endpointID, report: &report}
}
