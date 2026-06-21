// Package main provides unit tests for the HTTP API client.
package main

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"
)

func TestNewAPIClient(t *testing.T) {
	client := NewAPIClient("http://localhost:7370")
	if client == nil {
		t.Fatal("NewAPIClient() returned nil")
	}
	if client.baseURL != "http://localhost:7370" {
		t.Errorf("baseURL = %q, want %q", client.baseURL, "http://localhost:7370")
	}
	if client.client == nil {
		t.Error("http.Client is nil")
	}
}

func TestListQueryToQueryString(t *testing.T) {
	tests := []struct {
		name string
		q    ListQuery
		want string
	}{
		{
			name: "empty query",
			q:    ListQuery{},
			want: "",
		},
		{
			name: "offset only",
			q:    ListQuery{Offset: 10},
			want: "offset=10",
		},
		{
			name: "limit only",
			q:    ListQuery{Limit: 50},
			want: "limit=50",
		},
		{
			name: "sort and order",
			q:    ListQuery{SortKey: "create_at_ms", OrderBy: "desc"},
			want: "order_by=desc&sort_key=create_at_ms",
		},
		{
			name: "time range",
			q:    ListQuery{CreateAtMs: "1000-2000", UpdateAtMs: "3000-4000"},
			want: "create_at_ms=1000-2000&update_at_ms=3000-4000",
		},
		{
			name: "full query",
			q:    ListQuery{Offset: 10, Limit: 50, SortKey: "create_at_ms", OrderBy: "desc", CreateAtMs: "1000-2000"},
			want: "create_at_ms=1000-2000&limit=50&offset=10&order_by=desc&sort_key=create_at_ms",
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			got := tt.q.ToQueryString()
			if got != tt.want {
				t.Errorf("ToQueryString() = %q, want %q", got, tt.want)
			}
		})
	}
}

func TestAPIClientGet(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodGet {
			t.Errorf("expected GET, got %s", r.Method)
		}
		if r.URL.Path != "/api/v1/groups" {
			t.Errorf("expected path /api/v1/groups, got %s", r.URL.Path)
		}

		resp := APIResponse{
			Data:    json.RawMessage(`{"items":[{"group_id":"g1","group_name":"Test"}],"total":1}`),
			Error:   "",
			TraceID: "trace-123",
		}
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(http.StatusOK)
		json.NewEncoder(w).Encode(resp)
	}))
	defer server.Close()

	client := NewAPIClient(server.URL)
	resp, err := client.Get("/api/v1/groups")
	if err != nil {
		t.Fatalf("Get() error = %v", err)
	}
	if resp.TraceID != "trace-123" {
		t.Errorf("TraceID = %q, want %q", resp.TraceID, "trace-123")
	}

	var result struct {
		Items []map[string]interface{} `json:"items"`
		Total int                      `json:"total"`
	}
	if err := resp.GetData(&result); err != nil {
		t.Fatalf("GetData() error = %v", err)
	}
	if result.Total != 1 {
		t.Errorf("Total = %d, want 1", result.Total)
	}
	if len(result.Items) != 1 {
		t.Fatalf("Items length = %d, want 1", len(result.Items))
	}
	if result.Items[0]["group_id"] != "g1" {
		t.Errorf("group_id = %v, want g1", result.Items[0]["group_id"])
	}
}

func TestAPIClientPost(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodPost {
			t.Errorf("expected POST, got %s", r.Method)
		}
		if r.Header.Get("Content-Type") != "application/json" {
			t.Errorf("expected Content-Type application/json, got %s", r.Header.Get("Content-Type"))
		}

		var payload map[string]interface{}
		if err := json.NewDecoder(r.Body).Decode(&payload); err != nil {
			t.Fatalf("failed to decode body: %v", err)
		}
		if payload["group_name"] != "New Group" {
			t.Errorf("group_name = %v, want 'New Group'", payload["group_name"])
		}

		resp := APIResponse{
			Data:    json.RawMessage(`{"group_id":"g-new"}`),
			Error:   "",
			TraceID: "trace-456",
		}
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(http.StatusCreated)
		json.NewEncoder(w).Encode(resp)
	}))
	defer server.Close()

	client := NewAPIClient(server.URL)
	payload := map[string]interface{}{"group_name": "New Group"}
	resp, err := client.Post("/api/v1/groups", payload)
	if err != nil {
		t.Fatalf("Post() error = %v", err)
	}

	var result map[string]interface{}
	if err := resp.GetData(&result); err != nil {
		t.Fatalf("GetData() error = %v", err)
	}
	if result["group_id"] != "g-new" {
		t.Errorf("group_id = %v, want g-new", result["group_id"])
	}
}

