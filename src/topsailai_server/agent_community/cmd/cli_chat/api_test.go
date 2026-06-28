package main

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
)

func TestAPIClientLogin(t *testing.T) {
	mux := http.NewServeMux()
	mux.HandleFunc("/api/v1/accounts/login", func(w http.ResponseWriter, r *http.Request) {
		var req struct {
			LoginName     string `json:"login_name"`
			LoginPassword string `json:"login_password"`
		}
		if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
			http.Error(w, err.Error(), http.StatusBadRequest)
			return
		}
		if req.LoginName != "alice" || req.LoginPassword != "secret" {
			w.WriteHeader(http.StatusUnauthorized)
			_ = json.NewEncoder(w).Encode(Response[json.RawMessage]{Error: "unauthorized"})
			return
		}
		_ = json.NewEncoder(w).Encode(Response[LoginResponse]{
			Data: LoginResponse{
				AccountID:   "acc-1",
				SessionKey:  "acc-1-session",
				ExpiresAtMs: 9999999999,
			},
		})
	})
	srv := httptest.NewServer(mux)
	defer srv.Close()

	c := NewClient(srv.URL)
	ctx := context.Background()
	resp, sessionKey, err := c.Login(ctx, "alice", "secret")
	if err != nil {
		t.Fatalf("unexpected login error: %v", err)
	}
	if sessionKey != "acc-1-session" {
		t.Fatalf("expected session key acc-1-session, got %q", sessionKey)
	}
	if resp.AccountID != "acc-1" {
		t.Fatalf("unexpected account id: %q", resp.AccountID)
	}
	if c.sessionKey != "acc-1-session" {
		t.Fatalf("expected client session key to be set")
	}
}

func TestAPIClientLoginError(t *testing.T) {
	mux := http.NewServeMux()
	mux.HandleFunc("/api/v1/accounts/login", func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusUnauthorized)
		_ = json.NewEncoder(w).Encode(Response[json.RawMessage]{Error: "invalid credentials"})
	})
	srv := httptest.NewServer(mux)
	defer srv.Close()

	c := NewClient(srv.URL)
	_, _, err := c.Login(context.Background(), "alice", "wrong")
	if err == nil {
		t.Fatal("expected error")
	}
	if !strings.Contains(err.Error(), "invalid credentials") {
		t.Fatalf("unexpected error message: %v", err)
	}
}

func TestAPIClientAuthHeaders(t *testing.T) {
	var authHeader string
	mux := http.NewServeMux()
	mux.HandleFunc("/api/v1/accounts/me", func(w http.ResponseWriter, r *http.Request) {
		authHeader = r.Header.Get("Authorization")
		if authHeader == "" {
			authHeader = r.Header.Get("X-Session-Key")
		}
		_ = json.NewEncoder(w).Encode(Response[Account]{Data: Account{AccountID: "acc-1"}})
	})
	srv := httptest.NewServer(mux)
	defer srv.Close()

	c := NewClient(srv.URL)
	c.SetAPIKey("ak-test.secret")
	_, _ = c.GetMe(context.Background())
	if authHeader != "Bearer ak-test.secret" {
		t.Fatalf("expected API key auth header, got %q", authHeader)
	}

	c.SetSessionKey("session-key")
	_, _ = c.GetMe(context.Background())
	if authHeader != "session-key" {
		t.Fatalf("expected session key header, got %q", authHeader)
	}
}

func TestAPIClientListGroups(t *testing.T) {
	mux := http.NewServeMux()
	mux.HandleFunc("/api/v1/groups", func(w http.ResponseWriter, r *http.Request) {
		_ = json.NewEncoder(w).Encode(Response[ListResponse[Group]]{
			Data: ListResponse[Group]{
				Items: []Group{{GroupID: "group-1", GroupName: "G1"}},
				Total: 1,
			},
		})
	})
	srv := httptest.NewServer(mux)
	defer srv.Close()

	c := NewClient(srv.URL)
	c.SetAPIKey("ak-test.secret")
	groups, err := c.ListGroups(context.Background())
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if len(groups) != 1 || groups[0].GroupID != "group-1" {
		t.Fatalf("unexpected groups: %v", groups)
	}
}

func TestAPIClientCreateGroup(t *testing.T) {
	mux := http.NewServeMux()
	mux.HandleFunc("/api/v1/groups", func(w http.ResponseWriter, r *http.Request) {
		var req CreateGroupRequest
		if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
			http.Error(w, err.Error(), http.StatusBadRequest)
			return
		}
		if req.GroupName != "G1" {
			t.Fatalf("unexpected group name: %q", req.GroupName)
		}
		_ = json.NewEncoder(w).Encode(Response[Group]{Data: Group{GroupID: "group-1", GroupName: "G1"}})
	})
	srv := httptest.NewServer(mux)
	defer srv.Close()

	c := NewClient(srv.URL)
	c.SetAPIKey("ak-test.secret")
	group, err := c.CreateGroup(context.Background(), "G1", "ctx", "key")
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if group.GroupID != "group-1" {
		t.Fatalf("unexpected group id: %q", group.GroupID)
	}
}

func TestAPIClientGetGroup(t *testing.T) {
	mux := http.NewServeMux()
	mux.HandleFunc("/api/v1/groups/group-1", func(w http.ResponseWriter, r *http.Request) {
		_ = json.NewEncoder(w).Encode(Response[Group]{Data: Group{GroupID: "group-1", GroupName: "G1"}})
	})
	srv := httptest.NewServer(mux)
	defer srv.Close()

	c := NewClient(srv.URL)
	c.SetAPIKey("ak-test.secret")
	group, err := c.GetGroup(context.Background(), "group-1")
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if group.GroupID != "group-1" {
		t.Fatalf("unexpected group: %v", group)
	}
}

