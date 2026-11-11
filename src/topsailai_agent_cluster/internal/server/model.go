package server

import (
	"context"
	"net/http"
	"time"

	"topsailai_agent_cluster/internal/protocol"
)

// ModelCatalogRequester forwards a bounded live model-catalog read to an Endpoint.
type ModelCatalogRequester interface {
	RequestModelCatalog(context.Context, string, protocol.ModelCatalogQuery) (protocol.ModelCatalog, error)
}

// modelCatalog exposes the model profiles a session can select.
//
// The read is a live provider query, so this route never serves a stored
// projection and never caches a result. The Server forwards the target verbatim and
// returns the adapter's answer unchanged: it does not interpret a profile name, a
// provider name or an availability verdict.
func (h *Handler) modelCatalog(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodGet {
		h.writeError(w, http.StatusMethodNotAllowed, "method_not_allowed", "GET required")
		return
	}
	q := r.URL.Query()
	endpointID, resourceID := q.Get("endpoint_id"), q.Get("resource_id")
	if endpointID == "" || resourceID == "" {
		h.writeError(w, http.StatusBadRequest, "invalid_target", "endpoint_id and resource_id are required")
		return
	}
	requester, ok := h.Output.(ModelCatalogRequester)
	if !ok {
		h.writeError(w, http.StatusServiceUnavailable, "unavailable", "model catalog channel unavailable")
		return
	}
	ctx, cancel := context.WithTimeout(r.Context(), 10*time.Second)
	defer cancel()
	// The target is assembled at the boundary and passed down as an explicit value,
	// so the transport layer never re-reads the request. A catalog read is
	// read-only, so the generation is forwarded as evidence but is not required.
	query := protocol.ModelCatalogQuery{Target: protocol.CommandTarget{Kind: "session", ResourceID: resourceID, ProviderGeneration: q.Get("provider_generation")}}
	result, err := requester.RequestModelCatalog(ctx, endpointID, query)
	if err != nil {
		h.writeModelCatalogFailure(w, r, endpointID, err)
		return
	}
	if result.ErrorCode != "" {
		h.writeModelCatalogResultFailure(w, r, endpointID, result)
		return
	}
	h.write(w, http.StatusOK, 0, "success", result)
}

// writeModelCatalogFailure separates an unknown endpoint identifier from a
// registered endpoint with no live connection, so a typo is not reported as an
// outage.
func (h *Handler) writeModelCatalogFailure(w http.ResponseWriter, r *http.Request, endpointID string, err error) {
	if h.Store != nil {
		_, known, lookupErr := h.Store.GetEndpoint(r.Context(), endpointID)
		if lookupErr == nil && !known {
			h.writeError(w, http.StatusNotFound, "endpoint_not_found", "endpoint "+endpointID+" is not registered")
			return
		}
	}
	h.writeError(w, http.StatusServiceUnavailable, "endpoint_unavailable", "model catalog query failed: "+err.Error())
}

// writeModelCatalogResultFailure maps an adapter-reported capability or provider
// failure to a stable machine code. An unsupported adapter is not an outage and an
// empty catalog is not an error, so each outcome keeps its own status.
func (h *Handler) writeModelCatalogResultFailure(w http.ResponseWriter, r *http.Request, endpointID string, result protocol.ModelCatalog) {
	switch result.ErrorCode {
	case protocol.ModelCatalogUnsupported:
		h.writeError(w, http.StatusNotImplemented, protocol.ModelCatalogUnsupported, "endpoint has no model-catalog-capable adapter")
	case protocol.ModelCatalogTooLarge:
		h.writeError(w, http.StatusBadGateway, protocol.ModelCatalogTooLarge, "provider model catalog exceeded the configured bound")
	case "endpoint_unavailable":
		h.writeError(w, http.StatusServiceUnavailable, "endpoint_unavailable", "model catalog query failed: endpoint is not connected")
	case protocol.PolicyDenied:
		// The Endpoint refused the caller, so this is not a provider failure and
		// not an outage. Reporting it as either would send the operator to
		// investigate a provider that was never invoked.
		h.writeError(w, http.StatusForbidden, protocol.PolicyDenied, "operation agent.model.list is not permitted for this endpoint token")
	default:
		h.writeError(w, http.StatusBadGateway, protocol.ModelCatalogProviderError, "provider model catalog read failed")
	}
}
