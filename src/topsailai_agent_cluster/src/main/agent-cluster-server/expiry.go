package main

import (
	"context"
	"log/slog"
	"time"

	serverstorage "topsailai_agent_cluster/internal/storage/server"
)

// endpointExpiryStore is the Server storage seam used by the retention loop.
type endpointExpiryStore interface {
	ReconcileExpiredCommands(context.Context, int64) (int64, error)
	PurgeExpiredCommands(context.Context, int64) (int64, error)
	DegradeOfflineEndpoints(context.Context, int64, int64, int64) (serverstorage.EndpointDegradeResult, error)
	ExpireDegradedEndpoints(context.Context, int64) (serverstorage.EndpointExpiryResult, error)
}

// runEndpointExpiry removes expired records immediately at startup and then on
// a bounded cadence until the Server context is cancelled.
func runEndpointExpiry(ctx context.Context, logger *slog.Logger, store endpointExpiryStore, retention, commandRetention, degradedRetention time.Duration) {
	runEndpointExpiryAtInterval(ctx, logger, store, retention, commandRetention, degradedRetention, endpointExpiryInterval(retention))
}

// runEndpointExpiryAtInterval owns the recurring loop with an explicit cadence
// so periodic execution can be verified without waiting for a production tick.
func runEndpointExpiryAtInterval(ctx context.Context, logger *slog.Logger, store endpointExpiryStore, retention, commandRetention, degradedRetention, interval time.Duration) {
	ticker := time.NewTicker(interval)
	defer ticker.Stop()
	for {
		expireEndpointRecords(ctx, logger, store, retention, commandRetention, degradedRetention, time.Now())
		select {
		case <-ctx.Done():
			return
		case <-ticker.C:
		}
	}
}

// endpointExpiryInterval derives a responsive cadence without polling more
// often than once per second or waiting more than one minute between sweeps.
func endpointExpiryInterval(retention time.Duration) time.Duration {
	interval := retention / 2
	if interval < time.Second {
		return time.Second
	}
	if interval > time.Minute {
		return time.Minute
	}
	return interval
}

// expireEndpointRecords executes one sweep and logs every removed durable row.
//
// Convergence runs first, then the command purge, then endpoint degradation,
// then endpoint expiry. The order matters three times:
//
//   - Convergence before purge: a command that is still non-terminal is not
//     purgeable, so purging first would leave a converged row waiting one extra
//     cycle before it could be deleted.
//   - Purge before endpoint expiry: a metadata row blocked only by a now-purgeable
//     command is removed in the same sweep instead of surviving one extra cycle.
//   - Degrade before expiry: expiry only selects rows that are already degraded,
//     so an offline row that just crossed the offline window must be degraded in
//     this sweep or it waits one more cycle before its degraded window even starts.
//
// Degrading and expiring are separate steps because they answer different
// questions. Degrading decides that a disconnected machine is no longer usable
// and drops its inventory projection; expiring decides that the record of that
// machine stops existing. Collapsing them would delete the record at the moment
// it became degraded, so the degraded window would never exist.
//
// The completion line is emitted at Info even when nothing was deleted. Without
// it a sweep that selects zero rows is indistinguishable from a sweep that never
// ran, which is exactly how the unreachable offline state stayed hidden. Info is
// required rather than Debug because the logger has no level option, so the
// effective level is Info and a Debug line would never appear in production.
func expireEndpointRecords(ctx context.Context, logger *slog.Logger, store endpointExpiryStore, retention, commandRetention, degradedRetention time.Duration, now time.Time) {
	cutoff := now.Add(-retention)
	commandCutoff := now.Add(-commandRetention)
	convergedCommands, err := store.ReconcileExpiredCommands(ctx, now.UnixMilli())
	if err != nil {
		if ctx.Err() == nil {
			logger.Error("reconcile expired command records", "error", err)
		}
		return
	}
	purgedCommands, err := store.PurgeExpiredCommands(ctx, commandCutoff.UnixMilli())
	if err != nil {
		if ctx.Err() == nil {
			logger.Error("purge expired command records", "command_retention", commandRetention.String(), "cutoff_at_ms", commandCutoff.UnixMilli(), "error", err)
		}
		return
	}
	degraded, err := store.DegradeOfflineEndpoints(ctx, cutoff.UnixMilli(), now.UnixMilli(), degradedRetention.Milliseconds())
	if err != nil {
		if ctx.Err() == nil {
			logger.Error("degrade offline endpoint records", "retention", retention.String(), "cutoff_at_ms", cutoff.UnixMilli(), "degraded_retention", degradedRetention.String(), "error", err)
		}
		return
	}
	for _, endpointID := range degraded.DegradedEndpointIDs {
		logger.Info("degraded offline endpoint", "endpoint_id", endpointID, "retention", retention.String(), "cutoff_at_ms", cutoff.UnixMilli(), "degraded_retention", degradedRetention.String(), "expires_at_ms", now.Add(degradedRetention).UnixMilli())
	}
	for _, endpointID := range degraded.InventoryEndpointIDs {
		logger.Info("deleted degraded endpoint inventory", "endpoint_id", endpointID, "retention", retention.String(), "cutoff_at_ms", cutoff.UnixMilli())
	}
	result, err := store.ExpireDegradedEndpoints(ctx, now.UnixMilli())
	if err != nil {
		if ctx.Err() == nil {
			logger.Error("expire degraded endpoint records", "degraded_retention", degradedRetention.String(), "error", err)
		}
		return
	}
	for _, commandID := range result.DeletedCommandIDs {
		logger.Info("deleted expired endpoint command", "command_id", commandID, "degraded_retention", degradedRetention.String())
	}
	for _, endpointID := range result.InventoryEndpointIDs {
		logger.Info("expired degraded endpoint inventory", "endpoint_id", endpointID, "degraded_retention", degradedRetention.String())
	}
	for _, endpointID := range result.DeletedEndpointIDs {
		logger.Info("expired degraded endpoint metadata", "endpoint_id", endpointID, "degraded_retention", degradedRetention.String())
	}
	logger.Info("retention sweep complete", "retention", retention.String(), "cutoff_at_ms", cutoff.UnixMilli(), "command_retention", commandRetention.String(), "command_cutoff_at_ms", commandCutoff.UnixMilli(), "degraded_retention", degradedRetention.String(), "converged_commands", convergedCommands, "purged_commands", purgedCommands, "degraded_endpoints", len(degraded.DegradedEndpointIDs), "deleted_degraded_inventory", len(degraded.InventoryEndpointIDs), "deleted_commands", len(result.DeletedCommandIDs), "deleted_inventory", len(result.InventoryEndpointIDs), "deleted_metadata", len(result.DeletedEndpointIDs))
}
