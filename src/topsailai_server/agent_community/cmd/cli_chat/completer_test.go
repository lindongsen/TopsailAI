package main

import (
	"testing"
)

func TestCompleterCommand(t *testing.T) {
	c := NewCompleter()
	cands, length := c.Do([]rune("/gro"), 4)
	if length != 4 {
		t.Fatalf("expected length 4, got %d", length)
	}
	found := false
	for _, cand := range cands {
		if string(cand) == "/group list" {
			found = true
		}
	}
	if !found {
		t.Fatalf("expected /group list candidate, got %v", cands)
	}
}

func TestCompleterMentionByName(t *testing.T) {
	members := []Member{
		{MemberID: "alice", MemberName: "Alice"},
		{MemberID: "bob", MemberName: "Bob"},
	}
	c := NewCompleter()
	c.SetMembers(members)
	cands, length := c.Do([]rune("@A"), 2)
	if length != 2 {
		t.Fatalf("expected length 2, got %d", length)
	}
	if len(cands) != 1 || string(cands[0]) != "Alice" {
		t.Fatalf("expected Alice candidate, got %v", cands)
	}
}

func TestCompleterMentionByID(t *testing.T) {
	members := []Member{
		{MemberID: "alice-1", MemberName: "Alice"},
	}
	c := NewCompleter()
	c.SetMembers(members)
	cands, length := c.Do([]rune("@alice"), 6)
	if length != 6 {
		t.Fatalf("expected length 6, got %d", length)
	}
	if len(cands) != 1 || string(cands[0]) != "Alice" {
		t.Fatalf("expected Alice candidate, got %v", cands)
	}
}

func TestCompleterNoMention(t *testing.T) {
	members := []Member{
		{MemberID: "alice", MemberName: "Alice"},
	}
	c := NewCompleter()
	c.SetMembers(members)
	cands, length := c.Do([]rune("hello"), 5)
	if length != 5 || len(cands) != 0 {
		t.Fatalf("expected no completion, got %v %d", cands, length)
	}
}
