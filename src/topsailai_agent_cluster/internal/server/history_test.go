package server

import (
	"context"
	"errors"
	"net/http"
	"net/http/httptest"
	"path/filepath"
	"strings"
	"testing"

	"topsailai_agent_cluster/internal/client"
	"topsailai_agent_cluster/internal/protocol"
	"topsailai_agent_cluster/internal/security"
	serverstorage "topsailai_agent_cluster/internal/storage/server"
)

type historyRequester struct{}

// RequestOutput preserves the existing constructor's output interface.
func (historyRequester) RequestOutput(context.Context, string, protocol.OutputSnapshotRequest) (protocol.OutputSnapshotResponse, error) {
	return protocol.OutputSnapshotResponse{}, nil
}

// RequestHistory supplies a test history response through the real HTTP/client boundary.
func (historyRequester) RequestHistory(_ context.Context, endpoint string, _ protocol.HistoryQuery) (protocol.HistoryResult, error) {
	return protocol.HistoryResult{Rows: []protocol.HistoryRow{{ProviderSessionID: "wa-1", DisplayName: endpoint, Resumable: true}}}, nil
}

// TestHistoryHTTPClient verifies auth, method validation and encoded selectors.
func TestHistoryHTTPClient(t *testing.T) {
	h := &Handler{Authenticator: security.BearerAuthenticator{Token: "test"}, Output: historyRequester{}}
	server := httptest.NewServer(h)
	defer server.Close()
	api := client.NewAPIClient(server.URL, "test")
	result, err := api.GetHistory(context.Background(), "e /1")
	if err != nil || len(result.Rows) != 1 || result.Rows[0].DisplayName != "e /1" {
		t.Fatalf("%#v %v", result, err)
	}
	for _, item := range []struct {
		method, path, token string
		status              int
	}{
		{http.MethodGet, "/api/v1/history?endpoint_id=e", "", 401},
		{http.MethodPost, "/api/v1/history?endpoint_id=e", "test", 405},
		{http.MethodGet, "/api/v1/history", "test", 400},
	} {
		req := httptest.NewRequest(item.method, item.path, nil)
		req.Header.Set("Authorization", "Bearer "+item.token)
		out := httptest.NewRecorder()
		h.ServeHTTP(out, req)
		if out.Code != item.status {
			t.Fatalf("%s %s status=%d want=%d body=%s", item.method, item.path, out.Code, item.status, out.Body.String())
		}
	}
}

// historyFailureRequester fails every history query, so the handler must classify it.
type historyFailureRequester struct{ historyRequester }

// RequestHistory always fails, standing in for an offline endpoint.
func (historyFailureRequester) RequestHistory(context.Context, string, protocol.HistoryQuery) (protocol.HistoryResult, error) {
	return protocol.HistoryResult{}, errors.New("endpoint is offline")
}

// TestHistoryDistinguishesUnknownEndpointFromOffline proves a typo is not
// reported as an availability failure.
func TestHistoryDistinguishesUnknownEndpointFromOffline(t *testing.T) {
	store, err := serverstorage.Open(context.Background(), filepath.Join(t.TempDir(), "server.db"))
	if err != nil {
		t.Fatal(err)
	}
	defer store.Close()
	if err := store.UpsertEndpoint(context.Background(), protocol.Endpoint{EndpointID: "known", InstanceID: "known-1", DisplayName: "known", Hostname: "host-known", ConnectionState: "online", CapabilityRevision: "v1"}, 1000); err != nil {
		t.Fatal(err)
	}
	h := &Handler{Authenticator: security.BearerAuthenticator{Token: "test"}, Output: historyFailureRequester{}, Store: store}
	for _, item := range []struct {
		endpointID string
		status     int
		code       string
	}{
		{endpointID: "missing", status: http.StatusNotFound, code: "endpoint_not_found"},
		{endpointID: "known", status: http.StatusServiceUnavailable, code: "endpoint_unavailable"},
	} {
		req := httptest.NewRequest(http.MethodGet, "/api/v1/history?endpoint_id="+item.endpointID, nil)
		req.Header.Set("Authorization", "Bearer test")
		out := httptest.NewRecorder()
		h.ServeHTTP(out, req)
		if out.Code != item.status {
			t.Fatalf("endpoint %q status=%d want=%d body=%s", item.endpointID, out.Code, item.status, out.Body.String())
		}
		if !strings.Contains(out.Body.String(), `"`+item.code+`"`) {
			t.Fatalf("endpoint %q body=%s want code %q", item.endpointID, out.Body.String(), item.code)
		}
	}
}

