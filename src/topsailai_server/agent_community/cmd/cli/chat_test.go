// Package main provides unit tests for chat mode and mention parsing.
package main

import (
	"testing"
)

// newTestChatMode creates a ChatMode for testing without external dependencies.
func newTestChatMode() *ChatMode {
	return &ChatMode{
		groupID:  "g1",
		userID:   "u1",
		userName: "Alice",
		members:  nil,
	}
}

func TestParseMentionsEmpty(t *testing.T) {
	cm := newTestChatMode()
	cm.members = []map[string]interface{}{
		{"member_id": "m1", "member_name": "Alice", "member_type": "user"},
	}
	mentions := cm.parseMentions("Hello world")
	if len(mentions) != 0 {
		t.Errorf("parseMentions() = %v, want empty", mentions)
	}
}

func TestParseMentionsSingleByID(t *testing.T) {
	cm := newTestChatMode()
	cm.members = []map[string]interface{}{
		{"member_id": "m1", "member_name": "Alice", "member_type": "user"},
	}
	mentions := cm.parseMentions("Hello @m1")
	if len(mentions) != 1 {
		t.Fatalf("parseMentions() = %v, want 1 mention", mentions)
	}
	if mentions[0]["member_id"] != "m1" {
		t.Errorf("member_id = %q, want %q", mentions[0]["member_id"], "m1")
	}
	if mentions[0]["member_name"] != "Alice" {
		t.Errorf("member_name = %q, want %q", mentions[0]["member_name"], "Alice")
	}
	if mentions[0]["member_type"] != "user" {
		t.Errorf("member_type = %q, want %q", mentions[0]["member_type"], "user")
	}
}

func TestParseMentionsSingleByName(t *testing.T) {
	cm := newTestChatMode()
	cm.members = []map[string]interface{}{
		{"member_id": "m1", "member_name": "Alice", "member_type": "user"},
	}
	mentions := cm.parseMentions("Hello @Alice")
	if len(mentions) != 1 {
		t.Fatalf("parseMentions() = %v, want 1 mention", mentions)
	}
	if mentions[0]["member_id"] != "m1" {
		t.Errorf("member_id = %q, want %q", mentions[0]["member_id"], "m1")
	}
	if mentions[0]["member_name"] != "Alice" {
		t.Errorf("member_name = %q, want %q", mentions[0]["member_name"], "Alice")
	}
}

func TestParseMentionsMultiple(t *testing.T) {
	cm := newTestChatMode()
	cm.members = []map[string]interface{}{
		{"member_id": "m1", "member_name": "Alice", "member_type": "user"},
		{"member_id": "m2", "member_name": "Bob", "member_type": "worker-agent"},
	}
	mentions := cm.parseMentions("@m1 and @Bob")
	if len(mentions) != 2 {
		t.Fatalf("parseMentions() = %v, want 2 mentions", mentions)
	}
	if mentions[0]["member_id"] != "m1" {
		t.Errorf("first mention member_id = %q, want %q", mentions[0]["member_id"], "m1")
	}
	if mentions[1]["member_id"] != "m2" {
		t.Errorf("second mention member_id = %q, want %q", mentions[1]["member_id"], "m2")
	}
}

func TestParseMentionsUnknown(t *testing.T) {
	cm := newTestChatMode()
	cm.members = []map[string]interface{}{
		{"member_id": "m1", "member_name": "Alice", "member_type": "user"},
	}
	mentions := cm.parseMentions("Hello @unknown")
	if len(mentions) != 1 {
		t.Fatalf("parseMentions() = %v, want 1 mention", mentions)
	}
	if mentions[0]["member_id"] != "unknown" {
		t.Errorf("member_id = %q, want %q", mentions[0]["member_id"], "unknown")
	}
	if mentions[0]["member_name"] != "unknown" {
		t.Errorf("member_name = %q, want %q", mentions[0]["member_name"], "unknown")
	}
	if mentions[0]["member_type"] != "user" {
		t.Errorf("member_type = %q, want %q", mentions[0]["member_type"], "user")
	}
}

func TestParseMentionsDeduplication(t *testing.T) {
	cm := newTestChatMode()
	cm.members = []map[string]interface{}{
		{"member_id": "m1", "member_name": "Alice", "member_type": "user"},
	}
	mentions := cm.parseMentions("@m1 @m1 @Alice")
	if len(mentions) != 1 {
		t.Fatalf("parseMentions() = %v, want 1 mention after dedup", mentions)
	}
	if mentions[0]["member_id"] != "m1" {
		t.Errorf("member_id = %q, want %q", mentions[0]["member_id"], "m1")
	}
}

