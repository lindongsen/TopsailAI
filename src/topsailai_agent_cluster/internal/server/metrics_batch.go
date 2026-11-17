package server

import (
	"context"
	"net/http"
	"time"

	"topsailai_agent_cluster/internal/protocol"
)

// MetricsBatchRequester forwards a bounded set read of message counts to one
// Endpoint.
type MetricsBatchRequester interface {
	RequestMetricsBatch(context.Context, string, protocol.SessionMetricsBatchQuery) (protocol.SessionMetricsBatch, error)
}

// metricsBatchRequest is the accepted body of the batch route.
//
// The Endpoint is named in the body rather than in the path because the set is
// scoped to one Endpoint: a set that spanned Endpoints would be several reads
// wearing one request, which is exactly the cost this route exists to remove.
type metricsBatchRequest struct {
	EndpointID         string   `json:"endpoint_id"`
	ProviderSessionIDs []string `json:"provider_session_ids"`
}

// metricsBatch exposes authenticated bounded set reads of message counts.
//
// It is a POST rather than a GET because the set is caller-supplied and can name
// many sessions, which does not fit a query string without an arbitrary length
// limit. It is still a read: the route changes no state, and the method is chosen
// for the request shape rather than for the effect.
//
// The answer is a partial success by design. A session the provider could not
// measure is absent from the result, and the caller renders it as unmeasured. A
// whole-request failure is reported through the envelope, so the two outcomes
// never share one shape.
func (h *Handler) metricsBatch(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		h.writeError(w, 405, "method_not_allowed", "POST required")
		return
	}
	var request metricsBatchRequest
	if err := decodeJSON(w, r, &request, 1<<20); err != nil {
		h.writeError(w, 400, "invalid_request", "invalid request body: "+err.Error())
		return
	}
	if request.EndpointID == "" {
		h.writeError(w, 400, "invalid_target", "endpoint_id required")
		return
	}
	if len(request.ProviderSessionIDs) == 0 {
		h.writeError(w, 400, "invalid_target", "provider_session_ids required")
		return
	}
	if len(request.ProviderSessionIDs) > protocol.MaxMetricsBatchSessions {
		h.writeError(w, 400, "invalid_target", "provider_session_ids exceeds the accepted bound")
		return
	}
	requester, ok := h.Output.(MetricsBatchRequester)
	if !ok {
		h.writeError(w, 503, "unavailable", "metrics batch query channel unavailable")
		return
	}
	ctx, cancel := context.WithTimeout(r.Context(), 10*time.Second)
	defer cancel()
	query := protocol.SessionMetricsBatchQuery{ProviderSessionIDs: request.ProviderSessionIDs}
	result, err := requester.RequestMetricsBatch(ctx, request.EndpointID, query)
	if err != nil {
		h.writeMetricsFailure(w, r, request.EndpointID, err)
		return
	}
	if result.ErrorCode != "" {
		h.writeMetricsBatchResultFailure(w, r, request.EndpointID, result)
		return
	}
	h.write(w, 200, 0, "success", result)
}

// writeMetricsBatchResultFailure maps a whole-request failure to a stable machine
// code.
//
// A member failure is not handled here, because a member failure is not a
// whole-request failure: the set succeeded and one member carries its own code.
// Classifying a member failure as a request failure would discard the members that
// were measured, which is the outcome this route exists to avoid.
func (h *Handler) writeMetricsBatchResultFailure(w http.ResponseWriter, r *http.Request, endpointID string, result protocol.SessionMetricsBatch) {
	switch result.ErrorCode {
	case protocol.MetricsUnsupported:
		h.writeError(w, 501, protocol.MetricsUnsupported, "endpoint has no batch metrics-capable adapter")
	case "endpoint_unavailable":
		h.writeError(w, 503, "endpoint_unavailable", "metrics batch query failed: endpoint is not connected")
	case protocol.PolicyDenied:
		h.writeError(w, http.StatusForbidden, protocol.PolicyDenied, "operation metrics.read is not permitted for this endpoint token")
	case protocol.AdapterBusy:
		h.writeError(w, 503, protocol.AdapterBusy, "metrics batch read was not attempted: adapter capacity was unavailable, retry")
	default:
		h.writeError(w, 502, protocol.MetricsProviderError, "provider metrics batch read failed")
	}
}
