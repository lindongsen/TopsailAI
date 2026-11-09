package server

import (
	"context"
	"net/http"
	"time"

	"topsailai_agent_cluster/internal/protocol"
)

// HistoryRequester forwards a bounded live provider history read to an Endpoint.
type HistoryRequester interface {
	RequestHistory(context.Context, string, protocol.HistoryQuery) (protocol.HistoryResult, error)
}

// history exposes authenticated bounded provider session history.
//
// History is a live provider read, so this route never serves a stored
// projection and never caches a result. The Server forwards the query verbatim
// and returns the adapter's answer unchanged: it does not interpret provider
// status words, re-derive resumability or correlate rows with the inventory.
//
// The authorization check runs before the transport is consulted, so an
// unauthorized caller cannot infer Endpoint reachability from the response.
func (h *Handler) history(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodGet {
		h.writeError(w, 405, "method_not_allowed", "GET required")
		return
	}
	if !h.authorizeHistoryRead(w, r) {
		return
	}
	endpointID := r.URL.Query().Get("endpoint_id")
	if endpointID == "" {
		h.writeError(w, 400, "invalid_target", "endpoint_id required")
		return
	}
	requester, ok := h.Output.(HistoryRequester)
	if !ok {
		h.writeError(w, 503, "unavailable", "history query channel unavailable")
		return
	}
	ctx, cancel := context.WithTimeout(r.Context(), 10*time.Second)
	defer cancel()
	// The limit is parsed at the boundary and passed down as an explicit value, so
	// the transport layer never re-reads the request. An absent or invalid value
	// keeps the provider's own window instead of silently narrowing it to zero.
	query := protocol.HistoryQuery{Limit: parseInt(r.URL.Query().Get("limit"), 0)}
	result, err := requester.RequestHistory(ctx, endpointID, query)
	if err != nil {
		h.writeHistoryFailure(w, r, endpointID, err)
		return
	}
	if result.ErrorCode != "" {
		h.writeHistoryResultFailure(w, r, endpointID, result)
		return
	}
	h.write(w, 200, 0, "success", result)
}

// writeHistoryFailure separates an unknown endpoint identifier from a registered
// endpoint with no live connection, so a typo is not reported as an outage.
func (h *Handler) writeHistoryFailure(w http.ResponseWriter, r *http.Request, endpointID string, err error) {
	if h.Store != nil {
		_, known, lookupErr := h.Store.GetEndpoint(r.Context(), endpointID)
		if lookupErr == nil && !known {
			h.writeError(w, http.StatusNotFound, "endpoint_not_found", "endpoint "+endpointID+" is not registered")
			return
		}
	}
	h.writeError(w, 503, "endpoint_unavailable", "history query failed: "+err.Error())
}

// writeHistoryResultFailure maps an adapter-reported capability or provider
// failure to a stable machine code. An unsupported adapter is not an outage and
// an empty history is not an error, so each outcome keeps its own status.
//
// A disconnected endpoint is reported by the channel as an error code with no
// Go error, so it must be classified here as well. Without this case it fell
// through to the provider default and told the operator to investigate a
// provider that was never reached.
func (h *Handler) writeHistoryResultFailure(w http.ResponseWriter, r *http.Request, endpointID string, result protocol.HistoryResult) {
	switch result.ErrorCode {
	case protocol.HistoryUnsupported:
		h.writeError(w, 501, protocol.HistoryUnsupported, "endpoint has no history-capable adapter")
	case protocol.HistoryResponseTooLarge:
		h.writeError(w, 502, protocol.HistoryResponseTooLarge, "provider history response exceeded the configured bound")
	case "endpoint_unavailable":
		h.writeError(w, 503, "endpoint_unavailable", "history query failed: endpoint is not connected")
	default:
		h.writeError(w, 502, protocol.HistoryProviderError, "provider history read failed")
	}
}
