package server

import (
	"context"
	"net/http"
	"time"

	"topsailai_agent_cluster/internal/protocol"
)

// ProjectCatalogRequester forwards a bounded live project read to an Endpoint.
type ProjectCatalogRequester interface {
	RequestProjectCatalog(context.Context, string, protocol.ProjectCatalogQuery) (protocol.ProjectCatalog, error)
}

func (h *Handler) projectCatalog(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodGet {
		h.writeError(w, http.StatusMethodNotAllowed, "method_not_allowed", "GET required")
		return
	}
	endpointID := r.URL.Query().Get("endpoint_id")
	if endpointID == "" {
		h.writeError(w, http.StatusBadRequest, "invalid_target", "endpoint_id is required")
		return
	}
	requester, ok := h.Output.(ProjectCatalogRequester)
	if !ok {
		h.writeError(w, http.StatusServiceUnavailable, "unavailable", "project catalog channel unavailable")
		return
	}
	ctx, cancel := context.WithTimeout(r.Context(), 10*time.Second)
	defer cancel()
	result, err := requester.RequestProjectCatalog(ctx, endpointID, protocol.ProjectCatalogQuery{})
	if err != nil {
		h.writeProjectCatalogFailure(w, r, endpointID, err)
		return
	}
	if result.ErrorCode != "" {
		h.writeProjectCatalogResultFailure(w, result)
		return
	}
	h.write(w, http.StatusOK, 0, "success", result)
}

func (h *Handler) writeProjectCatalogFailure(w http.ResponseWriter, r *http.Request, endpointID string, err error) {
	if h.Store != nil {
		_, known, lookupErr := h.Store.GetEndpoint(r.Context(), endpointID)
		if lookupErr == nil && !known {
			h.writeError(w, http.StatusNotFound, "endpoint_not_found", "endpoint "+endpointID+" is not registered")
			return
		}
	}
	h.writeError(w, http.StatusServiceUnavailable, "endpoint_unavailable", "project catalog query failed: "+err.Error())
}

func (h *Handler) writeProjectCatalogResultFailure(w http.ResponseWriter, result protocol.ProjectCatalog) {
	switch result.ErrorCode {
	case protocol.ProjectCatalogUnsupported:
		h.writeError(w, http.StatusNotImplemented, result.ErrorCode, "endpoint has no project-catalog-capable adapter")
	case protocol.ProjectCatalogTooLarge:
		h.writeError(w, http.StatusBadGateway, result.ErrorCode, "provider project catalog exceeded the configured bound")
	case "endpoint_unavailable":
		h.writeError(w, http.StatusServiceUnavailable, result.ErrorCode, "project catalog query failed: endpoint is not connected")
	case protocol.CredentialRejected:
		h.writeCredentialRejected(w, protocol.OperationProjectList)
	case protocol.PolicyDenied:
		h.writeError(w, http.StatusForbidden, result.ErrorCode, "operation project.list is not permitted for this endpoint token")
	case protocol.AdapterBusy:
		h.writeError(w, http.StatusServiceUnavailable, result.ErrorCode, "project catalog read was not attempted: adapter capacity was unavailable, retry")
	default:
		h.writeError(w, http.StatusBadGateway, protocol.ProjectCatalogProviderError, "provider project catalog read failed")
	}
}
