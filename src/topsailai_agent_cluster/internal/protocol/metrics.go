package protocol

// MessageCounts carries the two message counts one session reports.
//
// The two counts are named by their role in the conversation, never by a
// provider's own layer vocabulary. The cluster contract must not encode one
// provider's internal structure, because a second provider would report a
// different one and the contract would then have to change for it. Inbound
// counts the messages the operator sent to the agent; Outbound counts the
// messages the agent sent to the model. An adapter maps its provider's layers
// onto these two positions and documents that mapping in the adapter document.
//
// Both counts are provider-derived observations. A zero is a measured zero, and
// an unavailable observation is reported through ErrorCode instead, so a missing
// count is never presented as a count of zero.
type MessageCounts struct {
	Inbound  int `json:"inbound"`
	Outbound int `json:"outbound"`
}

// SessionMetrics carries the message counts of one session.
//
// The counts are a live observation, not a persisted projection: they describe
// how much context a running session currently holds, so they are read on demand
// and never collected into the inventory. A session whose process is gone has no
// counts to report, which is an unavailable observation rather than a zero.
type SessionMetrics struct {
	ProviderSessionID string        `json:"provider_session_id"`
	Messages          MessageCounts `json:"messages"`
	ObservedAtMS      int64         `json:"observed_at_ms"`
	ErrorCode         string        `json:"error_code,omitempty"`
}

// Standard metrics error codes.
const (
	// MetricsUnsupported means no configured adapter can read message counts.
	MetricsUnsupported = "metrics_unsupported"
	// MetricsSessionNotFound means the provider does not have this session.
	MetricsSessionNotFound = "session_not_found"
	// MetricsUnavailable means the session exists but no live process could
	// report its counts. It is distinct from a zero count, because a session
	// with no live process has no current context to measure.
	MetricsUnavailable = "metrics_unavailable"
	// MetricsProviderError means the provider call failed.
	MetricsProviderError = "provider_error"
)

// MaxMessageCount bounds one accepted message count. The bound exists so an
// absurd provider value is rejected instead of being rendered as a real count.
const MaxMessageCount = 10000000

// SessionMetricsQuery addresses one session whose message counts are wanted.
//
// The target is the provider's own session identifier, not a cluster resource ID,
// because a session with no live process is absent from the inventory and therefore
// has no cluster ID. The counts are read on demand for the rows an operator is about
// to see, so this query is never part of an inventory collection.
//
// The payload is closed: there is nothing to configure. A bound on the read would be
// meaningless, because the provider reports two integers rather than a document.
type SessionMetricsQuery struct {
	ProviderSessionID string `json:"provider_session_id"`
}
