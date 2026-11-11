package client

import (
	"context"
	"net/url"
	"topsailai_agent_cluster/internal/protocol"
)

// GetLaunchOptions queries the live endpoint catalog or one adapter project handler.
func (c *APIClient) GetLaunchOptions(ctx context.Context, endpointID, adapterID string) (protocol.LaunchOptions, error) {
	var result protocol.LaunchOptions
	err := c.get(c.withEndpointToken(ctx, endpointID), "/api/v1/launch-options?endpoint_id="+url.QueryEscape(endpointID)+"&adapter_id="+url.QueryEscape(adapterID), &result)
	return result, c.explainRefusal(err, endpointID)
}
