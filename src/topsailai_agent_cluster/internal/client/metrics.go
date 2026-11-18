package client

import (
	"context"
	"net/http"
	"net/url"

	"topsailai_agent_cluster/internal/protocol"
)

// GetMetrics reads one session's current message counts for one Endpoint.
//
// The counts are a live observation of a running session, so this call answers
// only while the provider can still measure the session. It is a live provider
// read: the Server forwards the query and returns the adapter's answer verbatim,
// so the client never caches a result and never interprets a provider layer name.
//
// The target is the provider's own session identifier rather than a cluster
// resource ID, because a session with no live process is absent from the
// inventory and therefore has no cluster ID.
//
// This is an explicit on-demand read, never a rendering dependency. A table
// render shows the counts the Endpoint reported in the periodic inventory, so no
// render path calls this method. Reach for it when an operator asks for current
// counts, which is a different question from what the last report observed.
func (c *APIClient) GetMetrics(ctx context.Context, endpointID, sessionID string) (protocol.SessionMetrics, error) {
	var result protocol.SessionMetrics
	path := "/api/v1/metrics?endpoint_id=" + url.QueryEscape(endpointID) + "&session_id=" + url.QueryEscape(sessionID)
	err := c.get(c.withEndpointOperation(ctx, endpointID, protocol.OperationMetricsRead), path, &result)
	return result, c.explainRefusal(err, endpointID)
}

// GetMetricsBatch reads the current message counts of a bounded set of sessions
// on one Endpoint in a single call.
//
// The set is the unit of the read because reaching a provider costs a fixed
// amount that does not depend on how many sessions are asked about, so asking
// about many sessions costs one round trip instead of one per session.
//
// Like GetMetrics this is an explicit on-demand read, never a rendering
// dependency: a table render shows the counts the Endpoint reported in the
// periodic inventory.
//
// A session the provider could not measure is absent from the result rather than
// reported as zero, so a caller must treat absence as unmeasured. A member that is
// present with its own error code was asked about and could not be measured, which
// is a different fact from never being answered.
func (c *APIClient) GetMetricsBatch(ctx context.Context, endpointID string, sessionIDs []string) (protocol.SessionMetricsBatch, error) {
	var result protocol.SessionMetricsBatch
	if len(sessionIDs) == 0 {
		return result, nil
	}
	body := struct {
		EndpointID         string   `json:"endpoint_id"`
		ProviderSessionIDs []string `json:"provider_session_ids"`
	}{EndpointID: endpointID, ProviderSessionIDs: sessionIDs}
	err := c.request(c.withEndpointOperation(ctx, endpointID, protocol.OperationMetricsRead), http.MethodPost, "/api/v1/metrics/batch", body, &result)
	return result, c.explainRefusal(err, endpointID)
}