func TestAPIClientPut(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodPut {
			t.Errorf("expected PUT, got %s", r.Method)
		}

		resp := APIResponse{
			Data:    json.RawMessage(`{"group_id":"g1"}`),
			Error:   "",
			TraceID: "trace-789",
		}
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(http.StatusOK)
		json.NewEncoder(w).Encode(resp)
	}))
	defer server.Close()

	client := NewAPIClient(server.URL)
	resp, err := client.Put("/api/v1/groups/g1", map[string]interface{}{"group_name": "Updated"})
	if err != nil {
		t.Fatalf("Put() error = %v", err)
	}
	if resp.TraceID != "trace-789" {
		t.Errorf("TraceID = %q, want %q", resp.TraceID, "trace-789")
	}
}

func TestAPIClientDelete(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodDelete {
			t.Errorf("expected DELETE, got %s", r.Method)
		}

		resp := APIResponse{
			Data:    nil,
			Error:   "",
			TraceID: "trace-del",
		}
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(http.StatusOK)
		json.NewEncoder(w).Encode(resp)
	}))
	defer server.Close()

	client := NewAPIClient(server.URL)
	resp, err := client.Delete("/api/v1/groups/g1")
	if err != nil {
		t.Fatalf("Delete() error = %v", err)
	}
	if resp.TraceID != "trace-del" {
		t.Errorf("TraceID = %q, want %q", resp.TraceID, "trace-del")
	}
}

func TestAPIClientErrorResponse(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		resp := APIResponse{
			Data:    nil,
			Error:   "group not found",
			TraceID: "trace-err",
		}
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(http.StatusNotFound)
		json.NewEncoder(w).Encode(resp)
	}))
	defer server.Close()

	client := NewAPIClient(server.URL)
	_, err := client.Get("/api/v1/groups/notfound")
	if err == nil {
		t.Fatal("expected error, got nil")
	}
	if err.Error() != "HTTP 404: group not found (trace_id: trace-err)" {
		t.Errorf("error = %q, want %q", err.Error(), "HTTP 404: group not found (trace_id: trace-err)")
	}
}

func TestAPIClientNonJSONResponse(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusInternalServerError)
		w.Write([]byte("internal server error"))
	}))
	defer server.Close()

	client := NewAPIClient(server.URL)
	_, err := client.Get("/api/v1/groups")
	if err == nil {
		t.Fatal("expected error, got nil")
	}
	expected := "HTTP 500: internal server error"
	if err.Error() != expected {
		t.Errorf("error = %q, want %q", err.Error(), expected)
	}
}

func TestAPIClientRawResponseWithoutEnvelope(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(http.StatusOK)
		json.NewEncoder(w).Encode(map[string]interface{}{
			"items": []map[string]interface{}{
				{"group_id": "g1", "group_name": "Group One"},
			},
			"total": 1,
		})
	}))
	defer server.Close()

	client := NewAPIClient(server.URL)
	resp, err := client.ListGroups(ListQuery{Limit: 10})
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}

	var result struct {
		Items []map[string]interface{} `json:"items"`
		Total int                      `json:"total"`
	}
	if err := resp.GetData(&result); err != nil {
		t.Fatalf("GetData() error = %v", err)
	}
	if len(result.Items) != 1 {
		t.Fatalf("expected 1 group, got %d", len(result.Items))
	}
	if result.Items[0]["group_id"] != "g1" {
		t.Errorf("group_id = %q, want %q", result.Items[0]["group_id"], "g1")
	}
	if result.Total != 1 {
		t.Errorf("total = %d, want %d", result.Total, 1)
	}
}

