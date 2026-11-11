package endpoint

import (
	"context"
	"time"

	"topsailai_agent_cluster/internal/adapter"
	"topsailai_agent_cluster/internal/channel"
	"topsailai_agent_cluster/internal/protocol"
)

// modelCatalogBudget bounds one model-catalog read. It matches the history budget,
// because both are bounded read-only provider calls on the same channel.
const modelCatalogBudget = 10 * time.Second

// ModelCatalog reads the model profiles a session can select through the
// configured adapter.
//
// The read is a live provider query, not a persisted projection, so it is served by
// the adapter that can answer it rather than from the stored inventory. An Endpoint
// with no catalog-capable adapter reports the capability as absent instead of
// returning an empty catalog, because an empty catalog would read as "this session
// offers no selectable profile", which is a different claim from "this adapter
// cannot answer".
func (e *Executor) ModelCatalog(ctx context.Context, query protocol.ModelCatalogQuery) (protocol.ModelCatalog, error) {
	for _, instance := range e.registry.All() {
		handler, ok := instance.(adapter.ModelCatalogHandler)
		if !ok {
			continue
		}
		result, err := handler.ModelCatalog(ctx, query)
		if err != nil {
			if result.ErrorCode == "" {
				result.ErrorCode = protocol.ModelCatalogProviderError
			}
			return result, err
		}
		return result, nil
	}
	return protocol.ModelCatalog{ErrorCode: protocol.ModelCatalogUnsupported}, adapter.ErrUnsupported
}

// modelCatalogFrame answers one bounded read-only model-catalog query on the
// authenticated channel.
func (s *Service) modelCatalogFrame(ctx context.Context, frame channel.Frame) {
	// The policy check runs before the adapter is consulted, so a refused caller
	// cannot infer whether this Endpoint can list model profiles at all.
	if err := s.permitOperation(frame, protocol.OperationAgentModelList); err != nil {
		result := protocol.ModelCatalog{ErrorCode: s.refuseFrame(ctx, frame, protocol.OperationAgentModelList, err)}
		if sendErr := s.channel.SendFrame(ctx, channel.Frame{Type: channel.FrameModelCatalogResponse, ProtocolVersion: channel.ProtocolVersion, RequestID: frame.RequestID, ModelCatalog: &result}); sendErr != nil {
			s.logError("publish model catalog refusal", sendErr)
		}
		return
	}
	result := protocol.ModelCatalog{ErrorCode: protocol.ModelCatalogUnsupported}
	reader, ok := s.executor.(interface {
		ModelCatalog(context.Context, protocol.ModelCatalogQuery) (protocol.ModelCatalog, error)
	})
	if ok && frame.ModelCatalogQuery != nil {
		queryCtx, cancel := context.WithTimeout(ctx, modelCatalogBudget)
		defer cancel()
		var err error
		result, err = reader.ModelCatalog(queryCtx, *frame.ModelCatalogQuery)
		if err != nil {
			s.logError("query adapter model catalog", err)
			if result.ErrorCode == "" {
				result.ErrorCode = protocol.ModelCatalogProviderError
			}
		}
	}
	if err := s.channel.SendFrame(ctx, channel.Frame{Type: channel.FrameModelCatalogResponse, ProtocolVersion: channel.ProtocolVersion, RequestID: frame.RequestID, ModelCatalog: &result}); err != nil {
		s.logError("publish model catalog result", err)
	}
}