func TestParseMentionsAgentType(t *testing.T) {
	cm := newTestChatMode()
	cm.members = []map[string]interface{}{
		{"member_id": "a1", "member_name": "Bot", "member_type": "manager-agent"},
	}
	mentions := cm.parseMentions("@a1")
	if len(mentions) != 1 {
		t.Fatalf("parseMentions() = %v, want 1 mention", mentions)
	}
	if mentions[0]["member_type"] != "manager-agent" {
		t.Errorf("member_type = %q, want %q", mentions[0]["member_type"], "manager-agent")
	}
}

func TestParseMentionsWithPunctuation(t *testing.T) {
	cm := newTestChatMode()
	cm.members = []map[string]interface{}{
		{"member_id": "m1", "member_name": "Alice", "member_type": "user"},
	}
	mentions := cm.parseMentions("Hello @m1, how are you?")
	if len(mentions) != 1 {
		t.Fatalf("parseMentions() = %v, want 1 mention", mentions)
	}
	if mentions[0]["member_id"] != "m1" {
		t.Errorf("member_id = %q, want %q", mentions[0]["member_id"], "m1")
	}
}

func TestParseMentionsEmptyMembers(t *testing.T) {
	cm := newTestChatMode()
	cm.members = []map[string]interface{}{}
	mentions := cm.parseMentions("Hello @m1")
	if len(mentions) != 1 {
		t.Fatalf("parseMentions() = %v, want 1 mention", mentions)
	}
	if mentions[0]["member_id"] != "m1" {
		t.Errorf("member_id = %q, want %q", mentions[0]["member_id"], "m1")
	}
	if mentions[0]["member_type"] != "user" {
		t.Errorf("member_type = %q, want %q", mentions[0]["member_type"], "user")
	}
}

func TestParseMentionsComplexText(t *testing.T) {
	cm := newTestChatMode()
	cm.members = []map[string]interface{}{
		{"member_id": "u1", "member_name": "Alice", "member_type": "user"},
		{"member_id": "a1", "member_name": "Bot", "member_type": "worker-agent"},
	}
	text := "Hey @Alice, can you ask @Bot to help? Also @u1 is here."
	mentions := cm.parseMentions(text)
	if len(mentions) != 2 {
		t.Fatalf("parseMentions() = %v, want 2 mentions", mentions)
	}
	// Should have Alice (by name) and Bot (by name), u1 is same as Alice so deduped.
	ids := make(map[string]bool)
	for _, m := range mentions {
		ids[m["member_id"].(string)] = true
	}
	if !ids["u1"] {
		t.Error("expected Alice (u1) in mentions")
	}
	if !ids["a1"] {
		t.Error("expected Bot (a1) in mentions")
	}
}

func TestParseMentionsNoAtSymbol(t *testing.T) {
	cm := newTestChatMode()
	cm.members = []map[string]interface{}{
		{"member_id": "m1", "member_name": "Alice", "member_type": "user"},
	}
	mentions := cm.parseMentions("Hello Alice m1")
	if len(mentions) != 0 {
		t.Errorf("parseMentions() = %v, want empty", mentions)
	}
}

func TestParseMentionsWhitespaceAfterAt(t *testing.T) {
	cm := newTestChatMode()
	cm.members = []map[string]interface{}{
		{"member_id": "m1", "member_name": "Alice", "member_type": "user"},
	}
	mentions := cm.parseMentions("Hello @ m1")
	if len(mentions) != 0 {
		t.Errorf("parseMentions() = %v, want empty (whitespace after @)", mentions)
	}
}

func TestParseMentionsUnicodeName(t *testing.T) {
	cm := newTestChatMode()
	cm.members = []map[string]interface{}{
		{"member_id": "m1", "member_name": "小明", "member_type": "user"},
	}
	mentions := cm.parseMentions("Hello @小明")
	if len(mentions) != 1 {
		t.Fatalf("parseMentions() = %v, want 1 mention", mentions)
	}
	if mentions[0]["member_id"] != "m1" {
		t.Errorf("member_id = %q, want %q", mentions[0]["member_id"], "m1")
	}
	if mentions[0]["member_name"] != "小明" {
		t.Errorf("member_name = %q, want %q", mentions[0]["member_name"], "小明")
	}
}

