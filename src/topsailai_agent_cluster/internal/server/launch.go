package server

import (
	"context"
	"net/http"
	"time"

	"topsailai_agent_cluster/internal/protocol"
)

// LaunchRequester forwards read-only queries to configured adapter handlers.
type LaunchRequester interface {
	RequestLaunchOptions(context.Context, string, protocol.LaunchQuery) (protocol.LaunchOptions, error)
}

// launchOptions exposes authenticated bounded project discovery, not arbitrary handlers.
func (h *Handler) launchOptions(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodGet {
		h.writeError(w, 405, "method_not_allowed", "GET required")
		return
	}
	endpointID := r.URL.Query().Get("endpoint_id")
	if endpointID == "" {
		h.writeError(w, 400, "invalid_target", "endpoint_id required")
		return
	}
	requester, ok := h.Output.(LaunchRequester)
	if !ok {
		h.writeError(w, 503, "unavailable", "launch query channel unavailable")
		return
	}
	ctx, cancel := context.WithTimeout(r.Context(), 10*time.Second)
	defer cancel()
	result, err := requester.RequestLaunchOptions(ctx, endpointID, protocol.LaunchQuery{AdapterID: r.URL.Query().Get("adapter_id")})
	if err != nil {
		h.writeLaunchFailure(w, r, endpointID, err)
		return
	}
	h.write(w, 200, 0, "success", result)
}

// writeLaunchFailure separates an unknown endpoint identifier from an endpoint
// that is registered but has no live connection. Both used to collapse into one
// availability error, so a typo looked like an infrastructure outage.
func (h *Handler) writeLaunchFailure(w http.ResponseWriter, r *http.Request, endpointID string, err error) {
	if h.Store != nil {
		_, known, lookupErr := h.Store.GetEndpoint(r.Context(), endpointID)
		if lookupErr == nil && !known {
			h.writeError(w, http.StatusNotFound, "endpoint_not_found", "endpoint "+endpointID+" is not registered")
			return
		}
	}
	h.writeError(w, 503, "endpoint_unavailable", "launch query failed: "+err.Error())
}
