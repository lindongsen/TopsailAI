package endpoint

import (
	"context"
	"time"

	"topsailai_agent_cluster/internal/adapter"
	"topsailai_agent_cluster/internal/channel"
	"topsailai_agent_cluster/internal/protocol"
)

// messagesBudget bounds one provider conversation read. It matches the history
// budget, because both are bounded read-only provider calls on the same channel.
const messagesBudget = 10 * time.Second

// Messages reads one session's conversation through the configured adapter.
//
// Messages are persisted provider data, so this read works for a session that is
// not running. An Endpoint with no messages-capable adapter reports the capability
// as absent instead of returning an empty list, because an empty list would read as
// "this session recorded no messages", which is a different claim from "this
// adapter cannot answer".
func (e *Executor) Messages(ctx context.Context, query protocol.MessagesQuery) (protocol.MessagesResult, error) {
	for _, instance := range e.registry.All() {
		handler, ok := instance.(adapter.MessagesHandler)
		if !ok {
			continue
		}
		result, err := handler.Messages(ctx, query)
		if err != nil {
			if result.ErrorCode == "" {
				result.ErrorCode = protocol.MessagesProviderError
			}
			return result, err
		}
		return result, nil
	}
	return protocol.MessagesResult{ErrorCode: protocol.MessagesUnsupported}, adapter.ErrUnsupported
}

// messagesFrame answers one bounded read-only conversation query on the
// authenticated channel.
func (s *Service) messagesFrame(ctx context.Context, frame channel.Frame) {
	result := protocol.MessagesResult{ErrorCode: protocol.MessagesUnsupported}
	reader, ok := s.executor.(interface {
		Messages(context.Context, protocol.MessagesQuery) (protocol.MessagesResult, error)
	})
	if ok && frame.MessagesQuery != nil {
		queryCtx, cancel := context.WithTimeout(ctx, messagesBudget)
		defer cancel()
		var err error
		result, err = reader.Messages(queryCtx, *frame.MessagesQuery)
		if err != nil {
			s.logError("query adapter messages", err)
			if result.ErrorCode == "" {
				result.ErrorCode = protocol.MessagesProviderError
			}
		}
	}
	if err := s.channel.SendFrame(ctx, channel.Frame{Type: channel.FrameMessagesResponse, ProtocolVersion: channel.ProtocolVersion, RequestID: frame.RequestID, MessagesResult: &result}); err != nil {
		s.logError("publish messages result", err)
	}
}
