package server

import (
	"context"
	"net/http"
	"time"

	"topsailai_agent_cluster/internal/protocol"
)

// MessagesRequester forwards a bounded provider conversation read to an Endpoint.
type MessagesRequester interface {
	RequestMessages(context.Context, string, protocol.MessagesQuery) (protocol.MessagesResult, error)
}

// messages exposes authenticated bounded provider conversation reads.
//
// Messages are persisted provider data, so this route answers for a session that
// is no longer running. It is still a live provider read: the Server forwards the
// query and returns the adapter's answer unchanged, never caching it and never
// correlating it with the inventory, because a stopped session is absent from the
// inventory and has no cluster resource ID.
func (h *Handler) messages(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodGet {
		h.writeError(w, 405, "method_not_allowed", "GET required")
		return
	}
	endpointID := r.URL.Query().Get("endpoint_id")
	if endpointID == "" {
		h.writeError(w, 400, "invalid_target", "endpoint_id required")
		return
	}
	sessionID := r.URL.Query().Get("session_id")
	if sessionID == "" {
		h.writeError(w, 400, "invalid_target", "session_id required")
		return
	}
	requester, ok := h.Output.(MessagesRequester)
	if !ok {
		h.writeError(w, 503, "unavailable", "messages query channel unavailable")
		return
	}
	ctx, cancel := context.WithTimeout(r.Context(), 10*time.Second)
	defer cancel()
	// The bound is parsed at the boundary and passed down as an explicit value, so
	// the transport never re-reads the request. An absent or invalid value keeps
	// the adapter's own default instead of silently narrowing it to zero.
	query := protocol.MessagesQuery{
		ProviderSessionID: sessionID,
		MaxChars:          parseInt(r.URL.Query().Get("max_chars"), 0),
		MaxTokens:         parseInt(r.URL.Query().Get("max_tokens"), 0),
	}
	result, err := requester.RequestMessages(ctx, endpointID, query)
	if err != nil {
		h.writeMessagesFailure(w, r, endpointID, err)
		return
	}
	if result.ErrorCode != "" {
		h.writeMessagesResultFailure(w, r, endpointID, result)
		return
	}
	h.write(w, 200, 0, "success", result)
}

// writeMessagesFailure separates an unknown endpoint identifier from a registered
// endpoint with no live connection, so a typo is not reported as an outage.
func (h *Handler) writeMessagesFailure(w http.ResponseWriter, r *http.Request, endpointID string, err error) {
	if h.Store != nil {
		_, known, lookupErr := h.Store.GetEndpoint(r.Context(), endpointID)
		if lookupErr == nil && !known {
			h.writeError(w, http.StatusNotFound, "endpoint_not_found", "endpoint "+endpointID+" is not registered")
			return
		}
	}
	h.writeError(w, 503, "endpoint_unavailable", "messages query failed: "+err.Error())
}

// writeMessagesResultFailure maps an adapter-reported capability or provider
// failure to a stable machine code. An unsupported adapter is not an outage, and
// an empty conversation is not an error, so each outcome keeps its own status.
//
// A disconnected endpoint is reported by the channel as an error code with no Go
// error, so it must be classified here as well. Without this case it would fall
// through to the provider default and tell the operator to investigate a provider
// that was never reached.
func (h *Handler) writeMessagesResultFailure(w http.ResponseWriter, r *http.Request, endpointID string, result protocol.MessagesResult) {
	switch result.ErrorCode {
	case protocol.MessagesUnsupported:
		h.writeError(w, 501, protocol.MessagesUnsupported, "endpoint has no messages-capable adapter")
	case protocol.MessagesSessionNotFound:
		h.writeError(w, 404, protocol.MessagesSessionNotFound, "provider does not know session "+result.ProviderSessionID)
	case protocol.MessagesResponseTooLarge:
		h.writeError(w, 502, protocol.MessagesResponseTooLarge, "provider messages response exceeded the configured bound")
	case "endpoint_unavailable":
		h.writeError(w, 503, "endpoint_unavailable", "messages query failed: endpoint is not connected")
	case protocol.PolicyDenied:
		// The Endpoint refused the caller, so this is not a provider failure and
		// not an outage. Reporting it as either would send the operator to
		// investigate a provider that was never invoked.
		h.writeError(w, http.StatusForbidden, protocol.PolicyDenied, "operation messages.read is not permitted for this endpoint token")
	default:
		h.writeError(w, 502, protocol.MessagesProviderError, "provider messages read failed")
	}
}
