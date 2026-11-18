package server

import (
	"context"
	"net/http"
	"time"

	"topsailai_agent_cluster/internal/protocol"
)

// DetailRequester forwards a bounded session-record read to an Endpoint.
type DetailRequester interface {
	RequestDetail(context.Context, string, protocol.SessionDetailQuery) (protocol.SessionDetail, error)
}

// detail exposes authenticated bounded session-record reads.
//
// The record is provider state, so this route answers for a session that is no
// longer running. It is still a live provider read: the Server forwards the query
// and returns the adapter's answer unchanged, never caching it and never
// interpreting the provider document, because the document is provider detail and
// the Server must not learn one provider's record format.
func (h *Handler) detail(w http.ResponseWriter, r *http.Request) {
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
	requester, ok := h.Output.(DetailRequester)
	if !ok {
		h.writeError(w, 503, "unavailable", "detail query channel unavailable")
		return
	}
	ctx, cancel := context.WithTimeout(r.Context(), 10*time.Second)
	defer cancel()
	query := protocol.SessionDetailQuery{ProviderSessionID: sessionID}
	result, err := requester.RequestDetail(ctx, endpointID, query)
	if err != nil {
		h.writeDetailFailure(w, r, endpointID, err)
		return
	}
	if result.ErrorCode != "" {
		h.writeDetailResultFailure(w, r, endpointID, result)
		return
	}
	h.write(w, 200, 0, "success", result)
}

// writeDetailFailure separates an unknown endpoint identifier from a registered
// endpoint with no live connection, so a typo is not reported as an outage.
func (h *Handler) writeDetailFailure(w http.ResponseWriter, r *http.Request, endpointID string, err error) {
	if h.Store != nil {
		_, known, lookupErr := h.Store.GetEndpoint(r.Context(), endpointID)
		if lookupErr == nil && !known {
			h.writeError(w, http.StatusNotFound, "endpoint_not_found", "endpoint "+endpointID+" is not registered")
			return
		}
	}
	h.writeError(w, 503, "endpoint_unavailable", "detail query failed: "+err.Error())
}

// writeDetailResultFailure maps an adapter-reported capability or provider
// failure to a stable machine code. An unsupported adapter is not an outage, and
// an oversized provider document is not a provider fault, so each outcome keeps
// its own status.
//
// A disconnected endpoint is reported by the channel as an error code with no Go
// error, so it must be classified here as well. Without this case it would fall
// through to the provider default and tell the operator to investigate a provider
// that was never reached.
func (h *Handler) writeDetailResultFailure(w http.ResponseWriter, r *http.Request, endpointID string, result protocol.SessionDetail) {
	switch result.ErrorCode {
	case protocol.DetailUnsupported:
		h.writeError(w, 501, protocol.DetailUnsupported, "endpoint has no detail-capable adapter")
	case protocol.DetailSessionNotFound:
		h.writeError(w, 404, protocol.DetailSessionNotFound, "provider does not know session "+result.ProviderSessionID)
	case protocol.DetailResponseTooLarge:
		h.writeError(w, 502, protocol.DetailResponseTooLarge, "provider detail response exceeded the configured bound")
	case "endpoint_unavailable":
		h.writeError(w, 503, "endpoint_unavailable", "detail query failed: endpoint is not connected")
	case protocol.CredentialRejected:
		// The Endpoint could not authenticate the caller, so the policy was never
		// consulted. This is a credential problem, not a grant problem, so it must
		// not share the policy refusal's status or message.
		h.writeCredentialRejected(w, "detail.read")
	case protocol.PolicyDenied:
		// The Endpoint refused the caller, so this is not a provider failure and
		// not an outage. Reporting it as either would send the operator to
		// investigate a provider that was never invoked.
		h.writeError(w, http.StatusForbidden, protocol.PolicyDenied, "operation detail.read is not permitted for this endpoint token")
	case protocol.AdapterBusy:
		// The adapter had no capacity within the caller's budget, so the provider
		// was never invoked. This is transient and retryable, not a provider
		// fault, so it must not share the provider default.
		h.writeError(w, 503, protocol.AdapterBusy, "detail read was not attempted: adapter capacity was unavailable, retry")
	case protocol.InvalidTarget:
		// The caller named an identity this surface cannot accept, so the request
		// was refused before any provider process started. This is a caller error,
		// not a provider fault, so it must not share the provider default.
		h.writeError(w, http.StatusBadRequest, protocol.InvalidTarget, "session_id must be the provider session ID, not a cluster resource ID")
	default:
		h.writeError(w, 502, protocol.DetailProviderError, "provider detail read failed")
	}
}
