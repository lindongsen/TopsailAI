package main

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"
)

func newTestApp(baseURL string) *App {
	client := NewClient(baseURL)
	display := NewDisplay(true)
	prompt := NewPromptManager("tester")
	completer := NewCompleter()
	return NewApp(client, nil, completer, display, prompt, nil)
}

func TestSendMessage(t *testing.T) {
	mux := http.NewServeMux()
	mux.HandleFunc("/api/v1/groups/group-1/messages", func(w http.ResponseWriter, r *http.Request) {
		var req SendMessageRequest
		_ = json.NewDecoder(r.Body).Decode(&req)
		_ = json.NewEncoder(w).Encode(Response[Message]{Data: Message{
			MessageID:   "msg-1",
			MessageText: req.MessageText,
			SenderName:  "Alice",
			CreateAtMs:  1704067200000,
		}})
	})
	srv := httptest.NewServer(mux)
	defer srv.Close()

	app := newTestApp(srv.URL)
	app.currentGroup = &Group{GroupID: "group-1"}
	if err := app.sendMessage(context.Background(), "hello"); err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
}

func TestShowRecentMessages(t *testing.T) {
	mux := http.NewServeMux()
	mux.HandleFunc("/api/v1/groups/group-1/messages", func(w http.ResponseWriter, r *http.Request) {
		_ = json.NewEncoder(w).Encode(Response[ListResponse[Message]]{
			Data: ListResponse[Message]{
				Items: []Message{{MessageID: "msg-1", MessageText: "hi", SenderName: "Alice", CreateAtMs: 1704067200000}},
			},
		})
	})
	srv := httptest.NewServer(mux)
	defer srv.Close()

	app := newTestApp(srv.URL)
	app.currentGroup = &Group{GroupID: "group-1"}
	if err := app.showRecentMessages(context.Background()); err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
}

func TestRefreshMembers(t *testing.T) {
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

	app := newTestApp(srv.URL)
	app.currentGroup = &Group{GroupID: "group-1"}
	if err := app.refreshMembers(context.Background()); err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if len(app.members) != 1 {
		t.Fatalf("expected 1 member, got %d", len(app.members))
	}
}

func TestHandleIncomingMessageFiltersGroup(t *testing.T) {
	app := newTestApp("http://localhost:7370")
	app.currentGroup = &Group{GroupID: "group-1"}
	app.handleIncomingMessage(Message{GroupID: "group-2", MessageText: "x"})
}
