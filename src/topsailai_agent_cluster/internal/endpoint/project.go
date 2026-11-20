package endpoint

import (
	"context"
	"encoding/json"
	"errors"
	"sort"
	"time"

	"topsailai_agent_cluster/internal/adapter"
	"topsailai_agent_cluster/internal/channel"
	"topsailai_agent_cluster/internal/protocol"
)

const projectCatalogBudget = 10 * time.Second

// ProjectCatalog reads and combines the project catalogs of every capable Adapter.
func (e *Executor) ProjectCatalog(ctx context.Context, query protocol.ProjectCatalogQuery) (protocol.ProjectCatalog, error) {
	result := protocol.ProjectCatalog{Projects: []protocol.Project{}}
	instances, release := e.registry.AcquireAll()
	defer release()
	found := false
	for _, instance := range instances {
		handler, ok := instance.(adapter.ProjectCatalogHandler)
		if !ok {
			continue
		}
		catalog, err := handler.ProjectCatalog(ctx, query)
		if errors.Is(err, adapter.ErrUnsupported) {
			continue
		}
		found = true
		if err != nil {
			result.ErrorCode = readFailureCode(err, catalog.ErrorCode, protocol.ProjectCatalogProviderError)
			return result, err
		}
		if len(result.Projects)+len(catalog.Projects) > protocol.MaxProjects {
			result.Projects = []protocol.Project{}
			result.ErrorCode = protocol.ProjectCatalogTooLarge
			return result, errors.New("combined project catalog exceeds the project count bound")
		}
		result.Projects = append(result.Projects, catalog.Projects...)
		if catalog.ObservedAtMS > result.ObservedAtMS {
			result.ObservedAtMS = catalog.ObservedAtMS
		}
		result.Truncated = result.Truncated || catalog.Truncated
	}
	if !found {
		return protocol.ProjectCatalog{Projects: []protocol.Project{}, ErrorCode: protocol.ProjectCatalogUnsupported}, adapter.ErrUnsupported
	}
	encoded, err := json.Marshal(result)
	if err != nil {
		return protocol.ProjectCatalog{Projects: []protocol.Project{}, ErrorCode: protocol.ProjectCatalogProviderError}, err
	}
	if len(encoded) > protocol.MaxProjectBytes {
		return protocol.ProjectCatalog{Projects: []protocol.Project{}, ErrorCode: protocol.ProjectCatalogTooLarge}, errors.New("combined project catalog exceeds the project byte bound")
	}
	sort.Slice(result.Projects, func(i, j int) bool {
		if result.Projects[i].Name != result.Projects[j].Name {
			return result.Projects[i].Name < result.Projects[j].Name
		}
		if result.Projects[i].Path != result.Projects[j].Path {
			return result.Projects[i].Path < result.Projects[j].Path
		}
		return result.Projects[i].ProjectID < result.Projects[j].ProjectID
	})
	return result, nil
}

// projectCatalogFrame answers one bounded Endpoint-scoped project read.
func (s *Service) projectCatalogFrame(ctx context.Context, frame channel.Frame) {
	if err := s.permitOperation(frame, protocol.OperationProjectList); err != nil {
		result := protocol.ProjectCatalog{Projects: []protocol.Project{}, ErrorCode: s.refuseFrame(ctx, frame, protocol.OperationProjectList, err)}
		if sendErr := s.channel.SendFrame(ctx, channel.Frame{Type: channel.FrameProjectCatalogResponse, ProtocolVersion: channel.ProtocolVersion, RequestID: frame.RequestID, ProjectCatalog: &result}); sendErr != nil {
			s.logError("publish project catalog refusal", sendErr)
		}
		return
	}
	result := protocol.ProjectCatalog{Projects: []protocol.Project{}, ErrorCode: protocol.ProjectCatalogUnsupported}
	reader, ok := s.executor.(interface {
		ProjectCatalog(context.Context, protocol.ProjectCatalogQuery) (protocol.ProjectCatalog, error)
	})
	if ok && frame.ProjectCatalogQuery != nil {
		queryCtx, cancel := context.WithTimeout(ctx, projectCatalogBudget)
		defer cancel()
		var err error
		result, err = reader.ProjectCatalog(queryCtx, *frame.ProjectCatalogQuery)
		if err != nil {
			s.logError("query project catalog", err)
			if result.ErrorCode == "" {
				result.ErrorCode = protocol.ProjectCatalogProviderError
			}
		}
	}
	if err := s.channel.SendFrame(ctx, channel.Frame{Type: channel.FrameProjectCatalogResponse, ProtocolVersion: channel.ProtocolVersion, RequestID: frame.RequestID, ProjectCatalog: &result}); err != nil {
		s.logError("publish project catalog", err)
	}
}