func TestAPIClientRawResponseWithoutEnvelopeMessages(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(http.StatusOK)
		json.NewEncoder(w).Encode(map[string]interface{}{
			"items": []map[string]interface{}{
				{"message_id": "m1", "message_text": "Hello", "sender_id": "u1", "sender_type": "user"},
			},
			"total": 1,
		})
	}))
	defer server.Close()

	client := NewAPIClient(server.URL)
	resp, err := client.ListMessages("g1", ListQuery{Limit: 10})
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}

	var result struct {
		Items []map[string]interface{} `json:"items"`
		Total int                      `json:"total"`
	}
	if err := resp.GetData(&result); err != nil {
		t.Fatalf("GetData() error = %v", err)
	}
	if len(result.Items) != 1 {
		t.Fatalf("expected 1 message, got %d", len(result.Items))
	}
	if result.Items[0]["message_id"] != "m1" {
		t.Errorf("message_id = %q, want %q", result.Items[0]["message_id"], "m1")
	}
	if result.Total != 1 {
		t.Errorf("total = %d, want %d", result.Total, 1)
	}
}

func TestAPIClientNetworkError(t *testing.T) {
	client := NewAPIClient("http://invalid-host-that-does-not-exist:99999")
	_, err := client.Get("/api/v1/groups")
	if err == nil {
		t.Fatal("expected error, got nil")
	}
}

func TestAPIResponseGetData(t *testing.T) {
	tests := []struct {
		name    string
		data    json.RawMessage
		target  interface{}
		wantErr bool
	}{
		{
			name:    "nil data",
			data:    nil,
			target:  &map[string]interface{}{},
			wantErr: false,
		},
		{
			name:    "valid json",
			data:    json.RawMessage(`{"key":"value"}`),
			target:  &map[string]interface{}{},
			wantErr: false,
		},
		{
			name:    "invalid json",
			data:    json.RawMessage(`{invalid`),
			target:  &map[string]interface{}{},
			wantErr: true,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			resp := &APIResponse{Data: tt.data}
			err := resp.GetData(tt.target)
			if (err != nil) != tt.wantErr {
				t.Errorf("GetData() error = %v, wantErr %v", err, tt.wantErr)
			}
		})
	}
}

