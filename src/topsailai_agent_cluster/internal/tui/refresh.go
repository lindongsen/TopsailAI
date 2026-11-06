package tui

import (
	"context"
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