// historyCodeRequester returns one adapter-reported failure code unchanged.
type historyCodeRequester struct {
	historyRequester
	code string
}

// RequestHistory returns the configured adapter failure code.
func (r historyCodeRequester) RequestHistory(context.Context, string, protocol.HistoryQuery) (protocol.HistoryResult, error) {
	return protocol.HistoryResult{ErrorCode: r.code}, nil
}

// TestHistoryAdapterFailureCodes proves an unsupported adapter is not an outage
// and a provider failure is not reported as a successful empty history.
func TestHistoryAdapterFailureCodes(t *testing.T) {
	for _, item := range []struct {
		code   string
		status int
	}{
		{code: protocol.HistoryUnsupported, status: http.StatusNotImplemented},
		{code: protocol.HistoryResponseTooLarge, status: http.StatusBadGateway},
		{code: protocol.HistoryProviderError, status: http.StatusBadGateway},
	} {
		h := &Handler{Authenticator: security.BearerAuthenticator{Token: "test"}, Output: historyCodeRequester{code: item.code}}
		req := httptest.NewRequest(http.MethodGet, "/api/v1/history?endpoint_id=e", nil)
		req.Header.Set("Authorization", "Bearer test")
		out := httptest.NewRecorder()
		h.ServeHTTP(out, req)
		if out.Code != item.status {
			t.Fatalf("code %q status=%d want=%d body=%s", item.code, out.Code, item.status, out.Body.String())
		}
		if !strings.Contains(out.Body.String(), `"`+item.code+`"`) {
			t.Fatalf("code %q body=%s", item.code, out.Body.String())
		}
	}
}

// TestHistoryEmptySuccessIsNotAnError proves a provider with no history rows is
// a successful empty result, distinct from a capability or provider failure.
func TestHistoryEmptySuccessIsNotAnError(t *testing.T) {
	h := &Handler{Authenticator: security.BearerAuthenticator{Token: "test"}, Output: historyRequester{}}
	req := httptest.NewRequest(http.MethodGet, "/api/v1/history?endpoint_id=e", nil)
	req.Header.Set("Authorization", "Bearer test")
	out := httptest.NewRecorder()
	h.ServeHTTP(out, req)
	if out.Code != http.StatusOK {
		t.Fatalf("status=%d body=%s", out.Code, out.Body.String())
	}
	if strings.Contains(out.Body.String(), "error_code") {
		t.Fatalf("empty success carried an error: %s", out.Body.String())
	}
}

// historyDisconnectRequester reproduces the real disconnect path: the channel
// reports a lost endpoint as an error code with no Go error, so the handler must
// classify the code rather than fall through to the provider default.
type historyDisconnectRequester struct{ historyRequester }

// RequestHistory returns the channel's disconnect result unchanged.
func (historyDisconnectRequester) RequestHistory(context.Context, string, protocol.HistoryQuery) (protocol.HistoryResult, error) {
	return protocol.HistoryResult{ErrorCode: "endpoint_unavailable"}, nil
}

// TestHistoryDisconnectIsNotReportedAsProviderError proves a lost endpoint is an
// availability failure, never a provider failure. The channel signals a
// disconnect with an error code and a nil error, so this path is distinct from
// the transport-error path and must reach the same 503 outcome.
func TestHistoryDisconnectIsNotReportedAsProviderError(t *testing.T) {
	h := &Handler{Authenticator: security.BearerAuthenticator{Token: "test"}, Output: historyDisconnectRequester{}}
	req := httptest.NewRequest(http.MethodGet, "/api/v1/history?endpoint_id=e", nil)
	req.Header.Set("Authorization", "Bearer test")
	out := httptest.NewRecorder()
	h.ServeHTTP(out, req)
	if out.Code != http.StatusServiceUnavailable {
		t.Fatalf("status=%d want=%d body=%s", out.Code, http.StatusServiceUnavailable, out.Body.String())
	}
	if !strings.Contains(out.Body.String(), `"endpoint_unavailable"`) {
		t.Fatalf("body=%s want code endpoint_unavailable", out.Body.String())
	}
	if strings.Contains(out.Body.String(), `"`+protocol.HistoryProviderError+`"`) {
		t.Fatalf("disconnect was reported as a provider failure: %s", out.Body.String())
	}
}
