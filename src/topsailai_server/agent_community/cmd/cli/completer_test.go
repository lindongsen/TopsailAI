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

// applyCompletion simulates chzyer/readline's actual behavior: the candidate is
// inserted at the cursor position without deleting any existing text. The
// offset return value is ignored because readline only uses it for candidate
// list alignment.
func applyCompletion(line []rune, pos int, cand []rune) string {
	newLine := append(line[:pos], cand...)
	newLine = append(newLine, line[pos:]...)
	return string(newLine)
}

func TestChatMentionCompleterEmptyMembers(t *testing.T) {
	c := newChatMentionCompleter(func() []map[string]interface{} {
		return nil
	})

	line := []rune("Hello @")
	pos := 7
	candidates, length := c.Do(line, pos)
	if length != 1 {
		t.Errorf("length = %d, want 1 (len of '@')", length)
	}
	if len(candidates) != 1 {
		t.Fatalf("expected 1 candidate, got %d", len(candidates))
	}
	if string(candidates[0]) != "all " {
		t.Errorf("candidate = %q, want \"all \"", string(candidates[0]))
	}
	got := applyCompletion(line, pos, candidates[0])
	if got != "Hello @all " {
		t.Errorf("completed line = %q, want \"Hello @all \"", got)
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

	candidates, length := c.Do([]rune("@"), 1)
	if length != 1 {
		t.Errorf("length = %d, want 1", length)
	}
	if len(candidates) != 4 {
		t.Fatalf("expected 4 candidates, got %d", len(candidates))
	}

	expected := map[string]bool{"alice-001 ": false, "bob-002 ": false, "charlie-003 ": false, "all ": false}
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

	// Typing "@a" should suggest alice-001, anna-003 and all.
	candidates, length := c.Do([]rune("@a"), 2)
	if length != 2 {
		t.Errorf("length = %d, want 2", length)
	}
	if len(candidates) != 3 {
		t.Fatalf("expected 3 candidates, got %d", len(candidates))
	}

	// Typing "@ali" should suggest the suffix "ce-001 " (matched by ID).
	line := []rune("@ali")
	candidates, length = c.Do(line, 4)
	if length != 4 {
		t.Errorf("length = %d, want 4", length)
	}
	if len(candidates) != 1 {
		t.Fatalf("expected 1 candidate (alice-001), got %d", len(candidates))
	}
	if string(candidates[0]) != "ce-001 " {
		t.Errorf("candidate = %q, want \"ce-001 \"", string(candidates[0]))
	}
	got := applyCompletion(line, 4, candidates[0])
	if got != "@alice-001 " {
		t.Errorf("completed line = %q, want \"@alice-001 \"", got)
	}
}

func TestChatMentionCompleterCaseInsensitive(t *testing.T) {
	members := []map[string]interface{}{
		{"member_id": "alice-001", "member_name": "Alice"},
	}
	c := newChatMentionCompleter(func() []map[string]interface{} {
		return members
	})

	// Typing "@a" should match "alice-001" (id) and "all".
	candidates, length := c.Do([]rune("@a"), 2)
	if length != 2 {
		t.Errorf("length = %d, want 2", length)
	}
	if len(candidates) != 2 {
		t.Fatalf("expected 2 candidates, got %d", len(candidates))
	}
	foundAlice := false
	for _, cand := range candidates {
		if string(cand) == "lice-001 " {
			foundAlice = true
			break
		}
	}
	if !foundAlice {
		t.Error("expected \"lice-001 \" among candidates for @a")
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
		t.Fatalf("expected 2 candidates (alice-001 + all), got %d", len(candidates))
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
	line := []rune("Hello @a")
	pos := 8
	candidates, length := c.Do(line, pos)
	if length != 2 {
		t.Errorf("length = %d, want 2 (len of '@a')", length)
	}
	if len(candidates) != 2 {
		t.Fatalf("expected 2 candidates (alice-001 + all), got %d", len(candidates))
	}
	foundAlice := false
	for _, cand := range candidates {
		if string(cand) == "lice-001 " {
			foundAlice = true
			break
		}
	}
	if !foundAlice {
		t.Error("expected \"lice-001 \" among candidates for Hello @a")
	}
	got := applyCompletion(line, pos, []rune("lice-001 "))
	if got != "Hello @alice-001 " {
		t.Errorf("completed line = %q, want \"Hello @alice-001 \"", got)
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

func TestChatMentionCompleterAllPrefix(t *testing.T) {
	members := []map[string]interface{}{
		{"member_id": "alice-001", "member_name": "Alice"},
	}
	c := newChatMentionCompleter(func() []map[string]interface{} {
		return members
	})

	// Typing "@al" should match "alice-001" (id) and "all".
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

// Regression test: @d + Tab should become @dawson-001 (not @d@dawson-001).
func TestChatMentionCompleterNoPrefixDuplication(t *testing.T) {
	members := []map[string]interface{}{
		{"member_id": "dawson-001", "member_name": "dawson"},
	}
	c := newChatMentionCompleter(func() []map[string]interface{} {
		return members
	})

	line := []rune("@d")
	pos := 2
	candidates, length := c.Do(line, pos)
	if length != 2 {
		t.Errorf("length = %d, want 2", length)
	}
	if len(candidates) != 1 {
		t.Fatalf("expected 1 candidate, got %d", len(candidates))
	}

	if string(candidates[0]) != "awson-001 " {
		t.Errorf("candidate = %q, want \"awson-001 \"", string(candidates[0]))
	}

	got := applyCompletion(line, pos, candidates[0])
	if got != "@dawson-001 " {
		t.Errorf("completed line = %q, want \"@dawson-001 \"", got)
	}
}

// Regression test: @worker + Tab should replace the partial word with @worker-1 .
func TestChatMentionCompleterReplacesPartialWord(t *testing.T) {
	members := []map[string]interface{}{
		{"member_id": "worker-1", "member_name": "Worker One"},
		{"member_id": "worker-2", "member_name": "Worker Two"},
	}
	c := newChatMentionCompleter(func() []map[string]interface{} {
		return members
	})

	line := []rune("@worker")
	pos := 7
	candidates, length := c.Do(line, pos)
	if length != 7 {
		t.Errorf("length = %d, want 7", length)
	}
	if len(candidates) != 2 {
		t.Fatalf("expected 2 candidates, got %d", len(candidates))
	}

	// Pick the first candidate and simulate readline insert-at-cursor.
	got := applyCompletion(line, pos, candidates[0])
	if got != "@worker-1 " && got != "@worker-2 " {
		t.Errorf("completed line = %q, want \"@worker-1 \" or \"@worker-2 \"", got)
	}
}

// Regression test: bare @ + Tab should not produce a double @.
func TestChatMentionCompleterBareAtNoDoubleAt(t *testing.T) {
	members := []map[string]interface{}{
		{"member_id": "worker-1", "member_name": "Worker One"},
	}
	c := newChatMentionCompleter(func() []map[string]interface{} {
		return members
	})

	line := []rune("@")
	pos := 1
	candidates, length := c.Do(line, pos)
	if length != 1 {
		t.Errorf("length = %d, want 1", length)
	}
	if len(candidates) != 2 {
		t.Fatalf("expected 2 candidates (worker-1 + all), got %d", len(candidates))
	}

	got := applyCompletion(line, pos, []rune("all "))
	if got != "@all " {
		t.Errorf("completed line for all = %q, want \"@all \"", got)
	}

	got = applyCompletion(line, pos, []rune("worker-1 "))
	if got != "@worker-1 " {
		t.Errorf("completed line for worker-1 = %q, want \"@worker-1 \"", got)
	}
}

// Regression test: non-mention prefix returns no candidates.
func TestChatMentionCompleterNonMentionNoCandidates(t *testing.T) {
	members := []map[string]interface{}{
		{"member_id": "alice-001", "member_name": "Alice"},
	}
	c := newChatMentionCompleter(func() []map[string]interface{} {
		return members
	})

	candidates, _ := c.Do([]rune("hello "), 6)
	if len(candidates) != 0 {
		t.Errorf("expected 0 candidates for non-mention prefix, got %d", len(candidates))
	}
}
