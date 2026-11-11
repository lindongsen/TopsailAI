package endpoint

import (
	"context"
	"time"

	"topsailai_agent_cluster/internal/adapter"
	"topsailai_agent_cluster/internal/channel"
	"topsailai_agent_cluster/internal/protocol"
)

// historyBudget bounds one provider history read. It matches the launch query
// budget, because both are bounded read-only provider calls on the same channel.
const historyBudget = 10 * time.Second

// History queries provider session history through the configured adapter.
//
// History is a live read, not a persisted projection, so it is served by the
// adapter that can answer it rather than from the stored inventory. An Endpoint
// with no history-capable adapter reports the capability as absent instead of
// returning an empty list, because an empty list would read as "this Endpoint has
// no history", which is a different claim from "this adapter cannot answer".
func (e *Executor) History(ctx context.Context, query protocol.HistoryQuery) (protocol.HistoryResult, error) {
	for _, instance := range e.registry.All() {
		handler, ok := instance.(adapter.HistoryHandler)
		if !ok {
			continue
		}
		result, err := handler.History(ctx, query)
		if err != nil {
			if result.ErrorCode == "" {
				result.ErrorCode = protocol.HistoryProviderError
			}
			return result, err
		}
		return result, nil
	}
	return protocol.HistoryResult{ErrorCode: protocol.HistoryUnsupported}, adapter.ErrUnsupported
}

// historyFrame answers one bounded read-only history query on the authenticated channel.
func (s *Service) historyFrame(ctx context.Context, frame channel.Frame) {
	// The policy check runs before the adapter is consulted, so a refused caller
	// cannot infer whether this Endpoint can read history at all.
	if err := s.permitOperation(frame, OperationHistoryRead); err != nil {
		result := protocol.HistoryResult{ErrorCode: s.refuseFrame(ctx, frame, OperationHistoryRead, err)}
		if sendErr := s.channel.SendFrame(ctx, channel.Frame{Type: channel.FrameHistoryResponse, ProtocolVersion: channel.ProtocolVersion, RequestID: frame.RequestID, HistoryResult: &result}); sendErr != nil {
			s.logError("publish history refusal", sendErr)
		}
		return
	}
	result := protocol.HistoryResult{ErrorCode: protocol.HistoryUnsupported}
	reader, ok := s.executor.(interface {
		History(context.Context, protocol.HistoryQuery) (protocol.HistoryResult, error)
	})
	if ok && frame.HistoryQuery != nil {
		queryCtx, cancel := context.WithTimeout(ctx, historyBudget)
		defer cancel()
		var err error
		result, err = reader.History(queryCtx, *frame.HistoryQuery)
		if err != nil {
			s.logError("query adapter history", err)
			if result.ErrorCode == "" {
				result.ErrorCode = protocol.HistoryProviderError
			}
		}
	}
	if err := s.channel.SendFrame(ctx, channel.Frame{Type: channel.FrameHistoryResponse, ProtocolVersion: channel.ProtocolVersion, RequestID: frame.RequestID, HistoryResult: &result}); err != nil {
		s.logError("publish history result", err)
	}
}
