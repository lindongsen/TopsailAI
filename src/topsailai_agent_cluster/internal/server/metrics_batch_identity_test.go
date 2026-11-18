package server

import (
	"net/http"
	"strings"
	"testing"

	"topsailai_agent_cluster/internal/protocol"
)

// TestMetricsBatchReportsAClusterResourceIDAsACallerError proves the batch route
// classifies a rejected request identity the same way the single-session route
// does.
//
// The Endpoint refuses the request before any provider process starts and reports
// the caller-error code. Without a case for it here the code falls through to the
// provider default, so the operator is told a provider failed when the provider was
// never invoked, and the same mistake is described two different ways depending on
// which route carried it.
func TestMetricsBatchReportsAClusterResourceIDAsACallerError(t *testing.T) {
	stub := &metricsBatchRequesterStub{result: protocol.SessionMetricsBatch{
		ErrorCode: protocol.InvalidTarget,
	}}
	rec := metricsBatchCall(t, metricsHandler(stub), http.MethodPost,
		`{"endpoint_id":"e1","provider_session_ids":["res_0123456789abcdef0123456789abcdef"]}`, "test")
	if rec.Code != http.StatusBadRequest {
		t.Fatalf("status = %d, want %d, body = %s", rec.Code, http.StatusBadRequest, rec.Body.String())
	}
	body := rec.Body.String()
	if !strings.Contains(body, protocol.InvalidTarget) {
		t.Fatalf("body = %s, want code %q", body, protocol.InvalidTarget)
	}
	if strings.Contains(body, protocol.MetricsProviderError) {
		t.Fatalf("body = %s reports a provider failure for a request the provider never received", body)
	}
	if !strings.Contains(body, "provider session IDs") {
		t.Fatalf("body = %s does not say which identity the surface accepts", body)
	}
}

// TestMetricsBatchStillReportsAProviderFailureAsAProviderFailure proves the new
// case did not swallow the provider default.
//
// A mapping that answered every unknown code with the caller-error status would
// pass the test above while telling the operator to fix a request that was correct,
// so the neighbouring outcome needs its own assertion.
func TestMetricsBatchStillReportsAProviderFailureAsAProviderFailure(t *testing.T) {
	stub := &metricsBatchRequesterStub{result: protocol.SessionMetricsBatch{
		ErrorCode: protocol.MetricsProviderError,
	}}
	rec := metricsBatchCall(t, metricsHandler(stub), http.MethodPost,
		`{"endpoint_id":"e1","provider_session_ids":["session:stable"]}`, "test")
	if rec.Code != http.StatusBadGateway {
		t.Fatalf("status = %d, want %d, body = %s", rec.Code, http.StatusBadGateway, rec.Body.String())
	}
	if !strings.Contains(rec.Body.String(), protocol.MetricsProviderError) {
		t.Fatalf("body = %s, want code %q", rec.Body.String(), protocol.MetricsProviderError)
	}
}
