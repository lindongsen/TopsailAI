package client

import (
	"context"
	"net/url"

	"topsailai_agent_cluster/internal/protocol"
)

// GetModelRegistry reads the models one Endpoint offers to launches.
//
// It addresses the machine, so it takes no resource identifier and sends no target.
// The Endpoint token travels with the request because the Endpoint authorizes the
// read, exactly as it authorizes every other live provider read.
func (c *APIClient) GetModelRegistry(ctx context.Context, endpointID string) (protocol.ModelRegistry, error) {
	var result protocol.ModelRegistry
	path := "/api/v1/model-registry?endpoint_id=" + url.QueryEscape(endpointID)
	err := c.get(c.withEndpointOperation(ctx, endpointID, protocol.OperationAgentModelRegistry), path, &result)
	return result, c.explainRefusal(err, endpointID)
}
