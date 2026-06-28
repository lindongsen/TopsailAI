package main

import (
	"encoding/json"
	"testing"
)

func TestHandleMessageEvent(t *testing.T) {
	var got Message
	nc := NewNATSClient("")
	nc.onMessage = func(msg Message) { got = msg }

	payload := map[string]any{
		"type":    "message",
		"action":  "create",
		"groupId": "group-1",
		"data":    map[string]any{"message_id": "msg-1", "message_text": "hi"},
	}
	data, _ := json.Marshal(payload)
	nc.handleMessage(data)
	if got.MessageID != "msg-1" || got.MessageText != "hi" {
		t.Fatalf("unexpected message: %+v", got)
	}
}

func TestHandleMemberEvent(t *testing.T) {
	var got Member
	nc := NewNATSClient("")
	nc.onMember = func(member Member) { got = member }

	payload := map[string]any{
		"type":    "group_member",
		"action":  "create",
		"groupId": "group-1",
		"data":    map[string]any{"member_id": "alice", "member_name": "Alice"},
	}
	data, _ := json.Marshal(payload)
	nc.handleMessage(data)
	if got.MemberID != "alice" || got.MemberName != "Alice" {
		t.Fatalf("unexpected member: %+v", got)
	}
}

func TestHandleInvalidJSON(t *testing.T) {
	called := false
	nc := NewNATSClient("")
	nc.onMessage = func(_ Message) { called = true }
	nc.handleMessage([]byte("not json"))
	if called {
		t.Fatal("callback should not be invoked on invalid json")
	}
}
