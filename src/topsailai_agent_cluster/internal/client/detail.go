package client

import (
	"context"
	"net/url"

	"topsailai_agent_cluster/internal/protocol"
)

// GetDetail reads one session's provider metadata and runtime document for one
// Endpoint.
//
// The record is provider state, so this call answers for a session that is no
// longer running. It is still a live provider read: the Server forwards the query
// and returns the adapter's answer verbatim, so the client never caches a result
// and never interprets the provider document.
//
// The target is the provider's own session identifier rather than a cluster
// resource ID, because a session with no live process is absent from the
// inventory and therefore has no cluster ID, and detail is exactly the read an
// operator wants for such a session.
func (c *APIClient) GetDetail(ctx context.Context, endpointID, sessionID string) (protocol.SessionDetail, error) {
	var result protocol.SessionDetail
	path := "/api/v1/detail?endpoint_id=" + url.QueryEscape(endpointID) + "&session_id=" + url.QueryEscape(sessionID)
	err := c.get(c.withEndpointToken(ctx, endpointID), path, &result)
	return result, c.explainRefusal(err, endpointID)
}
