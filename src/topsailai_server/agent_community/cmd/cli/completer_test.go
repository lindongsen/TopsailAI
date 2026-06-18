// Package main provides unit tests for tab auto-completion.
package main

import (
	"strings"
	"testing"
)

func TestNewNormalCompleterNotNil(t *testing.T) {
	c := newNormalCompleter()
	if c == nil {
		t.Fatal("newNormalCompleter() returned nil")
	}
}

func TestNewChatCompleterNotNil(t *testing.T) {
	c := newChatCompleter()
	if c == nil {
		t.Fatal("newChatCompleter() returned nil")
	}
}

func TestFilterCommands(t *testing.T) {
	commands := []string{
		"/group:list", "/group:create", "/group:enter",
		"/member:list", "/member:add",
		"/message:list",
		"/help", "/exit",
	}

	tests := []struct {
		prefix string
		want   []string
	}{
		{"/g", []string{"/group:list", "/group:create", "/group:enter"}},
		{"/group:", []string{"/group:list", "/group:create", "/group:enter"}},
		{"/mes", []string{"/message:list"}},
		{"/mem", []string{"/member:list", "/member:add"}},
		{"/h", []string{"/help"}},
		{"/ex", []string{"/exit"}},
		{"/xyz", []string{}},
		{"", commands},
	}

	for _, tt := range tests {
		t.Run(tt.prefix, func(t *testing.T) {
			got := filterCommands(tt.prefix, commands)
			if len(got) != len(tt.want) {
				t.Fatalf("filterCommands(%q) = %v, want %v", tt.prefix, got, tt.want)
			}
			for i := range tt.want {
				if got[i] != tt.want[i] {
					t.Errorf("filterCommands(%q)[%d] = %q, want %q", tt.prefix, i, got[i], tt.want[i])
				}
			}
		})
	}
}

func TestFilterCommandsCaseInsensitive(t *testing.T) {
	commands := []string{"/group:list", "/GROUP:create"}

	got := filterCommands("/GROUP", commands)
	if len(got) != 2 {
		t.Errorf("expected 2 matches for case-insensitive filter, got %d", len(got))
	}
}

func TestCompleterFromCommands(t *testing.T) {
	commands := []string{"/foo", "/bar", "/baz"}
	c := completerFromCommands(commands)
	if c == nil {
		t.Fatal("completerFromCommands() returned nil")
	}

	for _, cmd := range commands {
		_, _ = c.Do([]rune(cmd), len(cmd))
	}
}

func TestNormalCompleterDoDoesNotPanic(t *testing.T) {
	c := newNormalCompleter()
	inputs := []string{"/mes", "he", "/mem", "/group", "/", "exit", "quit", "help"}
	for _, input := range inputs {
		_, _ = c.Do([]rune(input), len(input))
	}
}

func TestChatCompleterDoDoesNotPanic(t *testing.T) {
	c := newChatCompleter()
	inputs := []string{"/mem", "/ex", "/h", "/", "exit", "quit"}
	for _, input := range inputs {
		_, _ = c.Do([]rune(input), len(input))
	}
}

// --- Mention completer tests ---

func TestChatMentionCompleterEmptyMembers(t *testing.T) {
	c := newChatMentionCompleter(func() []map[string]interface{} {
		return nil
	})

	// Typing "@" should only suggest @all.
	candidates, offset := c.Do([]rune("Hello @"), 7)
	if offset != 6 {
		t.Errorf("offset = %d, want 6", offset)
	}
	if len(candidates) != 1 {
		t.Fatalf("expected 1 candidate, got %d", len(candidates))
	}
	if string(candidates[0]) != "@all " {
		t.Errorf("candidate = %q, want \"@all \"", string(candidates[0]))
	}
}

func TestChatMentionCompleterWithMembers(t *testing.T) {
	members := []map[string]interface{}{
		{"member_id": "alice-001", "member_name": "Alice"},
		{"member_id": "bob-002", "member_name": "Bob"},
		{"member_id": "charlie-003", "member_name": "Charlie"},
	}
	c := newChatMentionCompleter(func() []map[string]interface{} {
		return members
	})

	// Typing "@" should suggest all members + @all.
	candidates, offset := c.Do([]rune("@"), 1)
	if offset != 0 {
		t.Errorf("offset = %d, want 0", offset)
	}
	if len(candidates) != 4 {
		t.Fatalf("expected 4 candidates, got %d", len(candidates))
	}

	// Check that all expected replacements are present (IDs are inserted).
	expected := map[string]bool{"@alice-001 ": false, "@bob-002 ": false, "@charlie-003 ": false, "@all ": false}
	for _, cand := range candidates {
		expected[string(cand)] = true
	}
	for name, found := range expected {
		if !found {
			t.Errorf("expected candidate %q not found", name)
		}
	}
}