func TestConvenienceMethods(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		resp := APIResponse{
			Data:    json.RawMessage(`{"success":true}`),
			Error:   "",
			TraceID: "trace-conv",
		}
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(http.StatusOK)
		json.NewEncoder(w).Encode(resp)
	}))
	defer server.Close()

	client := NewAPIClient(server.URL)

	t.Run("ListGroups", func(t *testing.T) {
		resp, err := client.ListGroups(ListQuery{Limit: 10})
		if err != nil {
			t.Fatalf("ListGroups() error = %v", err)
		}
		if resp.TraceID != "trace-conv" {
			t.Errorf("TraceID = %q, want %q", resp.TraceID, "trace-conv")
		}
	})

	t.Run("CreateGroup", func(t *testing.T) {
		resp, err := client.CreateGroup("Test", "Context", "key")
		if err != nil {
			t.Fatalf("CreateGroup() error = %v", err)
		}
		if resp.TraceID != "trace-conv" {
			t.Errorf("TraceID = %q, want %q", resp.TraceID, "trace-conv")
		}
	})

	t.Run("GetGroup", func(t *testing.T) {
		resp, err := client.GetGroup("g1")
		if err != nil {
			t.Fatalf("GetGroup() error = %v", err)
		}
		if resp.TraceID != "trace-conv" {
			t.Errorf("TraceID = %q, want %q", resp.TraceID, "trace-conv")
		}
	})

	t.Run("UpdateGroup", func(t *testing.T) {
		resp, err := client.UpdateGroup("g1", "Name", "Ctx", "Key")
		if err != nil {
			t.Fatalf("UpdateGroup() error = %v", err)
		}
		if resp.TraceID != "trace-conv" {
			t.Errorf("TraceID = %q, want %q", resp.TraceID, "trace-conv")
		}
	})

	t.Run("DeleteGroup", func(t *testing.T) {
		resp, err := client.DeleteGroup("g1")
		if err != nil {
			t.Fatalf("DeleteGroup() error = %v", err)
		}
		if resp.TraceID != "trace-conv" {
			t.Errorf("TraceID = %q, want %q", resp.TraceID, "trace-conv")
		}
	})

	t.Run("ListMembers", func(t *testing.T) {
		resp, err := client.ListMembers("g1", ListQuery{})
		if err != nil {
			t.Fatalf("ListMembers() error = %v", err)
		}
		if resp.TraceID != "trace-conv" {
			t.Errorf("TraceID = %q, want %q", resp.TraceID, "trace-conv")
		}
	})

	t.Run("AddMember", func(t *testing.T) {
		resp, err := client.AddMember("g1", "m1", "Alice", "Desc", "user", nil)
		if err != nil {
			t.Fatalf("AddMember() error = %v", err)
		}
		if resp.TraceID != "trace-conv" {
			t.Errorf("TraceID = %q, want %q", resp.TraceID, "trace-conv")
		}
	})

	t.Run("GetMember", func(t *testing.T) {
		resp, err := client.GetMember("g1", "m1")
		if err != nil {
			t.Fatalf("GetMember() error = %v", err)
		}
		if resp.TraceID != "trace-conv" {
			t.Errorf("TraceID = %q, want %q", resp.TraceID, "trace-conv")
		}
	})

	t.Run("UpdateMember", func(t *testing.T) {
		resp, err := client.UpdateMember("g1", "m1", "Alice", "Desc", "online", nil)
		if err != nil {
			t.Fatalf("UpdateMember() error = %v", err)
		}
		if resp.TraceID != "trace-conv" {
			t.Errorf("TraceID = %q, want %q", resp.TraceID, "trace-conv")
		}
	})

	t.Run("RemoveMember", func(t *testing.T) {
		resp, err := client.RemoveMember("g1", "m1")
		if err != nil {
			t.Fatalf("RemoveMember() error = %v", err)
		}
		if resp.TraceID != "trace-conv" {
			t.Errorf("TraceID = %q, want %q", resp.TraceID, "trace-conv")
		}
	})

	t.Run("ListMessages", func(t *testing.T) {
		resp, err := client.ListMessages("g1", ListQuery{})
		if err != nil {
			t.Fatalf("ListMessages() error = %v", err)
		}
		if resp.TraceID != "trace-conv" {
			t.Errorf("TraceID = %q, want %q", resp.TraceID, "trace-conv")
		}
	})

	t.Run("SendMessage", func(t *testing.T) {
		server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			if r.Method != http.MethodPost {
				t.Errorf("method = %q, want %q", r.Method, http.MethodPost)
			}
			var body map[string]interface{}
			if err := json.NewDecoder(r.Body).Decode(&body); err != nil {
				t.Fatalf("decode body: %v", err)
			}
			if _, ok := body["sender_id"]; ok {
				t.Errorf("body contains sender_id, want omitted")
			}
			if _, ok := body["sender_type"]; ok {
				t.Errorf("body contains sender_type, want omitted")
			}
			if got, want := body["message_text"], "Hello"; got != want {
				t.Errorf("message_text = %v, want %v", got, want)
			}
			resp := APIResponse{
				Data:    json.RawMessage(`{"success":true}`),
				Error:   "",
				TraceID: "trace-conv",
			}
			w.Header().Set("Content-Type", "application/json")
			w.WriteHeader(http.StatusOK)
			json.NewEncoder(w).Encode(resp)
		}))
		defer server.Close()

		client := NewAPIClient(server.URL)
		resp, err := client.SendMessage("g1", "Hello", nil)
		if err != nil {
			t.Fatalf("SendMessage() error = %v", err)
		}
		if resp.TraceID != "trace-conv" {
			t.Errorf("TraceID = %q, want %q", resp.TraceID, "trace-conv")
		}
	})

	t.Run("UpdateMessage", func(t *testing.T) {
		resp, err := client.UpdateMessage("g1", "msg1", "Updated text")
		if err != nil {
			t.Fatalf("UpdateMessage() error = %v", err)
		}
		if resp.TraceID != "trace-conv" {
			t.Errorf("TraceID = %q, want %q", resp.TraceID, "trace-conv")
		}
	})

	t.Run("DeleteMessage", func(t *testing.T) {
		resp, err := client.DeleteMessage("g1", "msg1")
		if err != nil {
			t.Fatalf("DeleteMessage() error = %v", err)
		}
		if resp.TraceID != "trace-conv" {
			t.Errorf("TraceID = %q, want %q", resp.TraceID, "trace-conv")
		}
	})
}

