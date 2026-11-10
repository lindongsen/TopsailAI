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

type modelCatalogRequester struct{}

// RequestOutput preserves the existing constructor's output interface.
func (modelCatalogRequester) RequestOutput(context.Context, string, protocol.OutputSnapshotRequest) (protocol.OutputSnapshotResponse, error) {
	return protocol.OutputSnapshotResponse{}, nil
}

// RequestModelCatalog supplies a test catalog through the real HTTP/client
// boundary.
func (modelCatalogRequester) RequestModelCatalog(_ context.Context, endpoint string, query protocol.ModelCatalogQuery) (protocol.ModelCatalog, error) {
	return protocol.ModelCatalog{
		Profiles:         []protocol.ModelProfile{{ModelProfileID: "mp-1", DisplayName: endpoint, Available: true}},
		CurrentProfileID: "mp-1",
		ObservedAtMS:     1000,
	}, nil
}

// TestModelCatalogHTTPClient verifies auth, method validation and encoded
// selectors.
func TestModelCatalogHTTPClient(t *testing.T) {
	h := &Handler{Authenticator: security.BearerAuthenticator{Token: "test"}, Output: modelCatalogRequester{}}
	server := httptest.NewServer(h)
	defer server.Close()
	api := client.NewAPIClient(server.URL, "test")
	result, err := api.GetModelCatalog(context.Background(), "e /1", "s-1", "")
	if err != nil || len(result.Profiles) != 1 || result.Profiles[0].DisplayName != "e /1" {
		t.Fatalf("%#v %v", result, err)
	}
	for _, item := range []struct {
		method, path, token string
		status              int
	}{
		{http.MethodGet, "/api/v1/model-catalog?endpoint_id=e&resource_id=s", "", 401},
		{http.MethodPost, "/api/v1/model-catalog?endpoint_id=e&resource_id=s", "test", 405},
		{http.MethodGet, "/api/v1/model-catalog", "test", 400},
		{http.MethodGet, "/api/v1/model-catalog?endpoint_id=e", "test", 400},
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

// modelCatalogFailureRequester fails every catalog query, so the handler must
// classify it.
type modelCatalogFailureRequester struct{ modelCatalogRequester }

// RequestModelCatalog always fails, standing in for an offline endpoint.
func (modelCatalogFailureRequester) RequestModelCatalog(context.Context, string, protocol.ModelCatalogQuery) (protocol.ModelCatalog, error) {
	return protocol.ModelCatalog{}, errors.New("endpoint is offline")
}

// TestModelCatalogDistinguishesUnknownEndpointFromOffline proves a typo is not
// reported as an availability failure.
func TestModelCatalogDistinguishesUnknownEndpointFromOffline(t *testing.T) {
	store, err := serverstorage.Open(context.Background(), filepath.Join(t.TempDir(), "server.db"))
	if err != nil {
		t.Fatal(err)
	}
	defer store.Close()
	if err := store.UpsertEndpoint(context.Background(), protocol.Endpoint{EndpointID: "known", InstanceID: "known-1", DisplayName: "known", Hostname: "host-known", ConnectionState: "online", CapabilityRevision: "v1"}, 1000); err != nil {
		t.Fatal(err)
	}
	h := &Handler{Authenticator: security.BearerAuthenticator{Token: "test"}, Output: modelCatalogFailureRequester{}, Store: store}
	for _, item := range []struct {
		endpointID string
		status     int
		code       string
	}{
		{endpointID: "missing", status: http.StatusNotFound, code: "endpoint_not_found"},
		{endpointID: "known", status: http.StatusServiceUnavailable, code: "endpoint_unavailable"},
	} {
		req := httptest.NewRequest(http.MethodGet, "/api/v1/model-catalog?endpoint_id="+item.endpointID+"&resource_id=s", nil)
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

// modelCatalogCodeRequester returns one adapter-reported failure code unchanged.
type modelCatalogCodeRequester struct {
	modelCatalogRequester
	code string
}

// RequestModelCatalog returns the configured adapter failure code.
func (r modelCatalogCodeRequester) RequestModelCatalog(context.Context, string, protocol.ModelCatalogQuery) (protocol.ModelCatalog, error) {
	return protocol.ModelCatalog{ErrorCode: r.code}, nil
}

// TestModelCatalogAdapterFailureCodes proves an unsupported adapter is not an
// outage and a provider failure is not reported as a successful empty catalog.
func TestModelCatalogAdapterFailureCodes(t *testing.T) {
	for _, item := range []struct {
		code   string
		status int
	}{
		{code: protocol.ModelCatalogUnsupported, status: http.StatusNotImplemented},
		{code: protocol.ModelCatalogTooLarge, status: http.StatusBadGateway},
		{code: protocol.ModelCatalogProviderError, status: http.StatusBadGateway},
	} {
		h := &Handler{Authenticator: security.BearerAuthenticator{Token: "test"}, Output: modelCatalogCodeRequester{code: item.code}}
		req := httptest.NewRequest(http.MethodGet, "/api/v1/model-catalog?endpoint_id=e&resource_id=s", nil)
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

// TestModelCatalogEmptySuccessIsNotAnError proves a session with no selectable
// profile is a successful empty catalog, distinct from a capability or provider
// failure.
func TestModelCatalogEmptySuccessIsNotAnError(t *testing.T) {
	h := &Handler{Authenticator: security.BearerAuthenticator{Token: "test"}, Output: modelCatalogRequester{}}
	req := httptest.NewRequest(http.MethodGet, "/api/v1/model-catalog?endpoint_id=e&resource_id=s", nil)
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

// modelCatalogDisconnectRequester reproduces the real disconnect path: the channel
// reports a lost endpoint as an error code with no Go error, so the handler must
// classify the code rather than fall through to the provider default.
type modelCatalogDisconnectRequester struct{ modelCatalogRequester }

// RequestModelCatalog returns the channel's disconnect result unchanged.
func (modelCatalogDisconnectRequester) RequestModelCatalog(context.Context, string, protocol.ModelCatalogQuery) (protocol.ModelCatalog, error) {
	return protocol.ModelCatalog{ErrorCode: "endpoint_unavailable"}, nil
}

// TestModelCatalogDisconnectIsNotReportedAsProviderError proves a lost endpoint is
// an availability failure, never a provider failure.
func TestModelCatalogDisconnectIsNotReportedAsProviderError(t *testing.T) {
	h := &Handler{Authenticator: security.BearerAuthenticator{Token: "test"}, Output: modelCatalogDisconnectRequester{}}
	req := httptest.NewRequest(http.MethodGet, "/api/v1/model-catalog?endpoint_id=e&resource_id=s", nil)
	req.Header.Set("Authorization", "Bearer test")
	out := httptest.NewRecorder()
	h.ServeHTTP(out, req)
	if out.Code != http.StatusServiceUnavailable {
		t.Fatalf("status=%d want=%d body=%s", out.Code, http.StatusServiceUnavailable, out.Body.String())
	}
	if !strings.Contains(out.Body.String(), `"endpoint_unavailable"`) {
		t.Fatalf("body=%s want code endpoint_unavailable", out.Body.String())
	}
	if strings.Contains(out.Body.String(), `"`+protocol.ModelCatalogProviderError+`"`) {
		t.Fatalf("disconnect was reported as a provider failure: %s", out.Body.String())
	}
}

// TestModelCatalogRequiresViewScope proves catalog metadata is not reachable with
// any valid credential. A profile carries a display name and an availability
// verdict, so a credential narrowed to an unrelated scope must be refused before
// the transport is consulted.
func TestModelCatalogRequiresViewScope(t *testing.T) {
	for _, item := range []struct {
		name   string
		scopes security.ScopeSet
		status int
	}{
		{name: "unrestricted", scopes: security.ScopeSet{}, status: http.StatusOK},
		{name: "view", scopes: security.NewScopeSet(security.ScopeView), status: http.StatusOK},
		{name: "read_output only", scopes: security.NewScopeSet(security.ScopeReadOutput), status: http.StatusForbidden},
		{name: "send_message only", scopes: security.NewScopeSet(security.ScopeSendMessage), status: http.StatusForbidden},
	} {
		t.Run(item.name, func(t *testing.T) {
			h := &Handler{
				Authenticator: security.BearerAuthenticator{Token: "test", Scopes: item.scopes},
				Output:        modelCatalogRequester{},
			}
			req := httptest.NewRequest(http.MethodGet, "/api/v1/model-catalog?endpoint_id=e&resource_id=s", nil)
			req.Header.Set("Authorization", "Bearer test")
			out := httptest.NewRecorder()
			h.ServeHTTP(out, req)
			if out.Code != item.status {
				t.Fatalf("status=%d want=%d body=%s", out.Code, item.status, out.Body.String())
			}
			if item.status == http.StatusForbidden && !strings.Contains(out.Body.String(), `"permission_denied"`) {
				t.Fatalf("body=%s want code permission_denied", out.Body.String())
			}
		})
	}
}

// TestModelCatalogAuthorizationPrecedesTransport proves an unauthorized caller
// cannot infer Endpoint reachability. The handler is built without a catalog
// channel, so a missing check would answer 503 unavailable instead of 403.
func TestModelCatalogAuthorizationPrecedesTransport(t *testing.T) {
	h := &Handler{
		Authenticator: security.BearerAuthenticator{Token: "test", Scopes: security.NewScopeSet(security.ScopeSendMessage)},
	}
	req := httptest.NewRequest(http.MethodGet, "/api/v1/model-catalog?endpoint_id=e&resource_id=s", nil)
	req.Header.Set("Authorization", "Bearer test")
	out := httptest.NewRecorder()
	h.ServeHTTP(out, req)
	if out.Code != http.StatusForbidden {
		t.Fatalf("status=%d want=%d body=%s", out.Code, http.StatusForbidden, out.Body.String())
	}
}

// modelCatalogTargetRequester records the query the Server forwarded, so a test
// can prove the target was assembled at the boundary and passed down explicitly.
type modelCatalogTargetRequester struct {
	modelCatalogRequester
	queries []protocol.ModelCatalogQuery
}

// RequestModelCatalog records one forwarded query.
func (r *modelCatalogTargetRequester) RequestModelCatalog(_ context.Context, _ string, query protocol.ModelCatalogQuery) (protocol.ModelCatalog, error) {
	r.queries = append(r.queries, query)
	return protocol.ModelCatalog{Profiles: []protocol.ModelProfile{}, ObservedAtMS: 1000}, nil
}

// TestModelCatalogTargetReachesTheEndpoint proves the target travels from the HTTP
// query string to the forwarded protocol query, and that an omitted generation
// stays empty rather than being invented.
func TestModelCatalogTargetReachesTheEndpoint(t *testing.T) {
	requester := &modelCatalogTargetRequester{}
	h := &Handler{Authenticator: security.BearerAuthenticator{Token: "test"}, Output: requester}
	server := httptest.NewServer(h)
	defer server.Close()
	api := client.NewAPIClient(server.URL, "test")
	for _, item := range []struct {
		resourceID string
		generation string
	}{
		{"s-1", ""},
		{"s-2", "gen-7"},
	} {
		if _, err := api.GetModelCatalog(context.Background(), "ep-1", item.resourceID, item.generation); err != nil {
			t.Fatalf("%v", err)
		}
		query := requester.queries[len(requester.queries)-1]
		if query.Target.ResourceID != item.resourceID {
			t.Fatalf("resource=%q want=%q", query.Target.ResourceID, item.resourceID)
		}
		if query.Target.Generation != item.generation {
			t.Fatalf("generation=%q want=%q", query.Target.Generation, item.generation)
		}
		if query.Target.Kind != "session" {
			t.Fatalf("kind=%q want=session", query.Target.Kind)
		}
	}
}
