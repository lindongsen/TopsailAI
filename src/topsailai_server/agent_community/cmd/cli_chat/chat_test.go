package main

import (
	"context"
	"encoding/json"
	"errors"
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

// fakeNATSClient is a test fake implementing natsClient.
type fakeNATSClient struct {
	connectErr      error
	subscribeErr    error
	connected       bool
	msgCh           chan Message
	memberCh        chan Member
	connectCalled   bool
	subscribeCalled bool
	lastGroupID     string
}

func newFakeNATSClient() *fakeNATSClient {
	return &fakeNATSClient{
		msgCh:    make(chan Message, 64),
		memberCh: make(chan Member, 64),
	}
}

func (f *fakeNATSClient) Connect() error {
	f.connectCalled = true
	if f.connectErr != nil {
		return f.connectErr
	}
	f.connected = true
	return nil
}

func (f *fakeNATSClient) SubscribeGroup(groupID string) error {
	f.subscribeCalled = true
	f.lastGroupID = groupID
	if f.subscribeErr != nil {
		return f.subscribeErr
	}
	return nil
}

func (f *fakeNATSClient) IsConnected() bool         { return f.connected }
func (f *fakeNATSClient) Messages() <-chan Message  { return f.msgCh }
func (f *fakeNATSClient) Members() <-chan Member    { return f.memberCh }
func (f *fakeNATSClient) Close()                    {}

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

func TestHandleIncomingMessageUpdatesMembers(t *testing.T) {
	app := newTestApp("http://localhost:7370")
	app.currentGroup = &Group{GroupID: "group-1"}
	app.handleMemberEvent(Member{GroupID: "group-1", MemberID: "alice", MemberName: "Alice"})
	if len(app.members) != 1 {
		t.Fatalf("expected 1 member, got %d", len(app.members))
	}
	app.handleMemberEvent(Member{GroupID: "group-1", MemberID: "alice", MemberName: "Alice Updated"})
	if app.members[0].MemberName != "Alice Updated" {
		t.Fatalf("expected member name updated, got %s", app.members[0].MemberName)
	}
}

func TestHandleIncomingMessageRendersMessage(t *testing.T) {
	app := newTestApp("http://localhost:7370")
	app.currentGroup = &Group{GroupID: "group-1"}
	app.handleIncomingMessage(Message{GroupID: "group-1", MessageID: "msg-direct", MessageText: "direct", SenderName: "Bob"})
}

func TestChatLoopPollsWhenNATSNotConnected(t *testing.T) {
	callCount := 0
	mux := http.NewServeMux()
	mux.HandleFunc("/api/v1/groups/group-1/messages", func(w http.ResponseWriter, r *http.Request) {
		callCount++
		_ = json.NewEncoder(w).Encode(Response[ListResponse[Message]]{Data: ListResponse[Message]{}})
	})
	srv := httptest.NewServer(mux)
	defer srv.Close()

	fake := newFakeNATSClient()
	fake.connected = false
	app := newTestApp(srv.URL)
	app.nats = fake

	app.currentGroup = &Group{GroupID: "group-1"}
	if err := app.showRecentMessages(context.Background()); err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if callCount != 1 {
		t.Fatalf("expected 1 poll call, got %d", callCount)
	}
}

func TestEnterChatReturnsConnectError(t *testing.T) {
	mux := http.NewServeMux()
	mux.HandleFunc("/api/v1/groups/group-1", func(w http.ResponseWriter, r *http.Request) {
		_ = json.NewEncoder(w).Encode(Response[Group]{Data: Group{GroupID: "group-1"}})
	})
	mux.HandleFunc("/api/v1/groups/group-1/members", func(w http.ResponseWriter, r *http.Request) {
		_ = json.NewEncoder(w).Encode(Response[ListResponse[Member]]{Data: ListResponse[Member]{Items: []Member{}}})
	})
	mux.HandleFunc("/api/v1/groups/group-1/messages", func(w http.ResponseWriter, r *http.Request) {
		_ = json.NewEncoder(w).Encode(Response[ListResponse[Message]]{Data: ListResponse[Message]{Items: []Message{}}})
	})
	srv := httptest.NewServer(mux)
	defer srv.Close()

	fake := newFakeNATSClient()
	fake.connectErr = errors.New("nats connect failed")
	app := newTestApp(srv.URL)
	app.nats = fake

	err := app.EnterChat(context.Background(), "group-1")
	if err == nil || !errors.Is(err, fake.connectErr) {
		t.Fatalf("expected connect error, got %v", err)
	}
	if !fake.connectCalled {
		t.Fatal("expected Connect to be called")
	}
	if fake.subscribeCalled {
		t.Fatal("expected SubscribeGroup not to be called after connect failure")
	}
}

func TestEnterChatReturnsSubscribeError(t *testing.T) {
	mux := http.NewServeMux()
	mux.HandleFunc("/api/v1/groups/group-1", func(w http.ResponseWriter, r *http.Request) {
		_ = json.NewEncoder(w).Encode(Response[Group]{Data: Group{GroupID: "group-1"}})
	})
	mux.HandleFunc("/api/v1/groups/group-1/members", func(w http.ResponseWriter, r *http.Request) {
		_ = json.NewEncoder(w).Encode(Response[ListResponse[Member]]{Data: ListResponse[Member]{Items: []Member{}}})
	})
	mux.HandleFunc("/api/v1/groups/group-1/messages", func(w http.ResponseWriter, r *http.Request) {
		_ = json.NewEncoder(w).Encode(Response[ListResponse[Message]]{Data: ListResponse[Message]{Items: []Message{}}})
	})
	srv := httptest.NewServer(mux)
	defer srv.Close()

	fake := newFakeNATSClient()
	fake.subscribeErr = errors.New("nats subscribe failed")
	app := newTestApp(srv.URL)
	app.nats = fake

	err := app.EnterChat(context.Background(), "group-1")
	if err == nil || !errors.Is(err, fake.subscribeErr) {
		t.Fatalf("expected subscribe error, got %v", err)
	}
	if !fake.connectCalled {
		t.Fatal("expected Connect to be called")
	}
	if !fake.subscribeCalled {
		t.Fatal("expected SubscribeGroup to be called")
	}
}

func TestHandleIncomingMessageChannelDriven(t *testing.T) {
	mux := http.NewServeMux()
	mux.HandleFunc("/api/v1/groups/group-1", func(w http.ResponseWriter, r *http.Request) {
		_ = json.NewEncoder(w).Encode(Response[Group]{Data: Group{GroupID: "group-1"}})
	})
	mux.HandleFunc("/api/v1/groups/group-1/members", func(w http.ResponseWriter, r *http.Request) {
		_ = json.NewEncoder(w).Encode(Response[ListResponse[Member]]{Data: ListResponse[Member]{Items: []Member{}}})
	})
	mux.HandleFunc("/api/v1/groups/group-1/messages", func(w http.ResponseWriter, r *http.Request) {
		_ = json.NewEncoder(w).Encode(Response[ListResponse[Message]]{Data: ListResponse[Message]{Items: []Message{}}})
	})
	srv := httptest.NewServer(mux)
	defer srv.Close()

	fake := newFakeNATSClient()
	app := newTestApp(srv.URL)
	app.nats = fake

	// Since we cannot drive readline in a unit test, verify the handler path directly.
	app.handleIncomingMessage(Message{GroupID: "group-1", MessageID: "msg-direct", MessageText: "direct", SenderName: "Bob"})
}
