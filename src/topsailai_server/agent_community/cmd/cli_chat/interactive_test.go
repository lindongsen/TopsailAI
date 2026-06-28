package main

import (
	"testing"
)

func TestCollectAddMemberArgsInlineUser(t *testing.T) {
	args := []string{"alice", "Alice", "user"}
	memberID, name, memberType, _, err := collectAddMemberArgs(args)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if memberID != "alice" || name != "Alice" || memberType != "user" {
		t.Fatalf("unexpected args: %q %q %q", memberID, name, memberType)
	}
}

func TestCollectAddMemberArgsInlineAgent(t *testing.T) {
	args := []string{"agent-1", "Agent One", "worker-agent"}
	memberID, name, memberType, iface, err := collectAddMemberArgs(args)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if memberID != "agent-1" || name != "Agent One" || memberType != "worker-agent" {
		t.Fatalf("unexpected args: %q %q %q", memberID, name, memberType)
	}
	if iface == nil {
		t.Fatal("expected default empty interface for agent")
	}
	if len(iface) != 0 {
		t.Fatalf("expected empty interface map, got %v", iface)
	}
}

func TestCollectAddMemberArgsEmptyID(t *testing.T) {
	args := []string{"", "X", "user"}
	_, _, _, _, err := collectAddMemberArgs(args)
	if err == nil {
		t.Fatal("expected error for empty member id")
	}
}

func TestPromptMemberInterfaceEmptyDefaults(t *testing.T) {
	// promptMemberInterface reads from stdin; we cannot easily test interactive input here.
	// This test documents the expected default behavior for inline agent args.
	args := []string{"agent-1", "Agent", "worker-agent"}
	_, _, _, iface, err := collectAddMemberArgs(args)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if len(iface) != 0 {
		t.Fatalf("expected empty default interface, got %v", iface)
	}
}