func TestChatMentionCompleterPrefixFilter(t *testing.T) {
	members := []map[string]interface{}{
		{"member_id": "alice-001", "member_name": "Alice"},
		{"member_id": "bob-002", "member_name": "Bob"},
		{"member_id": "anna-003", "member_name": "Anna"},
	}
	c := newChatMentionCompleter(func() []map[string]interface{} {
		return members
	})

	// Typing "@A" should suggest Alice, Anna, and @all (matched by name).
	candidates, offset := c.Do([]rune("@A"), 2)
	if offset != 0 {
		t.Errorf("offset = %d, want 0", offset)
	}
	if len(candidates) != 3 {
		t.Fatalf("expected 3 candidates, got %d", len(candidates))
	}

	// Typing "@ali" should suggest Alice (matched by ID) but not @all.
	candidates, offset = c.Do([]rune("@ali"), 4)
	if offset != 0 {
		t.Errorf("offset = %d, want 0", offset)
	}
	if len(candidates) != 1 {
		t.Fatalf("expected 1 candidate (Alice), got %d", len(candidates))
	}
	// Verify Alice replacement is among the candidates.
	foundAlice := false
	for _, cand := range candidates {
		if string(cand) == "@alice-001 " {
			foundAlice = true
			break
		}
	}
	if !foundAlice {
		t.Error("expected \"@alice-001 \" among candidates for @ali")
	}
}

func TestChatMentionCompleterCaseInsensitive(t *testing.T) {
	members := []map[string]interface{}{
		{"member_id": "alice-001", "member_name": "Alice"},
	}
	c := newChatMentionCompleter(func() []map[string]interface{} {
		return members
	})

	// Typing "@a" should match "Alice" (name) and "all".
	candidates, offset := c.Do([]rune("@a"), 2)
	if offset != 0 {
		t.Errorf("offset = %d, want 0", offset)
	}
	if len(candidates) != 2 {
		t.Fatalf("expected 2 candidates, got %d", len(candidates))
	}
	foundAlice := false
	for _, cand := range candidates {
		if string(cand) == "@alice-001 " {
			foundAlice = true
			break
		}
	}
	if !foundAlice {
		t.Error("expected \"@alice-001 \" among candidates for @a")
	}
}

func TestChatMentionCompleterDeduplicates(t *testing.T) {
	members := []map[string]interface{}{
		{"member_id": "alice-001", "member_name": "Alice"},
		{"member_id": "alice-001", "member_name": "Alice"},
		{"member_id": "bob-002", "member_name": "Bob"},
	}
	c := newChatMentionCompleter(func() []map[string]interface{} {
		return members
	})

	candidates, _ := c.Do([]rune("@"), 1)
	if len(candidates) != 3 {
		t.Fatalf("expected 3 unique candidates, got %d", len(candidates))
	}
}

func TestChatMentionCompleterSkipsEmptyID(t *testing.T) {
	members := []map[string]interface{}{
		{"member_id": "", "member_name": ""},
		{"member_id": "alice-001", "member_name": "Alice"},
	}
	c := newChatMentionCompleter(func() []map[string]interface{} {
		return members
	})

	candidates, _ := c.Do([]rune("@"), 1)
	if len(candidates) != 2 {
		t.Fatalf("expected 2 candidates (Alice + all), got %d", len(candidates))
	}
}

func TestChatMentionCompleterSlashCommands(t *testing.T) {
	c := newChatMentionCompleter(func() []map[string]interface{} {
		return nil
	})

	// Slash commands should still work.
	candidates, _ := c.Do([]rune("/mem"), 4)
	if len(candidates) == 0 {
		t.Error("expected candidates for /mem command")
	}
}

