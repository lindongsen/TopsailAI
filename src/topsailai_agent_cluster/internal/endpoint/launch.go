package endpoint

import (
	"context"
	"encoding/json"
	"sort"
	"time"

	"topsailai_agent_cluster/internal/adapter"
	"topsailai_agent_cluster/internal/channel"
	"topsailai_agent_cluster/internal/protocol"
)

// LaunchOptions queries only explicitly configured, start-capable adapter handlers.
func (e *Executor) LaunchOptions(ctx context.Context, query protocol.LaunchQuery) (protocol.LaunchOptions, error) {
	result := protocol.LaunchOptions{Handlers: []protocol.LaunchHandler{}, Projects: []protocol.Project{}}
	for _, instance := range e.registry.All() {
		descriptor, err := instance.Describe(ctx)
		if err != nil {
			return result, err
		}
		if query.AdapterID != "" && descriptor.AdapterID != query.AdapterID {
			continue
		}
		if !supports(descriptor.Capabilities, protocol.OperationAgentStart, "v1") {
			continue
		}
		handler, ok := instance.(adapter.ProjectHandler)
		if !ok {
			continue
		}
		result.Handlers = append(result.Handlers, protocol.LaunchHandler{AdapterID: descriptor.AdapterID, DisplayName: descriptor.DisplayName, Revision: descriptor.Capabilities.Revision})
		if query.AdapterID == "" {
			continue
		}
		projects, err := handler.Projects(ctx)
		if err != nil {
			result.ErrorCode = "project_query_failed"
			return result, err
		}
		data, err := json.Marshal(projects)
		if err != nil || len(data) > protocol.MaxProjectBytes || len(projects) > protocol.MaxProjects {
			result.ErrorCode = "project_response_too_large"
			return result, nil
		}
		result.Projects = projects
	}
	sort.Slice(result.Handlers, func(i, j int) bool { return result.Handlers[i].AdapterID < result.Handlers[j].AdapterID })
	if query.AdapterID != "" && len(result.Handlers) == 0 {
		result.ErrorCode = "unknown_launch_handler"
	}
	return result, nil
}

// launchFrame answers one bounded read-only launch query on the authenticated channel.
func (s *Service) launchFrame(ctx context.Context, frame channel.Frame) {
	result := protocol.LaunchOptions{ErrorCode: "unsupported"}
	reader, ok := s.executor.(interface {
		LaunchOptions(context.Context, protocol.LaunchQuery) (protocol.LaunchOptions, error)
	})
	if ok && frame.LaunchQuery != nil {
		queryCtx, cancel := context.WithTimeout(ctx, 10*time.Second)
		defer cancel()
		var err error
		result, err = reader.LaunchOptions(queryCtx, *frame.LaunchQuery)
		if err != nil {
			s.logError("query adapter projects", err)
			if result.ErrorCode == "" {
				result.ErrorCode = "provider_error"
			}
		}
	}
	if err := s.channel.SendFrame(ctx, channel.Frame{Type: channel.FrameLaunchResponse, ProtocolVersion: channel.ProtocolVersion, RequestID: frame.RequestID, LaunchOptions: &result}); err != nil {
		s.logError("publish launch options", err)
	}
}
