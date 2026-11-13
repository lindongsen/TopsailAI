package main

import (
	"context"
	"log/slog"
	"time"

	serverstorage "topsailai_agent_cluster/internal/storage/server"
)

// endpointExpiryStore is the Server storage seam used by the retention loop.
type endpointExpiryStore interface {
	ExpireOfflineEndpoints(context.Context, int64) (serverstorage.EndpointExpiryResult, error)
	PurgeExpiredCommands(context.Context, int64) (int64, error)
}

// runEndpointExpiry removes expired records immediately at startup and then on
// a bounded cadence until the Server context is cancelled.
func runEndpointExpiry(ctx context.Context, logger *slog.Logger, store endpointExpiryStore, retention, commandRetention time.Duration) {
	runEndpointExpiryAtInterval(ctx, logger, store, retention, commandRetention, endpointExpiryInterval(retention))
}

// runEndpointExpiryAtInterval owns the recurring loop with an explicit cadence
// so periodic execution can be verified without waiting for a production tick.
func runEndpointExpiryAtInterval(ctx context.Context, logger *slog.Logger, store endpointExpiryStore, retention, commandRetention, interval time.Duration) {
	ticker := time.NewTicker(interval)
	defer ticker.Stop()
	for {
		expireEndpointRecords(ctx, logger, store, retention, commandRetention, time.Now())
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
// The command purge runs before endpoint expiry so a metadata row blocked only
// by a now-purgeable command is removed in the same sweep instead of surviving
// one extra cycle.
//
// The completion line is emitted at Info even when nothing was deleted. Without
// it a sweep that selects zero rows is indistinguishable from a sweep that never
// ran, which is exactly how the unreachable offline state stayed hidden. Info is
// required rather than Debug because the logger has no level option, so the
// effective level is Info and a Debug line would never appear in production.
func expireEndpointRecords(ctx context.Context, logger *slog.Logger, store endpointExpiryStore, retention, commandRetention time.Duration, now time.Time) {
	cutoff := now.Add(-retention)
	commandCutoff := now.Add(-commandRetention)
	purgedCommands, err := store.PurgeExpiredCommands(ctx, commandCutoff.UnixMilli())
	if err != nil {
		if ctx.Err() == nil {
			logger.Error("purge expired command records", "command_retention", commandRetention.String(), "cutoff_at_ms", commandCutoff.UnixMilli(), "error", err)
		}
		return
	}
	result, err := store.ExpireOfflineEndpoints(ctx, cutoff.UnixMilli())
	if err != nil {
		if ctx.Err() == nil {
			logger.Error("expire offline endpoint records", "retention", retention.String(), "cutoff_at_ms", cutoff.UnixMilli(), "error", err)
		}
		return
	}
	for _, endpointID := range result.InventoryEndpointIDs {
		logger.Info("expired offline endpoint inventory", "endpoint_id", endpointID, "retention", retention.String(), "cutoff_at_ms", cutoff.UnixMilli())
	}
	for _, endpointID := range result.DeletedEndpointIDs {
		logger.Info("expired offline endpoint metadata", "endpoint_id", endpointID, "retention", retention.String(), "cutoff_at_ms", cutoff.UnixMilli())
	}
	logger.Info("retention sweep complete", "retention", retention.String(), "cutoff_at_ms", cutoff.UnixMilli(), "command_retention", commandRetention.String(), "command_cutoff_at_ms", commandCutoff.UnixMilli(), "purged_commands", purgedCommands, "deleted_inventory", len(result.InventoryEndpointIDs), "deleted_metadata", len(result.DeletedEndpointIDs))
}
