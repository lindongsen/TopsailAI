package client

import (
	"context"
	"net/url"

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
func (c *APIClient) GetModelCatalog(ctx context.Context, endpointID, resourceID, generation string) (protocol.ModelCatalog, error) {
	var result protocol.ModelCatalog
	path := "/api/v1/model-catalog?endpoint_id=" + url.QueryEscape(endpointID) + "&resource_id=" + url.QueryEscape(resourceID)
	if generation != "" {
		path += "&provider_generation=" + url.QueryEscape(generation)
	}
	err := c.get(ctx, path, &result)
	return result, err
}
