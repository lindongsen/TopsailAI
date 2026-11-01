package server

import (
	"context"
	"net/http"
	"net/http/httptest"
	"path/filepath"
	"strings"
	"testing"

	"topsailai_agent_cluster/internal/security"
	serverstorage "topsailai_agent_cluster/internal/storage/server"
)

func TestHandlerErrorRoutesAndInvalidJSON(t *testing.T) {
	store, err := serverstorage.Open(context.Background(), filepath.Join(t.TempDir(), "server.db"))
	if err != nil {
		t.Fatal(err)
	}
	defer store.Close()
	h := &Handler{Store: store, Authenticator: security.BearerAuthenticator{Token: "secret"}, MaxBodyBytes: 32}
	call := func(method, path, body string) *httptest.ResponseRecorder {
		req := httptest.NewRequest(method, path, strings.NewReader(body))
		req.Header.Set("Authorization", "Bearer secret")
		rec := httptest.NewRecorder()
		h.ServeHTTP(rec, req)
		return rec
	}
	if got := call(http.MethodGet, "/api/v1/endpoints/nope", "").Code; got != http.StatusNotFound {
		t.Fatalf("malformed endpoint route status=%d", got)
	}
	if got := call(http.MethodPut, "/api/v1/endpoints", "{\"unknown\":1}").Code; got != http.StatusBadRequest {
		t.Fatalf("unknown field status=%d", got)
	}
	if got := call(http.MethodPut, "/api/v1/endpoints", "{}{}\n").Code; got != http.StatusBadRequest {
		t.Fatalf("multiple JSON status=%d", got)
	}
	if got := call(http.MethodPut, "/api/v1/endpoints", strings.Repeat("x", 64)).Code; got != http.StatusBadRequest {
		t.Fatalf("oversized body status=%d", got)
	}
	if got := call(http.MethodGet, "/api/v1/output", "").Code; got != http.StatusServiceUnavailable {
		t.Fatalf("output unavailable status=%d", got)
	}
}

func TestHandlerReadinessAndCommandServiceUnavailable(t *testing.T) {
	h := &Handler{Authenticator: security.BearerAuthenticator{Token: "secret"}}
	for _, tc := range []struct {
		method, path string
		want         int
	}{
		{http.MethodGet, "/readyz", http.StatusServiceUnavailable},
		{http.MethodGet, "/api/v1/commands", http.StatusServiceUnavailable},
		{http.MethodGet, "/api/v1/commands/x", http.StatusServiceUnavailable},
	} {
		req := httptest.NewRequest(tc.method, tc.path, nil)
		req.Header.Set("Authorization", "Bearer secret")
		rec := httptest.NewRecorder()
		h.ServeHTTP(rec, req)
		if rec.Code != tc.want {
			t.Fatalf("%s %s status=%d want=%d", tc.method, tc.path, rec.Code, tc.want)
		}
	}
}
