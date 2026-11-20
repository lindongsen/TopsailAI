package client

import (
	"context"
	"net/url"

	"topsailai_agent_cluster/internal/protocol"
)

// GetProjectCatalog reads the managed projects of one Endpoint.
func (c *APIClient) GetProjectCatalog(ctx context.Context, endpointID string) (protocol.ProjectCatalog, error) {
	var result protocol.ProjectCatalog
	path := "/api/v1/project-catalog?endpoint_id=" + url.QueryEscape(endpointID)
	err := c.get(c.withEndpointOperation(ctx, endpointID, protocol.OperationProjectList), path, &result)
	return result, c.explainRefusal(err, endpointID)
}
