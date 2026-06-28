package main

import (
	"strings"
	"testing"
)

func TestDisplayGroups(t *testing.T) {
	globalColorEnabled = false
	d := NewDisplay(true)
	groups := []Group{
		{GroupID: "group-1", GroupName: "One", CreatorID: "acc-1", CreateAtMs: 1704067200000},
	}
	out := d.Groups(groups)
	if !strings.Contains(out, "One") || !strings.Contains(out, "group-1") {
		t.Fatalf("unexpected groups output: %q", out)
	}
}

func TestDisplayMembers(t *testing.T) {
	globalColorEnabled = false
	d := NewDisplay(true)
	members := []Member{
		{MemberID: "alice", MemberName: "Alice", MemberType: "user", MemberStatus: "online"},
	}
	out := d.Members(members)
	if !strings.Contains(out, "Alice") || !strings.Contains(out, "online") {
		t.Fatalf("unexpected members output: %q", out)
	}
}

func TestDisplayMessages(t *testing.T) {
	globalColorEnabled = false
	d := NewDisplay(true)
	msgs := []Message{
		{MessageID: "msg-1", MessageText: "hello", SenderName: "Alice", CreateAtMs: 1704067200000},
	}
	out := d.Messages(msgs)
	if !strings.Contains(out, "hello") || !strings.Contains(out, "Alice") {
		t.Fatalf("unexpected messages output: %q", out)
	}
}

func TestDisplayError(t *testing.T) {
	globalColorEnabled = false
	d := NewDisplay(true)
	out := d.Error("not found", "/group list")
	if !strings.Contains(out, "Error: not found") {
		t.Fatalf("missing error prefix: %q", out)
	}
	if !strings.Contains(out, "Suggestion: /group list") {
		t.Fatalf("missing suggestion: %q", out)
	}
}

func TestFormatTime(t *testing.T) {
	got := formatTime(1704067200000)
	if got != "2024-01-01T00:00:00" {
		t.Fatalf("unexpected timestamp: %q", got)
	}
}