func TestCreateGroupWithEmptyKey(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		var payload map[string]interface{}
		json.NewDecoder(r.Body).Decode(&payload)
		if _, ok := payload["group_key"]; ok {
			t.Error("group_key should not be present when empty")
		}
		w.WriteHeader(http.StatusOK)
		json.NewEncoder(w).Encode(APIResponse{Data: json.RawMessage(`{}`)})
	}))
	defer server.Close()

	client := NewAPIClient(server.URL)
	_, err := client.CreateGroup("Test", "Ctx", "")
	if err != nil {
		t.Fatalf("CreateGroup() error = %v", err)
	}
}

func TestCreateGroupWithKey(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		var payload map[string]interface{}
		json.NewDecoder(r.Body).Decode(&payload)
		if payload["group_key"] != "secret" {
			t.Errorf("group_key = %v, want 'secret'", payload["group_key"])
		}
		w.WriteHeader(http.StatusOK)
		json.NewEncoder(w).Encode(APIResponse{Data: json.RawMessage(`{}`)})
	}))
	defer server.Close()

	client := NewAPIClient(server.URL)
	_, err := client.CreateGroup("Test", "Ctx", "secret")
	if err != nil {
		t.Fatalf("CreateGroup() error = %v", err)
	}
}

func TestUpdateGroupWithEmptyFields(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		var payload map[string]interface{}
		json.NewDecoder(r.Body).Decode(&payload)
		if len(payload) != 0 {
			t.Errorf("expected empty payload, got %v", payload)
		}
		w.WriteHeader(http.StatusOK)
		json.NewEncoder(w).Encode(APIResponse{Data: json.RawMessage(`{}`)})
	}))
	defer server.Close()

	client := NewAPIClient(server.URL)
	_, err := client.UpdateGroup("g1", "", "", "")
	if err != nil {
		t.Fatalf("UpdateGroup() error = %v", err)
	}
}

func TestListQueryURLPath(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.RawQuery != "limit=10&offset=5" {
			t.Errorf("query = %q, want %q", r.URL.RawQuery, "limit=10&offset=5")
		}
		w.WriteHeader(http.StatusOK)
		json.NewEncoder(w).Encode(APIResponse{Data: json.RawMessage(`{}`)})
	}))
	defer server.Close()

	client := NewAPIClient(server.URL)
	_, err := client.ListGroups(ListQuery{Offset: 5, Limit: 10})
	if err != nil {
		t.Fatalf("ListGroups() error = %v", err)
	}
}

func TestAPIClientServerURL(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusOK)
		json.NewEncoder(w).Encode(APIResponse{Data: json.RawMessage(`{}`)})
	}))
	defer server.Close()

	client := NewAPIClient(server.URL)
	_, err := client.Get("/test")
	if err != nil {
		t.Fatalf("Get() error = %v", err)
	}
}

func TestAPIClientAuthHeaders(t *testing.T) {
	tests := []struct {
		name           string
		setup          func(*APIClient)
		wantAuthHeader string
		wantValue      string
	}{
		{
			name: "api key auth",
			setup: func(c *APIClient) {
				c.SetAPIKey("ak-test.secret")
			},
			wantAuthHeader: "Authorization",
			wantValue:      "Bearer ak-test.secret",
		},
		{
			name: "session key auth",
			setup: func(c *APIClient) {
				c.SetSessionKey("acc-test-sessionkey")
			},
			wantAuthHeader: "X-Session-Key",
			wantValue:      "acc-test-sessionkey",
		},
		{
			name: "switch from api key to session",
			setup: func(c *APIClient) {
				c.SetAPIKey("ak-test.secret")
				c.SetSessionKey("acc-test-sessionkey")
			},
			wantAuthHeader: "X-Session-Key",
			wantValue:      "acc-test-sessionkey",
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			var gotValue string
			server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				gotValue = r.Header.Get(tt.wantAuthHeader)
				w.WriteHeader(http.StatusOK)
				json.NewEncoder(w).Encode(APIResponse{Data: json.RawMessage(`{}`)})
			}))
			defer server.Close()

			client := NewAPIClient(server.URL)
			tt.setup(client)
			_, err := client.Get("/api/v1/accounts/me")
			if err != nil {
				t.Fatalf("Get() error = %v", err)
			}
			if gotValue != tt.wantValue {
				t.Errorf("%s = %q, want %q", tt.wantAuthHeader, gotValue, tt.wantValue)
			}
		})
	}
}

