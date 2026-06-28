package main

import (
	"encoding/json"
	"errors"
	"fmt"
	"testing"
	"time"

	"github.com/nats-io/nats.go"
)

type fakeJetStreamSubscriber struct {
	subscribeCalled bool
	subject         string
	returnSub       *nats.Subscription
	returnErr       error
}

func (f *fakeJetStreamSubscriber) Subscribe(subj string, cb nats.MsgHandler, opts ...nats.SubOpt) (*nats.Subscription, error) {
	f.subscribeCalled = true
	f.subject = subj
	if f.returnErr != nil {
		return nil, f.returnErr
	}
	if f.returnSub != nil {
		return f.returnSub, nil
	}
	return &nats.Subscription{}, nil
}

func TestNewNATSClient(t *testing.T) {
	c := NewNATSClient("nats://localhost:4222")
	if c == nil {
		t.Fatal("expected non-nil client")
	}
	if c.url != "nats://localhost:4222" {
		t.Fatalf("unexpected url: %s", c.url)
	}
	if c.msgCh == nil || c.memberCh == nil {
		t.Fatal("expected channels to be initialized")
	}
}

func TestSubscribeGroupErrorWhenNotConnected(t *testing.T) {
	c := NewNATSClient("nats://localhost:4222")
	err := c.SubscribeGroup("group-1")
	if err == nil {
		t.Fatal("expected error when not connected")
	}
	if err.Error() != "not connected" {
		t.Fatalf("unexpected error: %v", err)
	}
}

func TestSubscribeGroupSuccess(t *testing.T) {
	c := NewNATSClient("nats://localhost:4222")
	c.connected = true
	c.js = &fakeJetStreamSubscriber{returnSub: &nats.Subscription{}}

	original := jsSubscribeFunc
	jsSubscribeFunc = func(js jetStreamSubscriber, subj string, cb nats.MsgHandler, opts ...nats.SubOpt) (*nats.Subscription, error) {
		return js.Subscribe(subj, cb, opts...)
	}
	defer func() { jsSubscribeFunc = original }()

	err := c.SubscribeGroup("group-123")
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if c.sub == nil {
		t.Fatal("expected subscription to be set")
	}
}

func TestSubscribeGroupError(t *testing.T) {
	c := NewNATSClient("nats://localhost:4222")
	c.connected = true
	c.js = &fakeJetStreamSubscriber{returnErr: errors.New("subscribe failed")}

	original := jsSubscribeFunc
	jsSubscribeFunc = func(js jetStreamSubscriber, subj string, cb nats.MsgHandler, opts ...nats.SubOpt) (*nats.Subscription, error) {
		return js.Subscribe(subj, cb, opts...)
	}
	defer func() { jsSubscribeFunc = original }()

	err := c.SubscribeGroup("group-123")
	if err == nil || err.Error() != "subscribe failed" {
		t.Fatalf("unexpected error: %v", err)
	}
}

func TestHandleMessageMessageType(t *testing.T) {
	c := NewNATSClient("nats://localhost:4222")
	msg := Message{MessageID: "msg-1", MessageText: "hello"}
	raw, _ := json.Marshal(msg)
	envelope, _ := json.Marshal(map[string]interface{}{
		"type":   "message",
		"action": "create",
		"data":   json.RawMessage(raw),
	})

	c.handleMessage(envelope)

	select {
	case got := <-c.Messages():
		if got.MessageID != "msg-1" || got.MessageText != "hello" {
			t.Fatalf("unexpected message: %+v", got)
		}
	case <-time.After(time.Second):
		t.Fatal("expected message on channel")
	}
}

func TestHandleMessageMemberType(t *testing.T) {
	c := NewNATSClient("nats://localhost:4222")
	member := Member{MemberID: "m-1", MemberName: "Alice"}
	raw, _ := json.Marshal(member)
	envelope, _ := json.Marshal(map[string]interface{}{
		"type":   "group_member",
		"action": "create",
		"data":   json.RawMessage(raw),
	})

	c.handleMessage(envelope)

	select {
	case got := <-c.Members():
		if got.MemberID != "m-1" || got.MemberName != "Alice" {
			t.Fatalf("unexpected member: %+v", got)
		}
	case <-time.After(time.Second):
		t.Fatal("expected member on channel")
	}
}

func TestHandleMessageUnknownType(t *testing.T) {
	c := NewNATSClient("nats://localhost:4222")
	envelope, _ := json.Marshal(map[string]interface{}{
		"type":   "unknown",
		"action": "create",
		"data":   map[string]string{"id": "x"},
	})

	c.handleMessage(envelope)

	select {
	case <-c.Messages():
		t.Fatal("unexpected message")
	case <-c.Members():
		t.Fatal("unexpected member")
	case <-time.After(100 * time.Millisecond):
	}
}