func TestAPIClientListMembers(t *testing.T) {
	mux := http.NewServeMux()
	mux.HandleFunc("/api/v1/groups/group-1/members", func(w http.ResponseWriter, r *http.Request) {
		_ = json.NewEncoder(w).Encode(Response[ListResponse[Member]]{
			Data: ListResponse[Member]{
				Items: []Member{{MemberID: "alice", MemberName: "Alice", MemberType: "user"}},
			},
		})
	})
	srv := httptest.NewServer(mux)
	defer srv.Close()

	c := NewClient(srv.URL)
	c.SetAPIKey("ak-test.secret")
	members, err := c.ListMembers(context.Background(), "group-1")
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if len(members) != 1 || members[0].MemberID != "alice" {
		t.Fatalf("unexpected members: %v", members)
	}
}

func TestAPIClientAddMember(t *testing.T) {
	mux := http.NewServeMux()
	mux.HandleFunc("/api/v1/groups/group-1/members", func(w http.ResponseWriter, r *http.Request) {
		var req AddMemberRequest
		if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
			http.Error(w, err.Error(), http.StatusBadRequest)
			return
		}
		if req.MemberInterface == nil {
			http.Error(w, "missing member_interface", http.StatusBadRequest)
			return
		}
		_ = json.NewEncoder(w).Encode(Response[Member]{Data: Member{
			MemberID:        req.MemberID,
			MemberName:      req.MemberName,
			MemberType:      req.MemberType,
			MemberInterface: req.MemberInterface,
		}})
	})
	srv := httptest.NewServer(mux)
	defer srv.Close()

	c := NewClient(srv.URL)
	c.SetAPIKey("ak-test.secret")
	iface := map[string]any{"adaptor": "mock"}
	member, err := c.AddMember(context.Background(), "group-1", "agent-1", "Agent", "worker-agent", iface)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if member.MemberID != "agent-1" {
		t.Fatalf("unexpected member: %v", member)
	}
	if member.MemberInterface == nil {
		t.Fatalf("expected member_interface to be set")
	}
}

func TestAPIClientLeaveGroup(t *testing.T) {
	var method string
	mux := http.NewServeMux()
	mux.HandleFunc("/api/v1/groups/group-1/members/alice", func(w http.ResponseWriter, r *http.Request) {
		method = r.Method
		w.WriteHeader(http.StatusNoContent)
	})
	srv := httptest.NewServer(mux)
	defer srv.Close()

	c := NewClient(srv.URL)
	c.SetAPIKey("ak-test.secret")
	if err := c.LeaveGroup(context.Background(), "group-1", "alice"); err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if method != http.MethodDelete {
		t.Fatalf("expected DELETE, got %q", method)
	}
}

func TestAPIClientListMessages(t *testing.T) {
	mux := http.NewServeMux()
	mux.HandleFunc("/api/v1/groups/group-1/messages", func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Query().Get("limit") != "50" {
			t.Fatalf("unexpected limit: %q", r.URL.Query().Get("limit"))
		}
		_ = json.NewEncoder(w).Encode(Response[ListResponse[Message]]{
			Data: ListResponse[Message]{
				Items: []Message{{MessageID: "msg-1", MessageText: "hello"}},
			},
		})
	})
	srv := httptest.NewServer(mux)
	defer srv.Close()

	c := NewClient(srv.URL)
	c.SetAPIKey("ak-test.secret")
	messages, err := c.ListMessages(context.Background(), "group-1", 50)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if len(messages) != 1 || messages[0].MessageID != "msg-1" {
		t.Fatalf("unexpected messages: %v", messages)
	}
}

func TestAPIClientSendMessage(t *testing.T) {
	mux := http.NewServeMux()
	mux.HandleFunc("/api/v1/groups/group-1/messages", func(w http.ResponseWriter, r *http.Request) {
		var req SendMessageRequest
		if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
			http.Error(w, err.Error(), http.StatusBadRequest)
			return
		}
		_ = json.NewEncoder(w).Encode(Response[Message]{Data: Message{
			MessageID:   "msg-1",
			MessageText: req.MessageText,
		}})
	})
	srv := httptest.NewServer(mux)
	defer srv.Close()

	c := NewClient(srv.URL)
	c.SetAPIKey("ak-test.secret")
	msg, err := c.SendMessage(context.Background(), "group-1", "hello")
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if msg.MessageText != "hello" {
		t.Fatalf("unexpected message text: %q", msg.MessageText)
	}
}

func TestAPIClientMeAlias(t *testing.T) {
	mux := http.NewServeMux()
	mux.HandleFunc("/api/v1/accounts/me", func(w http.ResponseWriter, r *http.Request) {
		_ = json.NewEncoder(w).Encode(Response[Account]{Data: Account{AccountID: "acc-1"}})
	})
	srv := httptest.NewServer(mux)
	defer srv.Close()

	c := NewClient(srv.URL)
	c.SetAPIKey("ak-test.secret")
	acc, err := c.Me(context.Background())
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if acc.AccountID != "acc-1" {
		t.Fatalf("unexpected account: %v", acc)
	}
}

func TestAPIClientDecodeHTTPError(t *testing.T) {
	mux := http.NewServeMux()
	mux.HandleFunc("/api/v1/groups", func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusForbidden)
		_ = json.NewEncoder(w).Encode(Response[json.RawMessage]{Error: "access denied"})
	})
	srv := httptest.NewServer(mux)
	defer srv.Close()

	c := NewClient(srv.URL)
	c.SetAPIKey("ak-test.secret")
	_, err := c.ListGroups(context.Background())
	if err == nil {
		t.Fatal("expected error")
	}
	if !strings.Contains(err.Error(), "access denied") {
		t.Fatalf("unexpected error: %v", err)
	}
}
