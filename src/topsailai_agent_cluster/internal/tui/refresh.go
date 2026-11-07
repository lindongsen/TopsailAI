package tui

import (
	"context"
	"fmt"
	"io"
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
	if _, ok := r.API.(InventoryRefresher); !ok {
		return fmt.Errorf("forced collection is unavailable: the API client does not support refresh")
	}
	loaded, err := forceCollection(ctx, r.API, filter)
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

// forceCollection asks every Endpoint in scope to collect a fresh inventory and
// returns the committed documents. A failed Endpoint keeps its last committed
// document and is reported through the load errors, so one slow or offline
// Endpoint never hides the others.
func forceCollection(ctx context.Context, api InteractiveAPI, filter string) (reportLoad, error) {
	endpoints, err := api.ListEndpoints(ctx)
	if err != nil {
		return reportLoad{}, err
	}
	loaded := reportLoad{endpoints: endpoints, reports: make(map[string]protocol.InventoryReport), errors: make(map[string]error)}
	refresher, forced := api.(InventoryRefresher)
	for _, endpoint := range endpoints {
		if filter != "" && endpoint.EndpointID != filter {
			continue
		}
		if forced {
			if _, refreshErr := refresher.RefreshInventory(ctx, endpoint.EndpointID); refreshErr != nil {
				loaded.errors[endpoint.EndpointID] = refreshErr
				// The last committed document stays visible, labelled by the failure.
				if report, fetchErr := api.GetInventory(ctx, endpoint.EndpointID); fetchErr == nil {
					loaded.reports[endpoint.EndpointID] = report
				}
				continue
			}
		}
		report, fetchErr := api.GetInventory(ctx, endpoint.EndpointID)
		if fetchErr != nil {
			loaded.errors[endpoint.EndpointID] = fetchErr
			continue
		}
		loaded.reports[endpoint.EndpointID] = report
	}
	return loaded, nil
}
