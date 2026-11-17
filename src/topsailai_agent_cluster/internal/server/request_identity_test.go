package server

import (
	"context"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"topsailai_agent_cluster/internal/protocol"
	"topsailai_agent_cluster/internal/security"
)

// invalidTargetMessagesRequester returns the caller-error code the Endpoint reports
// when a request named a Cluster resource ID where a provider session ID belongs.
type invalidTargetMessagesRequester struct{ messagesRequester }

// RequestMessages returns the rejected-identity result unchanged.
func (invalidTargetMessagesRequester) RequestMessages(context.Context, string, protocol.MessagesQuery) (protocol.MessagesResult, error) {
	return protocol.MessagesResult{ErrorCode: protocol.InvalidTarget, ProviderSessionID: "res_0123456789abcdef0123456789abcdef"}, nil
}

// TestMessagesRejectedIdentityIsACallerError proves a wrong identity is reported as
// a caller error rather than a provider failure.
//
// The caller supplied a Cluster resource ID where a provider session ID belongs, so
// the request was refused before any provider process started. Reporting it as a
// provider failure sends the operator to investigate a provider that was never
// invoked, and a script reading the exit status cannot tell the two apart.
func TestMessagesRejectedIdentityIsACallerError(t *testing.T) {
	h := &Handler{Authenticator: security.BearerAuthenticator{Token: "test"}, Output: invalidTargetMessagesRequester{}}
	req := httptest.NewRequest(http.MethodGet, "/api/v1/messages?endpoint_id=e&session_id=res_0123456789abcdef0123456789abcdef", nil)
	req.Header.Set("Authorization", "Bearer test")
	out := httptest.NewRecorder()
	h.ServeHTTP(out, req)
	if out.Code != http.StatusBadRequest {
		t.Fatalf("status=%d want=%d body=%s", out.Code, http.StatusBadRequest, out.Body.String())
	}
	if !strings.Contains(out.Body.String(), `"`+protocol.InvalidTarget+`"`) {
		t.Fatalf("body=%s want code %q", out.Body.String(), protocol.InvalidTarget)
	}
	if strings.Contains(out.Body.String(), `"`+protocol.MessagesProviderError+`"`) {
		t.Fatalf("a rejected identity was reported as a provider failure: %s", out.Body.String())
	}
}

// TestMessagesRejectedIdentityNamesTheRequiredIdentity proves the message tells the
// operator what to change.
//
// A caller error the caller cannot act on is only marginally better than a provider
// failure: the operator still has to guess which identity the command needs.
func TestMessagesRejectedIdentityNamesTheRequiredIdentity(t *testing.T) {
	h := &Handler{Authenticator: security.BearerAuthenticator{Token: "test"}, Output: invalidTargetMessagesRequester{}}
	req := httptest.NewRequest(http.MethodGet, "/api/v1/messages?endpoint_id=e&session_id=res_0123456789abcdef0123456789abcdef", nil)
	req.Header.Set("Authorization", "Bearer test")
	out := httptest.NewRecorder()
	h.ServeHTTP(out, req)
	body := out.Body.String()
	if !strings.Contains(body, "provider session ID") {
		t.Fatalf("body=%s does not name the identity the surface accepts", body)
	}
	if !strings.Contains(body, "cluster resource ID") {
		t.Fatalf("body=%s does not name the identity that was rejected", body)
	}
}

// invalidTargetDetailRequester returns the rejected-identity code for a detail read.
type invalidTargetDetailRequester struct{ messagesRequester }

// RequestDetail returns the rejected-identity result unchanged.
func (invalidTargetDetailRequester) RequestDetail(context.Context, string, protocol.SessionDetailQuery) (protocol.SessionDetail, error) {
	return protocol.SessionDetail{ErrorCode: protocol.InvalidTarget, ProviderSessionID: "res_0123456789abcdef0123456789abcdef"}, nil
}

// TestDetailRejectedIdentityIsACallerError proves the detail surface classifies the
// same fact identically.
//
// Every read surface that accepts a provider session ID can receive a Cluster
// resource ID, so a fix applied to one surface and not its siblings would leave the
// defect reachable through the others.
func TestDetailRejectedIdentityIsACallerError(t *testing.T) {
	h := &Handler{Authenticator: security.BearerAuthenticator{Token: "test"}, Output: invalidTargetDetailRequester{}}
	req := httptest.NewRequest(http.MethodGet, "/api/v1/detail?endpoint_id=e&session_id=res_0123456789abcdef0123456789abcdef", nil)
	req.Header.Set("Authorization", "Bearer test")
	out := httptest.NewRecorder()
	h.ServeHTTP(out, req)
	if out.Code != http.StatusBadRequest {
		t.Fatalf("status=%d want=%d body=%s", out.Code, http.StatusBadRequest, out.Body.String())
	}
	if !strings.Contains(out.Body.String(), `"`+protocol.InvalidTarget+`"`) {
		t.Fatalf("body=%s want code %q", out.Body.String(), protocol.InvalidTarget)
	}
	if strings.Contains(out.Body.String(), `"`+protocol.DetailProviderError+`"`) {
		t.Fatalf("a rejected identity was reported as a provider failure: %s", out.Body.String())
	}
}

// invalidTargetMetricsRequester returns the rejected-identity code for a metrics read.
type invalidTargetMetricsRequester struct{ messagesRequester }

// RequestMetrics returns the rejected-identity result unchanged.
func (invalidTargetMetricsRequester) RequestMetrics(context.Context, string, protocol.SessionMetricsQuery) (protocol.SessionMetrics, error) {
	return protocol.SessionMetrics{ErrorCode: protocol.InvalidTarget, ProviderSessionID: "res_0123456789abcdef0123456789abcdef"}, nil
}

// TestMetricsRejectedIdentityIsACallerError proves the metrics surface classifies the
// same fact identically.
func TestMetricsRejectedIdentityIsACallerError(t *testing.T) {
	h := &Handler{Authenticator: security.BearerAuthenticator{Token: "test"}, Output: invalidTargetMetricsRequester{}}
	req := httptest.NewRequest(http.MethodGet, "/api/v1/metrics?endpoint_id=e&session_id=res_0123456789abcdef0123456789abcdef", nil)
	req.Header.Set("Authorization", "Bearer test")
	out := httptest.NewRecorder()
	h.ServeHTTP(out, req)
	if out.Code != http.StatusBadRequest {
		t.Fatalf("status=%d want=%d body=%s", out.Code, http.StatusBadRequest, out.Body.String())
	}
	if !strings.Contains(out.Body.String(), `"`+protocol.InvalidTarget+`"`) {
		t.Fatalf("body=%s want code %q", out.Body.String(), protocol.InvalidTarget)
	}
	if strings.Contains(out.Body.String(), `"`+protocol.MetricsProviderError+`"`) {
		t.Fatalf("a rejected identity was reported as a provider failure: %s", out.Body.String())
	}
}
