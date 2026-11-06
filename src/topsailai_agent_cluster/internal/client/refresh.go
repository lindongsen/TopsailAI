package client

import (
	"context"
	"net/url"

	"topsailai_agent_cluster/internal/protocol"
)

// RefreshInventory forces one fresh Endpoint collection and returns the committed report.
func (c *APIClient) RefreshInventory(ctx context.Context, endpointID string) (protocol.InventoryReport, error) {
	var result protocol.InventoryReport
	err := c.request(ctx, "POST", "/api/v1/endpoints/"+url.PathEscape(endpointID)+"/session-state/refresh", nil, &result)
	return result, err
}
