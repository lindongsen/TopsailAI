package main

import "testing"

func TestExpandAliasGroupCreate(t *testing.T) {
	got := expandAlias("/group:create")
	if got != "/group create" {
		t.Fatalf("unexpected expansion: %q", got)
	}
}

func TestExpandAliasChat(t *testing.T) {
	got := expandAlias("/group:enter")
	if got != "/chat" {
		t.Fatalf("unexpected expansion: %q", got)
	}
}

func TestExpandAliasMemberList(t *testing.T) {
	got := expandAlias("/member:list")
	if got != "/member list" {
		t.Fatalf("unexpected expansion: %q", got)
	}
}

func TestExpandAliasUnknown(t *testing.T) {
	got := expandAlias("/unknown a")
	if got != "/unknown a" {
		t.Fatalf("unexpected passthrough: %q", got)
	}
}

func TestExpandAliasNoArgs(t *testing.T) {
	got := expandAlias("/group:list")
	if got != "/group list" {
		t.Fatalf("unexpected expansion: %q", got)
	}
}
