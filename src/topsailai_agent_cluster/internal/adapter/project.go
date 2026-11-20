package adapter

import (
	"context"

	"topsailai_agent_cluster/internal/protocol"
)

// ProjectCatalogHandler optionally lists one Adapter instance's managed projects.
type ProjectCatalogHandler interface {
	ProjectCatalog(context.Context, protocol.ProjectCatalogQuery) (protocol.ProjectCatalog, error)
}
