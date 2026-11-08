package client

import (
	"context"
	"net/url"
	"strconv"

	"topsailai_agent_cluster/internal/protocol"
)

// GetHistory reads bounded provider session history for one Endpoint.
//
// History is a live provider read, so this call always reaches the Endpoint and
// never returns a cached projection. The result is returned verbatim; the client
// does not interpret provider status words or re-derive resumability.
//
// A positive limit narrows the caller's view and is forwarded as a query
// parameter. Zero omits the parameter so the provider's own window applies, which
// keeps an unset limit from being indistinguishable from an explicit request.
func (c *APIClient) GetHistory(ctx context.Context, endpointID string, limit int) (protocol.HistoryResult, error) {
	var result protocol.HistoryResult
	path := "/api/v1/history?endpoint_id=" + url.QueryEscape(endpointID)
	if limit > 0 {
		path += "&limit=" + strconv.Itoa(limit)
	}
	err := c.get(ctx, path, &result)
	return result, err
}
