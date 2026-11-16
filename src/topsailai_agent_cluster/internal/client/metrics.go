package client

import (
	"context"
	"net/url"

	"topsailai_agent_cluster/internal/protocol"
)

// GetMetrics reads one session's current message counts for one Endpoint.
//
// The counts are a live observation of a running session, so this call answers
// only while the provider can still measure the session. It is still a live
// provider read: the Server forwards the query and returns the adapter's answer
// verbatim, so the client never caches a result and never interprets a provider
// layer name.
//
// The target is the provider's own session identifier rather than a cluster
// resource ID, because a session with no live process is absent from the
// inventory and therefore has no cluster ID. The counts are read on demand for the
// rows an operator is about to see, so this call is never part of a list render
// that the operator did not ask for.
func (c *APIClient) GetMetrics(ctx context.Context, endpointID, sessionID string) (protocol.SessionMetrics, error) {
	var result protocol.SessionMetrics
	path := "/api/v1/metrics?endpoint_id=" + url.QueryEscape(endpointID) + "&session_id=" + url.QueryEscape(sessionID)
	err := c.get(c.withEndpointToken(ctx, endpointID), path, &result)
	return result, c.explainRefusal(err, endpointID)
}