func TestAPIClientSetAuthMethod(t *testing.T) {
	client := NewAPIClient("http://localhost")

	client.SetAuthMethod(AuthMethodAPIKey, "ak-test.secret")
	if client.AuthMethod() != AuthMethodAPIKey {
		t.Errorf("AuthMethod = %q, want %q", client.AuthMethod(), AuthMethodAPIKey)
	}
	if !client.IsAuthenticated() {
		t.Error("IsAuthenticated() = false, want true")
	}

	client.SetAuthMethod(AuthMethodSession, "session-key")
	if client.AuthMethod() != AuthMethodSession {
		t.Errorf("AuthMethod = %q, want %q", client.AuthMethod(), AuthMethodSession)
	}

	client.SetAuthMethod("unknown", "value")
	if client.IsAuthenticated() {
		t.Error("IsAuthenticated() = true after unknown method, want false")
	}
}

func TestAPIClientLogin(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodPost {
			t.Errorf("expected POST, got %s", r.Method)
		}
		if r.URL.Path != "/api/v1/accounts/login" {
			t.Errorf("expected path /api/v1/accounts/login, got %s", r.URL.Path)
		}

		var payload map[string]interface{}
		if err := json.NewDecoder(r.Body).Decode(&payload); err != nil {
			t.Fatalf("failed to decode body: %v", err)
		}
		if payload["login_name"] != "alice@example.com" {
			t.Errorf("login_name = %v, want 'alice@example.com'", payload["login_name"])
		}
		if payload["login_password"] != "secret" {
			t.Errorf("login_password = %v, want 'secret'", payload["login_password"])
		}

		resp := APIResponse{
			Data:    json.RawMessage(`{"account_id":"acc-123","session_key":"acc-123-key","expires_at_ms":1704153600000}`),
			Error:   "",
			TraceID: "trace-login",
		}
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(http.StatusOK)
		json.NewEncoder(w).Encode(resp)
	}))
	defer server.Close()

	client := NewAPIClient(server.URL)
	resp, err := client.Login("alice@example.com", "secret")
	if err != nil {
		t.Fatalf("Login() error = %v", err)
	}
	if resp.TraceID != "trace-login" {
		t.Errorf("TraceID = %q, want %q", resp.TraceID, "trace-login")
	}
}

func TestAPIClientAccountMethods(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		resp := APIResponse{
			Data:    json.RawMessage(`{"success":true}`),
			Error:   "",
			TraceID: "trace-account",
		}
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(http.StatusOK)
		json.NewEncoder(w).Encode(resp)
	}))
	defer server.Close()

	client := NewAPIClient(server.URL)

	t.Run("GetMe", func(t *testing.T) {
		resp, err := client.GetMe()
		if err != nil {
			t.Fatalf("GetMe() error = %v", err)
		}
		if resp.TraceID != "trace-account" {
			t.Errorf("TraceID = %q, want %q", resp.TraceID, "trace-account")
		}
	})

	t.Run("CreateAccount", func(t *testing.T) {
		resp, err := client.CreateAccount(map[string]interface{}{"account_name": "Bob"})
		if err != nil {
			t.Fatalf("CreateAccount() error = %v", err)
		}
		if resp.TraceID != "trace-account" {
			t.Errorf("TraceID = %q, want %q", resp.TraceID, "trace-account")
		}
	})

	t.Run("ListAccounts", func(t *testing.T) {
		resp, err := client.ListAccounts(ListQuery{Limit: 10}, "user", "active", "ext-1")
		if err != nil {
			t.Fatalf("ListAccounts() error = %v", err)
		}
		if resp.TraceID != "trace-account" {
			t.Errorf("TraceID = %q, want %q", resp.TraceID, "trace-account")
		}
	})

	t.Run("GetAccount", func(t *testing.T) {
		resp, err := client.GetAccount("acc-123")
		if err != nil {
			t.Fatalf("GetAccount() error = %v", err)
		}
		if resp.TraceID != "trace-account" {
			t.Errorf("TraceID = %q, want %q", resp.TraceID, "trace-account")
		}
	})

	t.Run("UpdateAccount", func(t *testing.T) {
		resp, err := client.UpdateAccount("acc-123", map[string]interface{}{"account_name": "Bob Updated"})
		if err != nil {
			t.Fatalf("UpdateAccount() error = %v", err)
		}
		if resp.TraceID != "trace-account" {
			t.Errorf("TraceID = %q, want %q", resp.TraceID, "trace-account")
		}
	})

	t.Run("DeleteAccount", func(t *testing.T) {
		resp, err := client.DeleteAccount("acc-123")
		if err != nil {
			t.Fatalf("DeleteAccount() error = %v", err)
		}
		if resp.TraceID != "trace-account" {
			t.Errorf("TraceID = %q, want %q", resp.TraceID, "trace-account")
		}
	})

	t.Run("ChangePassword", func(t *testing.T) {
		resp, err := client.ChangePassword("acc-123", "old", "new")
		if err != nil {
			t.Fatalf("ChangePassword() error = %v", err)
		}
		if resp.TraceID != "trace-account" {
			t.Errorf("TraceID = %q, want %q", resp.TraceID, "trace-account")
		}
	})

	t.Run("CreateSession", func(t *testing.T) {
		resp, err := client.CreateSession("acc-123")
		if err != nil {
			t.Fatalf("CreateSession() error = %v", err)
		}
		if resp.TraceID != "trace-account" {
			t.Errorf("TraceID = %q, want %q", resp.TraceID, "trace-account")
		}
	})
}

