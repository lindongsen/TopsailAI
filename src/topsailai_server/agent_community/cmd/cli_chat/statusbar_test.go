package main

import (
	"strings"
	"testing"
)

func TestStatusBarRender(t *testing.T) {
	globalColorEnabled = false
	sb := NewStatusBar(8)
	sb.Update([]Member{
		{MemberID: "alice", MemberName: "Alice", MemberStatus: "online"},
		{MemberID: "bob", MemberName: "Bob", MemberStatus: "idle"},
	})
	out := sb.Render()
	if !strings.Contains(out, "Alice") || !strings.Contains(out, "Bob") {
		t.Fatalf("unexpected status bar: %q", out)
	}
}

func TestStatusBarLimit(t *testing.T) {
	globalColorEnabled = false
	sb := NewStatusBar(2)
	members := []Member{
		{MemberID: "a", MemberName: "A", MemberStatus: "online"},
		{MemberID: "b", MemberName: "B", MemberStatus: "online"},
		{MemberID: "c", MemberName: "C", MemberStatus: "online"},
	}
	sb.Update(members)
	out := sb.Render()
	if strings.Contains(out, "C") {
		t.Fatalf("status bar should not contain third member: %q", out)
	}
}

func TestStatusBarEmpty(t *testing.T) {
	globalColorEnabled = false
	sb := NewStatusBar(8)
	out := sb.Render()
	if out != "" {
		t.Fatalf("expected empty status bar, got %q", out)
	}
}
