// Package main provides unit tests for the HTTP API client.
package main

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"
)

func TestAPIClient_SendsSessionKeyHeader(t *testing.T) {
	var receivedHeader string
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		receivedHeader = r.Header.Get("X-Session-Key")
		json.NewEncoder(w).Encode(APIResponse{
			Data: mustJSON(map[string]interface{}{
				"account_id":   "acc-1",
				"account_name": "Alice",
				"role":         "user",
			}),
		})
	}))
	defer server.Close()

	client := NewAPIClient(server.URL)
	client.SetSessionKey("acc-1-test-session-key")

	resp, err := client.GetMe()
	if err != nil {
		t.Fatalf("GetMe error = %v", err)
	}

	if receivedHeader != "acc-1-test-session-key" {
		t.Errorf("X-Session-Key header = %q, want %q", receivedHeader, "acc-1-test-session-key")
	}

	var me map[string]interface{}
	if err := resp.GetData(&me); err != nil {
		t.Fatalf("GetData error = %v", err)
	}
	if me["account_id"] != "acc-1" {
		t.Errorf("account_id = %v, want acc-1", me["account_id"])
	}
}

func TestAPIClient_SendsAPIKeyHeader(t *testing.T) {
	var receivedHeader string
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		receivedHeader = r.Header.Get("Authorization")
		json.NewEncoder(w).Encode(APIResponse{
			Data: mustJSON(map[string]interface{}{
				"account_id":   "acc-1",
				"account_name": "Alice",
				"role":         "user",
			}),
		})
	}))
	defer server.Close()

	client := NewAPIClient(server.URL)
	client.SetAPIKey("ak-test.secret")

	_, err := client.GetMe()
	if err != nil {
		t.Fatalf("GetMe error = %v", err)
	}

	if receivedHeader != "Bearer ak-test.secret" {
		t.Errorf("Authorization header = %q, want %q", receivedHeader, "Bearer ak-test.secret")
	}
}

func TestAPIClient_NoAuthSendsNoAuthHeaders(t *testing.T) {
	var sessionHeader, authHeader string
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		sessionHeader = r.Header.Get("X-Session-Key")
		authHeader = r.Header.Get("Authorization")
		w.WriteHeader(http.StatusUnauthorized)
		json.NewEncoder(w).Encode(APIResponse{Error: "authentication required"})
	}))
	defer server.Close()

	client := NewAPIClient(server.URL)
	_, err := client.GetMe()
	if err == nil {
		t.Fatal("expected error for unauthenticated request")
	}

	if sessionHeader != "" {
		t.Errorf("X-Session-Key header = %q, want empty", sessionHeader)
	}
	if authHeader != "" {
		t.Errorf("Authorization header = %q, want empty", authHeader)
	}
}

func TestAPIClient_SetAuthMethod_Session(t *testing.T) {
	var receivedHeader string
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		receivedHeader = r.Header.Get("X-Session-Key")
		json.NewEncoder(w).Encode(APIResponse{
			Data: mustJSON(map[string]interface{}{"account_id": "acc-1"}),
		})
	}))
	defer server.Close()

	client := NewAPIClient(server.URL)
	client.SetAuthMethod(AuthMethodSession, "acc-1-via-set-auth-method")

	_, err := client.GetMe()
	if err != nil {
		t.Fatalf("GetMe error = %v", err)
	}

	if receivedHeader != "acc-1-via-set-auth-method" {
		t.Errorf("X-Session-Key header = %q, want %q", receivedHeader, "acc-1-via-set-auth-method")
	}
}

func TestAPIClient_SwitchFromAPIKeyToSession(t *testing.T) {
	var sessionHeader, authHeader string
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		sessionHeader = r.Header.Get("X-Session-Key")
		authHeader = r.Header.Get("Authorization")
		json.NewEncoder(w).Encode(APIResponse{
			Data: mustJSON(map[string]interface{}{"account_id": "acc-1"}),
		})
	}))
	defer server.Close()

	client := NewAPIClient(server.URL)
	client.SetAPIKey("ak-test.secret")
	client.SetSessionKey("acc-1-session")

	_, err := client.GetMe()
	if err != nil {
		t.Fatalf("GetMe error = %v", err)
	}

	if sessionHeader != "acc-1-session" {
		t.Errorf("X-Session-Key header = %q, want %q", sessionHeader, "acc-1-session")
	}
	if authHeader != "" {
		t.Errorf("Authorization header = %q, want empty after switching to session", authHeader)
	}
}