func TestParseMentionsEmojiName(t *testing.T) {
	cm := newTestChatMode()
	cm.members = []map[string]interface{}{
		{"member_id": "m1", "member_name": "🤖Bot", "member_type": "worker-agent"},
	}
	mentions := cm.parseMentions("Hello @🤖Bot")
	if len(mentions) != 1 {
		t.Fatalf("parseMentions() = %v, want 1 mention", mentions)
	}
	if mentions[0]["member_id"] != "m1" {
		t.Errorf("member_id = %q, want %q", mentions[0]["member_id"], "m1")
	}
}

func TestParseMentionsMultipleSameMember(t *testing.T) {
	cm := newTestChatMode()
	cm.members = []map[string]interface{}{
		{"member_id": "m1", "member_name": "Alice", "member_type": "user"},
	}
	mentions := cm.parseMentions("@Alice @Alice @Alice")
	if len(mentions) != 1 {
		t.Fatalf("parseMentions() = %v, want 1 mention after dedup", mentions)
	}
}

func TestParseMentionsIDAndNameSameMember(t *testing.T) {
	cm := newTestChatMode()
	cm.members = []map[string]interface{}{
		{"member_id": "m1", "member_name": "Alice", "member_type": "user"},
	}
	mentions := cm.parseMentions("@m1 @Alice")
	if len(mentions) != 1 {
		t.Fatalf("parseMentions() = %v, want 1 mention after dedup", mentions)
	}
	if mentions[0]["member_id"] != "m1" {
		t.Errorf("member_id = %q, want %q", mentions[0]["member_id"], "m1")
	}
}

func TestParseMentionsCaseSensitive(t *testing.T) {
	cm := newTestChatMode()
	cm.members = []map[string]interface{}{
		{"member_id": "m1", "member_name": "Alice", "member_type": "user"},
	}
	mentions := cm.parseMentions("@alice")
	// Case-sensitive: "alice" != "Alice"
	if len(mentions) != 1 {
		t.Fatalf("parseMentions() = %v, want 1 mention", mentions)
	}
	if mentions[0]["member_id"] != "alice" {
		t.Errorf("member_id = %q, want %q (case-sensitive)", mentions[0]["member_id"], "alice")
	}
	if mentions[0]["member_name"] != "alice" {
		t.Errorf("member_name = %q, want %q (case-sensitive)", mentions[0]["member_name"], "alice")
	}
}

func TestParseMentionsWithNewlines(t *testing.T) {
	cm := newTestChatMode()
	cm.members = []map[string]interface{}{
		{"member_id": "m1", "member_name": "Alice", "member_type": "user"},
		{"member_id": "m2", "member_name": "Bob", "member_type": "user"},
	}
	text := "Hello @m1\nHow are you @Bob?"
	mentions := cm.parseMentions(text)
	if len(mentions) != 2 {
		t.Fatalf("parseMentions() = %v, want 2 mentions", mentions)
	}
}

func TestParseMentionsAtEndOfString(t *testing.T) {
	cm := newTestChatMode()
	cm.members = []map[string]interface{}{
		{"member_id": "m1", "member_name": "Alice", "member_type": "user"},
	}
	mentions := cm.parseMentions("Hello @m1")
	if len(mentions) != 1 {
		t.Fatalf("parseMentions() = %v, want 1 mention", mentions)
	}
}

func TestParseMentionsOnlyAtSymbol(t *testing.T) {
	cm := newTestChatMode()
	cm.members = []map[string]interface{}{
		{"member_id": "m1", "member_name": "Alice", "member_type": "user"},
	}
	mentions := cm.parseMentions("@")
	if len(mentions) != 0 {
		t.Errorf("parseMentions() = %v, want empty", mentions)
	}
}

func TestParseMentionsSpecialCharsInID(t *testing.T) {
	cm := newTestChatMode()
	cm.members = []map[string]interface{}{
		{"member_id": "user-123_test", "member_name": "Alice", "member_type": "user"},
	}
	mentions := cm.parseMentions("Hello @user-123_test")
	if len(mentions) != 1 {
		t.Fatalf("parseMentions() = %v, want 1 mention", mentions)
	}
	if mentions[0]["member_id"] != "user-123_test" {
		t.Errorf("member_id = %q, want %q", mentions[0]["member_id"], "user-123_test")
	}
}
