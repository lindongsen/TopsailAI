package adapter

import (
	"context"

	"topsailai_agent_cluster/internal/protocol"
)

// MetricsHandler optionally reads one session's current message counts.
//
// It mirrors MessagesHandler: an adapter that cannot measure a session simply does
// not implement it, and the Endpoint reports the capability as absent rather than
// returning zero counts. A zero count is a measured zero, so returning one for an
// adapter that cannot measure would state a fact the adapter never observed.
//
// The counts are a live observation, not persisted provider data. They describe how
// much context a session currently holds, so a session whose process is gone has no
// counts to report. That is an unavailable observation, which is why the result
// carries its own error code instead of a zero value.
//
// The adapter owns the mapping from its provider's own layer vocabulary onto the
// cluster's two positions, because it is the only layer that knows how the provider
// names them. The cluster never learns a provider layer name, and the Server never
// interprets one.
type MetricsHandler interface {
	Metrics(context.Context, protocol.SessionMetricsQuery) (protocol.SessionMetrics, error)
}