func TestChatMentionCompleterMidLine(t *testing.T) {
	members := []map[string]interface{}{
		{"member_id": "alice-001", "member_name": "Alice"},
	}
	c := newChatMentionCompleter(func() []map[string]interface{} {
		return members
	})

	// Typing in the middle of a line.
	candidates, offset := c.Do([]rune("Hello @A"), 8)
	if offset != 6 {
		t.Errorf("offset = %d, want 6", offset)
	}
	if len(candidates) != 2 {
		t.Fatalf("expected 2 candidates (Alice + all), got %d", len(candidates))
	}
	foundAlice := false
	for _, cand := range candidates {
		if string(cand) == "@alice-001 " {
			foundAlice = true
			break
		}
	}
	if !foundAlice {
		t.Error("expected \"@alice-001 \" among candidates for Hello @A")
	}
}

func TestChatMentionCompleterNoAtSymbol(t *testing.T) {
	members := []map[string]interface{}{
		{"member_id": "alice-001", "member_name": "Alice"},
	}
	c := newChatMentionCompleter(func() []map[string]interface{} {
		return members
	})

	// Typing without @ should not suggest members.
	candidates, _ := c.Do([]rune("Hello A"), 7)
	if len(candidates) != 0 {
		t.Errorf("expected 0 candidates, got %d", len(candidates))
	}
}

func TestChatMentionCompleterUnicodeName(t *testing.T) {
	members := []map[string]interface{}{
		{"member_id": "xiaoming-001", "member_name": "小明"},
	}
	c := newChatMentionCompleter(func() []map[string]interface{} {
		return members
	})

	candidates, offset := c.Do([]rune("@小"), 2)
	if offset != 0 {
		t.Errorf("offset = %d, want 0", offset)
	}
	if len(candidates) != 1 {
		t.Fatalf("expected 1 candidate, got %d", len(candidates))
	}
	if string(candidates[0]) != "@xiaoming-001 " {
		t.Errorf("candidate = %q, want \"@xiaoming-001 \"", string(candidates[0]))
	}
}

func TestChatMentionCompleterAllPrefix(t *testing.T) {
	members := []map[string]interface{}{
		{"member_id": "alice-001", "member_name": "Alice"},
	}
	c := newChatMentionCompleter(func() []map[string]interface{} {
		return members
	})

	// Typing "@al" should match both "Alice" (name) and "@all".
	candidates, _ := c.Do([]rune("@al"), 3)
	if len(candidates) != 2 {
		t.Fatalf("expected 2 candidates, got %d", len(candidates))
	}
}

func TestChatMentionCompleterTrailingSpace(t *testing.T) {
	members := []map[string]interface{}{
		{"member_id": "alice-001", "member_name": "Alice"},
	}
	c := newChatMentionCompleter(func() []map[string]interface{} {
		return members
	})

	candidates, _ := c.Do([]rune("@"), 1)
	for _, cand := range candidates {
		s := string(cand)
		if !strings.HasSuffix(s, " ") {
			t.Errorf("candidate %q should have trailing space", s)
		}
	}
}

// Regression test: @d + Tab should become @dawson (not @d@dawson).
func TestChatMentionCompleterNoPrefixDuplication(t *testing.T) {
	members := []map[string]interface{}{
		{"member_id": "dawson-001", "member_name": "dawson"},
	}
	c := newChatMentionCompleter(func() []map[string]interface{} {
		return members
	})

	// Simulate typing "@d" with cursor at position 2.
	candidates, offset := c.Do([]rune("@d"), 2)
	if offset != 0 {
		t.Errorf("offset = %d, want 0", offset)
	}
	if len(candidates) != 1 {
		t.Fatalf("expected 1 candidate, got %d", len(candidates))
	}

	// The candidate should be the full replacement string.
	if string(candidates[0]) != "@dawson-001 " {
		t.Errorf("candidate = %q, want \"@dawson-001 \"", string(candidates[0]))
	}
}

// Test that the completer prefers member_id over member_name for insertion.
func TestChatMentionCompleterInsertsMemberID(t *testing.T) {
	members := []map[string]interface{}{
		{"member_id": "agent-001", "member_name": "Research Agent"},
	}
	c := newChatMentionCompleter(func() []map[string]interface{} {
		return members
	})

	candidates, _ := c.Do([]rune("@Research"), 9)
	if len(candidates) != 1 {
		t.Fatalf("expected 1 candidate, got %d", len(candidates))
	}
	if string(candidates[0]) != "@agent-001 " {
		t.Errorf("candidate = %q, want \"@agent-001 \"", string(candidates[0]))
	}
}
