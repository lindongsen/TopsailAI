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

// MetricsBatchHandler optionally reads the current message counts of a bounded
// set of sessions in one call.
//
// It is a separate optional interface rather than a method on MetricsHandler,
// because the two capabilities have different costs and an adapter may honestly
// support one without the other. An adapter that can measure one session but
// cannot batch is still useful: the Endpoint falls back to the single-session
// read for every row, which is slower but correct. Requiring both would make such
// an adapter report no metrics capability at all, which would be a worse answer
// than a slow one.
//
// The set is the unit of the read. Reaching a provider costs a fixed amount that
// does not depend on how many sessions are asked about, so an adapter that can
// answer a set pays that cost once instead of once per member.
//
// A member the adapter could not measure is reported by its own error code, not
// by a zero count, for the same reason the single-session read does: a zero is a
// measured zero.
type MetricsBatchHandler interface {
	MetricsBatch(context.Context, protocol.SessionMetricsBatchQuery) (protocol.SessionMetricsBatch, error)
}
