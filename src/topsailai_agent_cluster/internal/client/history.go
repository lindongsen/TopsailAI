package client

import (
	"context"
	"net/url"

	"topsailai_agent_cluster/internal/protocol"
)

// GetHistory reads bounded provider session history for one Endpoint.
//
// History is a live provider read, so this call always reaches the Endpoint and
// never returns a cached projection. The result is returned verbatim; the client
// does not interpret provider status words or re-derive resumability.
func (c *APIClient) GetHistory(ctx context.Context, endpointID string) (protocol.HistoryResult, error) {
	var result protocol.HistoryResult
	err := c.get(ctx, "/api/v1/history?endpoint_id="+url.QueryEscape(endpointID), &result)
	return result, err
}
