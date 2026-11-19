package client

import (
	"context"
	"net/url"
	"strconv"

	"topsailai_agent_cluster/internal/protocol"
)

// GetModelCatalog reads the model profiles one session can select.
//
// The read is a live provider query, so this call always reaches the Endpoint and
// never returns a cached projection. The result is returned verbatim; the client
// does not interpret a profile name or re-derive availability.
//
// The generation is forwarded as evidence but is not required, because a catalog
// read changes nothing. Only a selection needs a live target.
func (c *APIClient) GetModelCatalog(ctx context.Context, endpointID string, query protocol.ModelCatalogQuery) (protocol.ModelCatalog, error) {
	var result protocol.ModelCatalog
	path := "/api/v1/model-catalog?endpoint_id=" + url.QueryEscape(endpointID) + "&resource_id=" + url.QueryEscape(query.Target.ResourceID)
	if query.Target.ProviderGeneration != "" {
		path += "&provider_generation=" + url.QueryEscape(query.Target.ProviderGeneration)
	}
	// The provider's own identity travels as query parameters because the Server
	// forwards it verbatim and never interprets it. Omitting an empty value keeps
	// the request unchanged for a caller that has no inventory row, so the adapter
	// resolves the target itself exactly as before.
	if query.ProviderSessionID != "" {
		path += "&provider_session_id=" + url.QueryEscape(query.ProviderSessionID)
	}
	if query.ProviderPID > 0 {
		path += "&provider_pid=" + url.QueryEscape(strconv.FormatInt(query.ProviderPID, 10))
	}
	err := c.get(c.withEndpointOperation(ctx, endpointID, protocol.OperationAgentModelList), path, &result)
	return result, c.explainRefusal(err, endpointID)
}
