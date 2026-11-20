package server

import (
	"context"
	"net/http"
	"time"

	"topsailai_agent_cluster/internal/protocol"
)

// ModelRegistryRequester forwards a bounded live model-registry read to an Endpoint.
type ModelRegistryRequester interface {
	RequestModelRegistry(context.Context, string, protocol.ModelRegistryQuery) (protocol.ModelRegistry, error)
}

// modelRegistry serves the models one Endpoint offers to launches.
//
// The route requires only endpoint_id. It deliberately does not accept a resource_id,
// because a registry describes the machine rather than one session: accepting a
// resource identifier would let a caller believe the answer was about that resource,
// and the Endpoint would have to ignore it. A caller that wants a session's catalog
// uses /api/v1/model-catalog, which is a different question with a different subject.
func (h *Handler) modelRegistry(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodGet {
		h.writeError(w, http.StatusMethodNotAllowed, "method_not_allowed", "GET required")
		return
	}
	endpointID := r.URL.Query().Get("endpoint_id")
	if endpointID == "" {
		h.writeError(w, http.StatusBadRequest, "invalid_target", "endpoint_id is required")
		return
	}
	requester, ok := h.Output.(ModelRegistryRequester)
	if !ok {
		h.writeError(w, http.StatusServiceUnavailable, "unavailable", "model registry channel unavailable")
		return
	}
	ctx, cancel := context.WithTimeout(r.Context(), 10*time.Second)
	defer cancel()
	result, err := requester.RequestModelRegistry(ctx, endpointID, protocol.ModelRegistryQuery{})
	if err != nil {
		h.writeModelRegistryFailure(w, r, endpointID, err)
		return
	}
	if result.ErrorCode != "" {
		h.writeModelRegistryResultFailure(w, result)
		return
	}
	h.write(w, http.StatusOK, 0, "success", result)
}

// writeModelRegistryFailure separates an unknown endpoint identifier from a
// reachability failure, because a router that cannot tell "no such address" from
// "address unreachable" has not verified the address.
func (h *Handler) writeModelRegistryFailure(w http.ResponseWriter, r *http.Request, endpointID string, err error) {
	if h.Store != nil {
		_, known, lookupErr := h.Store.GetEndpoint(r.Context(), endpointID)
		if lookupErr == nil && !known {
			h.writeError(w, http.StatusNotFound, "endpoint_not_found", "endpoint "+endpointID+" is not registered")
			return
		}
	}
	h.writeError(w, http.StatusServiceUnavailable, "endpoint_unavailable", "model registry query failed: "+err.Error())
}

// writeModelRegistryResultFailure maps an adapter-reported capability or provider
// failure onto a stable HTTP status.
func (h *Handler) writeModelRegistryResultFailure(w http.ResponseWriter, result protocol.ModelRegistry) {
	switch result.ErrorCode {
	case protocol.ModelRegistryUnsupported:
		h.writeError(w, http.StatusNotImplemented, result.ErrorCode, "endpoint has no model-registry-capable adapter")
	case protocol.ModelRegistryTooLarge:
		h.writeError(w, http.StatusBadGateway, result.ErrorCode, "provider model registry exceeded the configured bound")
	case protocol.ModelRegistrySelectionInvalid:
		h.writeError(w, http.StatusConflict, result.ErrorCode, "the endpoint holds a model selection that cannot be resolved")
	case "endpoint_unavailable":
		h.writeError(w, http.StatusServiceUnavailable, result.ErrorCode, "model registry query failed: endpoint is not connected")
	case protocol.CredentialRejected:
		h.writeCredentialRejected(w, protocol.OperationAgentModelRegistry)
	case protocol.PolicyDenied:
		h.writeError(w, http.StatusForbidden, result.ErrorCode, "operation agent.model.registry is not permitted for this endpoint token")
	case protocol.AdapterBusy:
		h.writeError(w, http.StatusServiceUnavailable, result.ErrorCode, "model registry read was not attempted: adapter capacity was unavailable, retry")
	default:
		h.writeError(w, http.StatusBadGateway, protocol.ModelRegistryProviderError, "provider model registry read failed")
	}
}
