package endpoint

import (
	"context"
	"errors"
	"time"

	"topsailai_agent_cluster/internal/adapter"
	"topsailai_agent_cluster/internal/channel"
	"topsailai_agent_cluster/internal/protocol"
)

// modelRegistryBudget bounds one model-registry read. It matches the model-catalog
// budget, because both are bounded read-only provider calls on the same channel.
const modelRegistryBudget = 10 * time.Second

// ModelRegistry reads the models one Endpoint offers to launches.
//
// The read is a live provider query, not a persisted projection, so it is served by
// the adapter that can answer it rather than from the stored inventory. An Endpoint
// with no registry-capable adapter reports the capability as absent instead of
// returning an empty registry, because an empty registry would read as "this machine
// offers no model", which is a different claim from "this adapter cannot answer".
//
// Unlike ModelCatalog, this read is not addressed by a session, so it does not select
// an adapter by target. It asks every capable adapter and combines the answers, the
// same way ProjectCatalog does, because a machine may host several Adapter instances
// and each one contributes its own models. Combining is what makes the answer describe
// the machine rather than whichever adapter happened to be configured first.
func (e *Executor) ModelRegistry(ctx context.Context, query protocol.ModelRegistryQuery) (protocol.ModelRegistry, error) {
	result := protocol.ModelRegistry{Entries: []protocol.ModelRegistryEntry{}, CurrentSource: protocol.ModelSourceUnknown}
	instances, release := e.registry.AcquireAll()
	defer release()
	found := false
	for _, instance := range instances {
		handler, ok := instance.(adapter.ModelRegistryHandler)
		if !ok {
			continue
		}
		registry, err := handler.ModelRegistry(ctx, query)
		if errors.Is(err, adapter.ErrUnsupported) {
			continue
		}
		found = true
		if err != nil {
			result.ErrorCode = readFailureCode(err, registry.ErrorCode, protocol.ModelRegistryProviderError)
			return result, err
		}
		if len(result.Entries)+len(registry.Entries) > protocol.MaxModelRegistryEntries {
			result.Entries = []protocol.ModelRegistryEntry{}
			result.ErrorCode = protocol.ModelRegistryTooLarge
			return result, errors.New("combined model registry exceeds the entry count bound")
		}
		result.Entries = append(result.Entries, registry.Entries...)
		result.ProjectOverrides = append(result.ProjectOverrides, registry.ProjectOverrides...)
		if registry.ObservedAtMS > result.ObservedAtMS {
			result.ObservedAtMS = registry.ObservedAtMS
		}
		result.Truncated = result.Truncated || registry.Truncated
		// The current selection is a machine-level fact, so the first adapter that
		// reports one wins and a later adapter cannot overwrite it. Overwriting would
		// make the answer depend on configuration order, which is exactly the
		// ambiguity the Endpoint refuses elsewhere.
		if result.CurrentProfileID == "" && registry.CurrentProfileID != "" {
			result.CurrentProfileID = registry.CurrentProfileID
			result.CurrentSource = registry.CurrentSource
		}
	}
	if !found {
		return protocol.ModelRegistry{Entries: []protocol.ModelRegistryEntry{}, CurrentSource: protocol.ModelSourceUnknown, ErrorCode: protocol.ModelRegistryUnsupported}, adapter.ErrUnsupported
	}
	if err := protocol.ValidateModelRegistry(result); err != nil {
		result.Entries = []protocol.ModelRegistryEntry{}
		result.ErrorCode = protocol.ModelRegistryProviderError
		return result, err
	}
	return result, nil
}

// modelRegistryFrame answers one bounded Endpoint-scoped model-registry read.
func (s *Service) modelRegistryFrame(ctx context.Context, frame channel.Frame) {
	// The policy check runs before the adapter is consulted, so a refused caller
	// cannot infer whether this Endpoint can list models at all.
	if err := s.permitOperation(frame, protocol.OperationAgentModelRegistry); err != nil {
		result := protocol.ModelRegistry{Entries: []protocol.ModelRegistryEntry{}, CurrentSource: protocol.ModelSourceUnknown, ErrorCode: s.refuseFrame(ctx, frame, protocol.OperationAgentModelRegistry, err)}
		if sendErr := s.channel.SendFrame(ctx, channel.Frame{Type: channel.FrameModelRegistryResponse, ProtocolVersion: channel.ProtocolVersion, RequestID: frame.RequestID, ModelRegistry: &result}); sendErr != nil {
			s.logError("publish model registry refusal", sendErr)
		}
		return
	}
	result := protocol.ModelRegistry{Entries: []protocol.ModelRegistryEntry{}, CurrentSource: protocol.ModelSourceUnknown, ErrorCode: protocol.ModelRegistryUnsupported}
	reader, ok := s.executor.(interface {
		ModelRegistry(context.Context, protocol.ModelRegistryQuery) (protocol.ModelRegistry, error)
	})
	if ok && frame.ModelRegistryQuery != nil {
		queryCtx, cancel := context.WithTimeout(ctx, modelRegistryBudget)
		defer cancel()
		var err error
		result, err = reader.ModelRegistry(queryCtx, *frame.ModelRegistryQuery)
		if err != nil {
			s.logError("query adapter model registry", err)
			result.ErrorCode = readFailureCode(err, result.ErrorCode, protocol.ModelRegistryProviderError)
		}
	}
	if err := s.channel.SendFrame(ctx, channel.Frame{Type: channel.FrameModelRegistryResponse, ProtocolVersion: channel.ProtocolVersion, RequestID: frame.RequestID, ModelRegistry: &result}); err != nil {
		s.logError("publish model registry result", err)
	}
}