func TestAPIClientAPIKeyMethods(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		resp := APIResponse{
			Data:    json.RawMessage(`{"success":true}`),
			Error:   "",
			TraceID: "trace-ak",
		}
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(http.StatusOK)
		json.NewEncoder(w).Encode(resp)
	}))
	defer server.Close()

	client := NewAPIClient(server.URL)

	t.Run("CreateAPIKey", func(t *testing.T) {
		resp, err := client.CreateAPIKey("acc-123", "CLI Key", "user")
		if err != nil {
			t.Fatalf("CreateAPIKey() error = %v", err)
		}
		if resp.TraceID != "trace-ak" {
			t.Errorf("TraceID = %q, want %q", resp.TraceID, "trace-ak")
		}
	})

	t.Run("ListAPIKeys", func(t *testing.T) {
		resp, err := client.ListAPIKeys("acc-123", ListQuery{Limit: 10}, "active")
		if err != nil {
			t.Fatalf("ListAPIKeys() error = %v", err)
		}
		if resp.TraceID != "trace-ak" {
			t.Errorf("TraceID = %q, want %q", resp.TraceID, "trace-ak")
		}
	})

	t.Run("DeleteAPIKey", func(t *testing.T) {
		resp, err := client.DeleteAPIKey("acc-123", "ak-xyz")
		if err != nil {
			t.Fatalf("DeleteAPIKey() error = %v", err)
		}
		if resp.TraceID != "trace-ak" {
			t.Errorf("TraceID = %q, want %q", resp.TraceID, "trace-ak")
		}
	})
}

func TestListAccountsQueryString(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		query := r.URL.Query()
		if query.Get("role") != "user" {
			t.Errorf("role = %q, want %q", query.Get("role"), "user")
		}
		if query.Get("status") != "active" {
			t.Errorf("status = %q, want %q", query.Get("status"), "active")
		}
		if query.Get("external_id") != "ext-1" {
			t.Errorf("external_id = %q, want %q", query.Get("external_id"), "ext-1")
		}
		if query.Get("limit") != "10" {
			t.Errorf("limit = %q, want %q", query.Get("limit"), "10")
		}
		w.WriteHeader(http.StatusOK)
		json.NewEncoder(w).Encode(APIResponse{Data: json.RawMessage(`{}`)})
	}))
	defer server.Close()

	client := NewAPIClient(server.URL)
	_, err := client.ListAccounts(ListQuery{Limit: 10}, "user", "active", "ext-1")
	if err != nil {
		t.Fatalf("ListAccounts() error = %v", err)
	}
}

func TestListAPIKeysQueryString(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		query := r.URL.Query()
		if query.Get("status") != "active" {
			t.Errorf("status = %q, want %q", query.Get("status"), "active")
		}
		if query.Get("limit") != "5" {
			t.Errorf("limit = %q, want %q", query.Get("limit"), "5")
		}
		w.WriteHeader(http.StatusOK)
		json.NewEncoder(w).Encode(APIResponse{Data: json.RawMessage(`{}`)})
	}))
	defer server.Close()

	client := NewAPIClient(server.URL)
	_, err := client.ListAPIKeys("acc-123", ListQuery{Limit: 5}, "active")
	if err != nil {
		t.Fatalf("ListAPIKeys() error = %v", err)
	}
}
