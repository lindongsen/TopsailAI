package main

import (
	"context"
	"log/slog"
	"time"

	"topsailai_agent_cluster/internal/channel"
)

// endpointLivenessServer is the channel seam used by the liveness loop.
type endpointLivenessServer interface {
	ExpireStalePeers(time.Time) []channel.Peer
}

// runEndpointLiveness expires silent authoritative peers until cancellation.
func runEndpointLiveness(ctx context.Context, logger *slog.Logger, server endpointLivenessServer, heartbeatTimeout time.Duration) {
	runEndpointLivenessAtInterval(ctx, logger, server, endpointLivenessInterval(heartbeatTimeout))
}

// runEndpointLivenessAtInterval owns the recurring loop with an explicit cadence
// so periodic execution can be verified without waiting for a production tick.
func runEndpointLivenessAtInterval(ctx context.Context, logger *slog.Logger, server endpointLivenessServer, interval time.Duration) {
	ticker := time.NewTicker(interval)
	defer ticker.Stop()
	for {
		expireStaleEndpointPeers(logger, server, time.Now())
		select {
		case <-ctx.Done():
			return
		case <-ticker.C:
		}
	}
}

// endpointLivenessInterval bounds scans between one and five seconds. The scan
// remains responsive at the default 30-second timeout without busy polling when
// an unusually small timeout is configured in a test or embedding application.
func endpointLivenessInterval(heartbeatTimeout time.Duration) time.Duration {
	interval := heartbeatTimeout / 2
	if interval < time.Second {
		return time.Second
	}
	if interval > 5*time.Second {
		return 5 * time.Second
	}
	return interval
}

// expireStaleEndpointPeers executes one sweep and logs every connection closed.
func expireStaleEndpointPeers(logger *slog.Logger, server endpointLivenessServer, now time.Time) {
	for _, peer := range server.ExpireStalePeers(now) {
		logger.Warn("expired silent endpoint connection", "endpoint_id", peer.EndpointID, "instance_id", peer.InstanceID, "connection_generation", peer.ConnectionGeneration, "last_seen_at_ms", peer.LastSeen.UnixMilli())
	}
}
