package server

import (
	"context"
	"net/http"
	"net/http/httptest"
	"testing"

	"topsailai_agent_cluster/internal/protocol"
	"topsailai_agent_cluster/internal/security"
)

type projectCatalogRequester struct {
	token string
	code  string
}

func (r *projectCatalogRequester) RequestOutput(context.Context, string, protocol.OutputSnapshotRequest) (protocol.OutputSnapshotResponse, error) {
	return protocol.OutputSnapshotResponse{}, nil
}

func (r *projectCatalogRequester) RequestProjectCatalog(ctx context.Context, endpointID string, _ protocol.ProjectCatalogQuery) (protocol.ProjectCatalog, error) {
	r.token = security.EndpointCredentialFrom(ctx).Token
	return protocol.ProjectCatalog{Projects: []protocol.Project{{ProjectID: "pr-1", Name: endpointID, Path: "/work/demo"}}, ObservedAtMS: 1, ErrorCode: r.code}, nil
}

// TestProjectCatalogHTTPClient verifies the real route, encoded endpoint and typed result.
func TestProjectCatalogHTTPClient(t *testing.T) {
	requester := &projectCatalogRequester{}
	h := &Handler{Authenticator: security.BearerAuthenticator{Token: "test"}, Output: requester}
	server := httptest.NewServer(h)
	defer server.Close()
	api := newBearerAPIClient(server.URL, "test")
	result, err := api.GetProjectCatalog(context.Background(), "e /1")
	if err != nil || len(result.Projects) != 1 || result.Projects[0].Name != "e /1" {
		t.Fatalf("result=%#v err=%v", result, err)
	}
	for _, item := range []struct {
		method string
		path   string
		token  string
		status int
	}{
		{http.MethodGet, "/api/v1/project-catalog?endpoint_id=e", "", http.StatusUnauthorized},
		{http.MethodPost, "/api/v1/project-catalog?endpoint_id=e", "test", http.StatusMethodNotAllowed},
		{http.MethodGet, "/api/v1/project-catalog", "test", http.StatusBadRequest},
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

// TestProjectCatalogForwardsEndpointToken proves Endpoint authority remains local.
func TestProjectCatalogForwardsEndpointToken(t *testing.T) {
	requester := &projectCatalogRequester{}
	h := &Handler{Authenticator: security.BearerAuthenticator{Token: "test"}, Output: requester}
	req := httptest.NewRequest(http.MethodGet, "/api/v1/project-catalog?endpoint_id=e", nil)
	req.Header.Set("Authorization", "Bearer test")
	req.Header.Set(endpointTokenHeader, "endpoint-secret")
	out := httptest.NewRecorder()
	h.ServeHTTP(out, req)
	if out.Code != http.StatusOK || requester.token != "endpoint-secret" {
		t.Fatalf("status=%d token=%q body=%s", out.Code, requester.token, out.Body.String())
	}
}

// TestProjectCatalogMapsEndpointRefusals preserves credential and policy boundaries.
func TestProjectCatalogMapsEndpointRefusals(t *testing.T) {
	for _, item := range []struct {
		code   string
		status int
	}{
		{protocol.ProjectCatalogUnsupported, http.StatusNotImplemented},
		{protocol.PolicyDenied, http.StatusForbidden},
		{protocol.CredentialRejected, http.StatusUnauthorized},
		{protocol.AdapterBusy, http.StatusServiceUnavailable},
	} {
		h := &Handler{Authenticator: security.BearerAuthenticator{Token: "test"}, Output: &projectCatalogRequester{code: item.code}}
		req := httptest.NewRequest(http.MethodGet, "/api/v1/project-catalog?endpoint_id=e", nil)
		req.Header.Set("Authorization", "Bearer test")
		out := httptest.NewRecorder()
		h.ServeHTTP(out, req)
		if out.Code != item.status {
			t.Fatalf("code=%s status=%d want=%d body=%s", item.code, out.Code, item.status, out.Body.String())
		}
	}
}
