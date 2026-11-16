package endpoint

import (
	"context"
	"time"

	"topsailai_agent_cluster/internal/adapter"
	"topsailai_agent_cluster/internal/channel"
	"topsailai_agent_cluster/internal/protocol"
)

// metricsBudget bounds one provider message-count read. It matches the messages
// budget, because both are bounded read-only provider calls on the same channel.
//
// The budget is deliberately the same rather than shorter. A count read looks
// cheaper than a conversation read, but it reaches the same provider control
// channel, so a provider that is slow to answer is slow for both. A shorter budget
// would make the count fail while the conversation succeeded, which would look
// like a defect in the count rather than a slow provider.
const metricsBudget = 10 * time.Second

// detailBudget bounds one provider session-record read. It matches the messages
// budget for the same reason.
const detailBudget = 10 * time.Second

// Metrics reads one session's current message counts through the configured
// adapter.
//
// The counts are a live observation of a running session, so a session whose
// process is gone has no counts to report. That is reported as an unavailable
// observation rather than as zero counts, because a zero is a measured zero and
// presenting an unmeasured session as empty would state a fact nobody observed.
//
// An Endpoint with no metrics-capable adapter reports the capability as absent
// instead of returning zero counts, for the same reason.
func (e *Executor) Metrics(ctx context.Context, query protocol.SessionMetricsQuery) (protocol.SessionMetrics, error) {
	instances, release := e.registry.AcquireAll()
	defer release()
	for _, instance := range instances {
		handler, ok := instance.(adapter.MetricsHandler)
		if !ok {
			continue
		}
		result, err := handler.Metrics(ctx, query)
		if err != nil {
			result.ErrorCode = readFailureCode(err, result.ErrorCode, protocol.MetricsProviderError)
			return result, err
		}
		return result, nil
	}
	return protocol.SessionMetrics{ErrorCode: protocol.MetricsUnsupported}, adapter.ErrUnsupported
}

// Detail reads one session's provider metadata and runtime document through the
// configured adapter.
//
// The metadata is the provider's own session record, forwarded verbatim. The
// runtime document is a seam and is empty until a source is chosen, so an empty
// value here means the provider reported none rather than that the read failed.
//
// An Endpoint with no detail-capable adapter reports the capability as absent
// instead of returning an empty document, because an empty document would read as
// "this provider keeps no record for the session", which is a different claim from
// "this adapter cannot answer".
func (e *Executor) Detail(ctx context.Context, query protocol.SessionDetailQuery) (protocol.SessionDetail, error) {
	instances, release := e.registry.AcquireAll()
	defer release()
	for _, instance := range instances {
		handler, ok := instance.(adapter.DetailHandler)
		if !ok {
			continue
		}
		result, err := handler.Detail(ctx, query)
		if err != nil {
			result.ErrorCode = readFailureCode(err, result.ErrorCode, protocol.DetailProviderError)
			return result, err
		}
		return result, nil
	}
	return protocol.SessionDetail{ErrorCode: protocol.DetailUnsupported}, adapter.ErrUnsupported
}

// metricsFrame answers one bounded read-only message-count query on the
// authenticated channel.
func (s *Service) metricsFrame(ctx context.Context, frame channel.Frame) {
	// The policy check runs before the adapter is consulted, so a refused caller
	// cannot infer whether this Endpoint can measure a session at all.
	if err := s.permitOperation(frame, OperationMetricsRead); err != nil {
		result := protocol.SessionMetrics{ErrorCode: s.refuseFrame(ctx, frame, OperationMetricsRead, err)}
		if sendErr := s.channel.SendFrame(ctx, channel.Frame{Type: channel.FrameMetricsResponse, ProtocolVersion: channel.ProtocolVersion, RequestID: frame.RequestID, MetricsResult: &result}); sendErr != nil {
			s.logError("publish metrics refusal", sendErr)
		}
		return
	}
	result := protocol.SessionMetrics{ErrorCode: protocol.MetricsUnsupported}
	reader, ok := s.executor.(interface {
		Metrics(context.Context, protocol.SessionMetricsQuery) (protocol.SessionMetrics, error)
	})
	if ok && frame.MetricsQuery != nil {
		queryCtx, cancel := context.WithTimeout(ctx, metricsBudget)
		defer cancel()
		var err error
		result, err = reader.Metrics(queryCtx, *frame.MetricsQuery)
		if err != nil {
			s.logError("query adapter metrics", err)
			result.ErrorCode = readFailureCode(err, result.ErrorCode, protocol.MetricsProviderError)
		}
	}
	if err := s.channel.SendFrame(ctx, channel.Frame{Type: channel.FrameMetricsResponse, ProtocolVersion: channel.ProtocolVersion, RequestID: frame.RequestID, MetricsResult: &result}); err != nil {
		s.logError("publish metrics result", err)
	}
}

// detailFrame answers one bounded read-only session-record query on the
// authenticated channel.
func (s *Service) detailFrame(ctx context.Context, frame channel.Frame) {
	// The policy check runs before the adapter is consulted, so a refused caller
	// cannot infer whether this Endpoint can read a session record at all.
	if err := s.permitOperation(frame, OperationDetailRead); err != nil {
		result := protocol.SessionDetail{ErrorCode: s.refuseFrame(ctx, frame, OperationDetailRead, err)}
		if sendErr := s.channel.SendFrame(ctx, channel.Frame{Type: channel.FrameDetailResponse, ProtocolVersion: channel.ProtocolVersion, RequestID: frame.RequestID, DetailResult: &result}); sendErr != nil {
			s.logError("publish detail refusal", sendErr)
		}
		return
	}
	result := protocol.SessionDetail{ErrorCode: protocol.DetailUnsupported}
	reader, ok := s.executor.(interface {
		Detail(context.Context, protocol.SessionDetailQuery) (protocol.SessionDetail, error)
	})
	if ok && frame.DetailQuery != nil {
		queryCtx, cancel := context.WithTimeout(ctx, detailBudget)
		defer cancel()
		var err error
		result, err = reader.Detail(queryCtx, *frame.DetailQuery)
		if err != nil {
			s.logError("query adapter detail", err)
			result.ErrorCode = readFailureCode(err, result.ErrorCode, protocol.DetailProviderError)
		}
	}
	if err := s.channel.SendFrame(ctx, channel.Frame{Type: channel.FrameDetailResponse, ProtocolVersion: channel.ProtocolVersion, RequestID: frame.RequestID, DetailResult: &result}); err != nil {
		s.logError("publish detail result", err)
	}
}