func TestHandleMessageChannelFull(t *testing.T) {
	c := NewNATSClient("nats://localhost:4222")
	for i := 0; i < cap(c.msgCh)+1; i++ {
		msg := Message{MessageID: fmt.Sprintf("msg-%d", i)}
		raw, _ := json.Marshal(msg)
		envelope, _ := json.Marshal(map[string]interface{}{
			"type":   "message",
			"action": "create",
			"data":   json.RawMessage(raw),
		})
		c.handleMessage(envelope)
	}

	if len(c.msgCh) != cap(c.msgCh) {
		t.Fatalf("expected channel to be full, got %d", len(c.msgCh))
	}
}

func TestNATSClientClose(t *testing.T) {
	c := NewNATSClient("nats://localhost:4222")
	c.connected = true
	c.sub = &nats.Subscription{}
	c.Close()
	if c.connected {
		t.Fatal("expected client to be disconnected")
	}
}

// TestHandleMessageServerFormat reproduces the cross-user messaging bug.
// The server publishes the raw models.GroupMessage, where MessageAttachments
// and Mentions are stored as JSON strings. The CLI Message struct previously
// declared these fields as []any, causing json.Unmarshal to fail silently and
// dropping messages from other users.
func TestHandleMessageServerFormat(t *testing.T) {
	c := NewNATSClient("nats://localhost:4222")

	// Build an envelope that matches the server's actual publish format:
	// models.GroupMessage is marshaled directly, so message_attachments and
	// mentions are JSON strings, not arrays.
	envelope := map[string]interface{}{
		"type":    "message",
		"action":  "create",
		"groupId": "group-abc123",
		"data": map[string]interface{}{
			"group_id":             "group-abc123",
			"message_id":           "msg-from-alice",
			"message_text":         "hello from Alice",
			"message_attachments":  "[]",
			"sender_id":            "acc-alice",
			"sender_type":          "user",
			"processed_msg_id":     "",
			"mentions":             "[{\"member_id\":\"acc-bob\",\"member_name\":\"Bob\",\"member_type\":\"user\"}]",
			"is_deleted":           false,
			"delete_at_ms":         0,
			"create_at_ms":         1704067200000,
			"update_at_ms":         1704067200000,
		},
	}
	payload, _ := json.Marshal(envelope)

	c.handleMessage(payload)

	select {
	case got := <-c.Messages():
		if got.MessageID != "msg-from-alice" {
			t.Fatalf("expected message_id msg-from-alice, got %q", got.MessageID)
		}
		if got.MessageText != "hello from Alice" {
			t.Fatalf("expected message_text 'hello from Alice', got %q", got.MessageText)
		}
		if got.SenderID != "acc-alice" {
			t.Fatalf("expected sender_id acc-alice, got %q", got.SenderID)
		}
		if len(got.MessageAttachments) != 0 {
			t.Fatalf("expected empty attachments, got %v", got.MessageAttachments)
		}
		if len(got.Mentions) != 1 {
			t.Fatalf("expected 1 mention, got %d", len(got.Mentions))
		}
		mention, ok := got.Mentions[0].(map[string]any)
		if !ok {
			t.Fatalf("expected mention map, got %T", got.Mentions[0])
		}
		if mention["member_id"] != "acc-bob" || mention["member_name"] != "Bob" {
			t.Fatalf("unexpected mention: %v", mention)
		}
	case <-time.After(time.Second):
		t.Fatal("expected message on channel, but none received (likely unmarshal failed)")
	}
}

func TestJSONStringOrArrayUnmarshal(t *testing.T) {
	tests := []struct {
		name     string
		input    string
		wantLen  int
		wantErr  bool
		firstVal any
	}{
		{
			name:    "json string empty array",
			input:   `"[]"`,
			wantLen: 0,
		},
		{
			name:     "json string with object array",
			input:    `"[{\"member_id\":\"acc-bob\",\"member_name\":\"Bob\"}]"`,
			wantLen:  1,
			firstVal: map[string]any{"member_id": "acc-bob", "member_name": "Bob"},
		},
		{
			name:    "json array directly",
			input:   `[{"member_id":"acc-bob"}]`,
			wantLen: 1,
			firstVal: map[string]any{"member_id": "acc-bob"},
		},
		{
			name:    "empty json array directly",
			input:   `[]`,
			wantLen: 0,
		},
		{
			name:    "null",
			input:   `null`,
			wantLen: 0,
		},
		{
			name:    "invalid string content",
			input:   `"not-an-array"`,
			wantErr: true,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			var got JSONStringOrArray
			err := json.Unmarshal([]byte(tt.input), &got)
			if tt.wantErr {
				if err == nil {
					t.Fatal("expected error")
				}
				return
			}
			if err != nil {
				t.Fatalf("unexpected error: %v", err)
			}
			if len(got) != tt.wantLen {
				t.Fatalf("expected len %d, got %d", tt.wantLen, len(got))
			}
			if tt.wantLen > 0 && tt.firstVal != nil {
				m, ok := got[0].(map[string]any)
				if !ok {
					t.Fatalf("expected map, got %T", got[0])
				}
				wantMap, ok := tt.firstVal.(map[string]any)
				if !ok {
					t.Fatalf("test firstVal must be map[string]any")
				}
				for k, v := range wantMap {
					if m[k] != v {
						t.Fatalf("expected %s=%v, got %v", k, v, m[k])
					}
				}
			}
		})
	}
}
