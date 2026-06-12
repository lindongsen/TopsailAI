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
		resp, err := client.SendMessage("g1", "Hello", "u1", "user", nil)
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
