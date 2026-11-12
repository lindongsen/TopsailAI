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
}

// runEndpointExpiry removes expired records immediately at startup and then on
// a bounded cadence until the Server context is cancelled.
func runEndpointExpiry(ctx context.Context, logger *slog.Logger, store endpointExpiryStore, retention time.Duration) {
	runEndpointExpiryAtInterval(ctx, logger, store, retention, endpointExpiryInterval(retention))
}

// runEndpointExpiryAtInterval owns the recurring loop with an explicit cadence
// so periodic execution can be verified without waiting for a production tick.
func runEndpointExpiryAtInterval(ctx context.Context, logger *slog.Logger, store endpointExpiryStore, retention, interval time.Duration) {
	ticker := time.NewTicker(interval)
	defer ticker.Stop()
	for {
		expireEndpointRecords(ctx, logger, store, retention, time.Now())
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
func expireEndpointRecords(ctx context.Context, logger *slog.Logger, store endpointExpiryStore, retention time.Duration, now time.Time) {
	cutoff := now.Add(-retention)
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
}
