// Package main provides unit tests for chat mode and mention parsing.
package main

import (
	"bytes"
	"encoding/json"
	"fmt"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync"
	"testing"

	"github.com/topsailai/agent-community/internal/nats"
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


// --- Message deduplication tests ---

func TestIsMessageDisplayed(t *testing.T) {
	cm := newTestChatMode()
	cm.displayedMsgIDs = make(map[string]struct{})

	if cm.isMessageDisplayed("msg-1") {
		t.Error("isMessageDisplayed() = true, want false for unknown msgID")
	}

	cm.markMessageDisplayed("msg-1")
	if !cm.isMessageDisplayed("msg-1") {
		t.Error("isMessageDisplayed() = false, want true after marking")
	}
}

func TestMarkMessageDisplayed(t *testing.T) {
	cm := newTestChatMode()
	cm.displayedMsgIDs = make(map[string]struct{})

	cm.markMessageDisplayed("msg-a")
	cm.markMessageDisplayed("msg-b")

	if !cm.isMessageDisplayed("msg-a") {
		t.Error("expected msg-a to be displayed")
	}
	if !cm.isMessageDisplayed("msg-b") {
		t.Error("expected msg-b to be displayed")
	}
	if cm.isMessageDisplayed("msg-c") {
		t.Error("expected msg-c to NOT be displayed")
	}
}

func TestClearDisplayedMessages(t *testing.T) {
	cm := newTestChatMode()
	cm.displayedMsgIDs = make(map[string]struct{})

	cm.markMessageDisplayed("msg-1")
	cm.markMessageDisplayed("msg-2")
	cm.clearDisplayedMessages()

	if cm.isMessageDisplayed("msg-1") {
		t.Error("expected msg-1 to be cleared")
	}
	if cm.isMessageDisplayed("msg-2") {
		t.Error("expected msg-2 to be cleared")
	}
}

func TestDisplayEventDeduplication(t *testing.T) {
	cm := newTestChatMode()
	cm.groupID = "g1"
	cm.displayedMsgIDs = make(map[string]struct{})

	// First event with message_id should be displayed.
	event1 := &nats.PendingPublishMessage{
		Type:    "message",
		Action:  "create",
		GroupID: "g1",
		Data: map[string]interface{}{
			"message_id":   "msg-1",
			"sender_id":    "u1",
			"sender_name":  "Alice",
			"sender_type":  "user",
			"message_text": "Hello",
			"create_at_ms": float64(1718205045000),
		},
	}

	// Second event with same message_id should be skipped.
	event2 := &nats.PendingPublishMessage{
		Type:    "message",
		Action:  "create",
		GroupID: "g1",
		Data: map[string]interface{}{
			"message_id":   "msg-1",
			"sender_id":    "u1",
			"sender_name":  "Alice.local",
			"sender_type":  "user",
			"message_text": "Hello",
			"create_at_ms": float64(1718205045000),
		},
	}

	// Third event with different message_id should be displayed.
	event3 := &nats.PendingPublishMessage{
		Type:    "message",
		Action:  "create",
		GroupID: "g1",
		Data: map[string]interface{}{
			"message_id":   "msg-2",
			"sender_id":    "u2",
			"sender_name":  "Bob",
			"sender_type":  "user",
			"message_text": "World",
			"create_at_ms": float64(1718205045001),
		},
	}

	// Simulate display: mark msg-1 as already displayed (as if from local echo).
	cm.markMessageDisplayed("msg-1")

	if !cm.isMessageDisplayed("msg-1") {
		t.Fatal("msg-1 should be marked displayed")
	}
	if cm.isMessageDisplayed("msg-2") {
		t.Fatal("msg-2 should NOT be marked displayed yet")
	}

	// displayEvent should skip event2 because msg-1 is already displayed.
	// We cannot easily capture fmt.Println output here, but we can verify the state.
	cm.displayEvent(event1)
	cm.displayEvent(event2)
	cm.displayEvent(event3)

	if !cm.isMessageDisplayed("msg-1") {
		t.Error("msg-1 should still be displayed")
	}
	if !cm.isMessageDisplayed("msg-2") {
		t.Error("msg-2 should be marked displayed after event3")
	}
}

func TestDisplayEventDifferentGroup(t *testing.T) {
	cm := newTestChatMode()
	cm.groupID = "g1"
	cm.displayedMsgIDs = make(map[string]struct{})

	event := &nats.PendingPublishMessage{
		Type:    "message",
		Action:  "create",
		GroupID: "g2",
		Data: map[string]interface{}{
			"message_id":   "msg-1",
			"sender_id":    "u1",
			"sender_name":  "Alice",
			"sender_type":  "user",
			"message_text": "Hello",
			"create_at_ms": float64(1718205045000),
		},
	}

	cm.displayEvent(event)

	if cm.isMessageDisplayed("msg-1") {
		t.Error("message from different group should not be marked displayed")
	}
}
func TestDisplayEventNonMessageType(t *testing.T) {
	cm := newTestChatMode()
	cm.groupID = "g1"
	cm.displayedMsgIDs = make(map[string]struct{})

	event := &nats.PendingPublishMessage{
		Type:    "group",
		Action:  "create",
		GroupID: "g1",
		Data: map[string]interface{}{
			"group_id":   "g1",
			"group_name": "TestGroup",
		},
	}

	cm.displayEvent(event)

	// Non-message events should not interact with displayedMsgIDs.
	if cm.isMessageDisplayed("g1") {
		t.Error("non-message event should not mark anything displayed")
	}
}

func TestMessageDeduplicationConcurrency(t *testing.T) {
	cm := newTestChatMode()
	cm.displayedMsgIDs = make(map[string]struct{})

	var wg sync.WaitGroup
	for i := 0; i < 100; i++ {
		wg.Add(1)
		go func(idx int) {
			defer wg.Done()
			msgID := fmt.Sprintf("msg-%d", idx)
			cm.markMessageDisplayed(msgID)
			if !cm.isMessageDisplayed(msgID) {
				t.Errorf("msg %s should be displayed after marking", msgID)
			}
		}(i)
	}
	wg.Wait()

	for i := 0; i < 100; i++ {
		msgID := fmt.Sprintf("msg-%d", i)
		if !cm.isMessageDisplayed(msgID) {
			t.Errorf("msg %s should be displayed after concurrent marking", msgID)
		}
	}
}

// fakeNATSManager is a test double for the natsManager interface used by ChatMode.
type fakeNATSManager struct {
	mu           sync.Mutex
	subscribed   bool
	groupID      string
	unsubscribed bool
	onEvent      func(*nats.PendingPublishMessage)
	subscribeErr error
}

func (f *fakeNATSManager) SubscribeGroup(groupID string) error {
	f.mu.Lock()
	defer f.mu.Unlock()
	if f.subscribeErr != nil {
		return f.subscribeErr
	}
	f.subscribed = true
	f.groupID = groupID
	return nil
}

func (f *fakeNATSManager) Unsubscribe() error {
	f.mu.Lock()
	defer f.mu.Unlock()
	f.unsubscribed = true
	return nil
}

func (f *fakeNATSManager) SetOnEvent(handler func(*nats.PendingPublishMessage)) {
	f.mu.Lock()
	defer f.mu.Unlock()
	f.onEvent = handler
}

func (f *fakeNATSManager) GetOnEvent() func(*nats.PendingPublishMessage) {
	f.mu.Lock()
	defer f.mu.Unlock()
	return f.onEvent
}

func (f *fakeNATSManager) IsSubscribed() bool {
	f.mu.Lock()
	defer f.mu.Unlock()
	return f.subscribed
}

func (f *fakeNATSManager) IsUnsubscribed() bool {
	f.mu.Lock()
	defer f.mu.Unlock()
	return f.unsubscribed
}

func (f *fakeNATSManager) SubscribedGroup() string {
	f.mu.Lock()
	defer f.mu.Unlock()
	return f.groupID
}

// newChatModeWithServer creates a ChatMode wired to an httptest server and a fake NATS manager.
func newChatModeWithServer(t *testing.T, handler http.HandlerFunc) (*ChatMode, *bytes.Buffer, *fakeNATSManager) {
	server := httptest.NewServer(handler)
	t.Cleanup(server.Close)
	client := NewAPIClient(server.URL)
	buf := &bytes.Buffer{}
	nm := &fakeNATSManager{}
	cm := NewChatMode(client, nm)
	cm.out = buf
	return cm, buf, nm
}

// membersHandler returns a handler that serves the member list endpoint.
func membersHandler(members []map[string]interface{}) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodGet {
			http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
			return
		}
		resp := map[string]interface{}{
			"data": map[string]interface{}{
				"items": members,
				"total": len(members),
			},
		}
		w.Header().Set("Content-Type", "application/json")
		_ = json.NewEncoder(w).Encode(resp)
	}
}

// sendMessageHandler returns a handler that accepts a message and echoes it back with an id.
func sendMessageHandler(messageID string) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodPost {
			http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
			return
		}
		var payload map[string]interface{}
		if err := json.NewDecoder(r.Body).Decode(&payload); err != nil {
			http.Error(w, err.Error(), http.StatusBadRequest)
			return
		}
		resp := map[string]interface{}{
			"data": map[string]interface{}{
				"message_id":    messageID,
				"group_id":      strings.TrimPrefix(r.URL.Path, "/api/v1/groups/"),
				"message_text":  payload["message_text"],
				"sender_id":     "u1",
				"sender_type":   "user",
				"create_at_ms":  1704067200000,
			},
		}
		w.Header().Set("Content-Type", "application/json")
		_ = json.NewEncoder(w).Encode(resp)
	}
}

func TestRefreshMembers_Success(t *testing.T) {
	members := []map[string]interface{}{
		{"member_id": "m1", "member_name": "Alice", "member_type": "user"},
		{"member_id": "a1", "member_name": "Agent1", "member_type": "worker-agent"},
	}
	cm, _, _ := newChatModeWithServer(t, membersHandler(members))
	cm.groupID = "group-123"

	if err := cm.refreshMembers(); err != nil {
		t.Fatalf("refreshMembers() error = %v", err)
	}

	cm.mu.Lock()
	got := cm.members
	cm.mu.Unlock()
	if len(got) != 2 {
		t.Fatalf("members length = %d, want 2", len(got))
	}
	if got[0]["member_id"] != "m1" {
		t.Errorf("first member id = %v, want m1", got[0]["member_id"])
	}
}

func TestRefreshMembers_APIError(t *testing.T) {
	cm, _, _ := newChatModeWithServer(t, func(w http.ResponseWriter, r *http.Request) {
		http.Error(w, `{"error":"group not found"}`, http.StatusNotFound)
	})
	cm.groupID = "group-missing"

	if err := cm.refreshMembers(); err == nil {
		t.Fatal("refreshMembers() expected error, got nil")
	}
}

func TestShowMembers(t *testing.T) {
	cm, buf, _ := newChatModeWithServer(t, membersHandler(nil))
	cm.groupID = "group-123"
	cm.members = []map[string]interface{}{
		{"member_id": "m1", "member_name": "Alice", "member_type": "user"},
		{"member_id": "a1", "member_name": "Agent1", "member_type": "worker-agent"},
	}

	cm.showMembers()

	out := buf.String()
	if !strings.Contains(out, "Alice") {
		t.Errorf("showMembers output missing Alice: %s", out)
	}
	if !strings.Contains(out, "Agent1") {
		t.Errorf("showMembers output missing Agent1: %s", out)
	}
}

func TestShowChatHelp(t *testing.T) {
	cm, buf, _ := newChatModeWithServer(t, membersHandler(nil))
	cm.showChatHelp()

	out := buf.String()
	for _, want := range []string{"/members", "/help", "/exit"} {
		if !strings.Contains(out, want) {
			t.Errorf("showChatHelp output missing %q: %s", want, out)
		}
	}
}

func TestSendChatMessage_Success(t *testing.T) {
	cm, buf, _ := newChatModeWithServer(t, sendMessageHandler("msg-001"))
	cm.groupID = "group-123"
	cm.userID = "u1"
	cm.userName = "Alice"

	if err := cm.SendChatMessage("Hello team"); err != nil {
		t.Fatalf("SendChatMessage() error = %v", err)
	}

	out := buf.String()
	if !strings.Contains(out, "Hello team") {
		t.Errorf("output missing sent message text: %s", out)
	}
	if !strings.Contains(out, "Alice") {
		t.Errorf("output missing sender name: %s", out)
	}
	if !cm.isMessageDisplayed("msg-001") {
		t.Error("expected message id to be marked displayed")
	}
}

func TestSendChatMessage_APIError(t *testing.T) {
	cm, _, _ := newChatModeWithServer(t, func(w http.ResponseWriter, r *http.Request) {
		http.Error(w, `{"error":"forbidden"}`, http.StatusForbidden)
	})
	cm.groupID = "group-123"

	if err := cm.SendChatMessage("Hello"); err == nil {
		t.Fatal("SendChatMessage() expected error, got nil")
	}
}

func TestHandleInput_Help(t *testing.T) {
	cm, buf, _ := newChatModeWithServer(t, membersHandler(nil))
	cm.groupID = "group-123"
	cm.active = true

	cm.handleInput("/help")

	out := buf.String()
	if !strings.Contains(out, "/members") {
		t.Errorf("help output missing /members: %s", out)
	}
}

func TestHandleInput_Members(t *testing.T) {
	cm, buf, _ := newChatModeWithServer(t, membersHandler(nil))
	cm.groupID = "group-123"
	cm.active = true
	cm.members = []map[string]interface{}{
		{"member_id": "m1", "member_name": "Alice", "member_type": "user"},
	}

	cm.handleInput("/members")

	out := buf.String()
	if !strings.Contains(out, "Alice") {
		t.Errorf("members output missing Alice: %s", out)
	}
}

func TestHandleInput_Exit(t *testing.T) {
	cm, _, nm := newChatModeWithServer(t, membersHandler(nil))
	cm.groupID = "group-123"
	cm.active = true
	cm.natsManager = nm

	cm.handleInput("/exit")

	if cm.active {
		t.Error("expected chat mode to be inactive after /exit")
	}
	if !nm.IsUnsubscribed() {
		t.Error("expected Unsubscribe to be called on exit")
	}
}

func TestHandleInput_SendMessage(t *testing.T) {
	cm, buf, _ := newChatModeWithServer(t, sendMessageHandler("msg-002"))
	cm.groupID = "group-123"
	cm.userID = "u1"
	cm.userName = "Alice"
	cm.active = true

	cm.handleInput("Hello everyone")

	out := buf.String()
	if !strings.Contains(out, "Hello everyone") {
		t.Errorf("output missing sent message: %s", out)
	}
}

func TestHandleInput_SendMessageError(t *testing.T) {
	cm, buf, _ := newChatModeWithServer(t, func(w http.ResponseWriter, r *http.Request) {
		http.Error(w, `{"error":"send failed"}`, http.StatusInternalServerError)
	})
	cm.groupID = "group-123"
	cm.active = true

	cm.handleInput("Hello")

	out := buf.String()
	if !strings.Contains(out, "Failed to send") {
		t.Errorf("output missing error message: %s", out)
	}
}

func TestHandleInput_UnknownCommand(t *testing.T) {
	cm, buf, _ := newChatModeWithServer(t, membersHandler(nil))
	cm.groupID = "group-123"
	cm.active = true

	cm.handleInput("/unknown")

	out := buf.String()
	if !strings.Contains(out, "Unknown command") {
		t.Errorf("output missing unknown command error: %s", out)
	}
}

func TestHandleInput_EmptyLine(t *testing.T) {
	cm, buf, _ := newChatModeWithServer(t, membersHandler(nil))
	cm.groupID = "group-123"
	cm.active = true

	cm.handleInput("   ")

	if buf.Len() != 0 {
		t.Errorf("expected no output for empty line, got %q", buf.String())
	}
}

func TestLeaveChat_WhenInactive(t *testing.T) {
	cm, _, nm := newChatModeWithServer(t, membersHandler(nil))
	cm.active = false

	cm.LeaveChat() // should be a no-op

	if nm.IsUnsubscribed() {
		t.Error("Unsubscribe should not be called when chat was inactive")
	}
}

func TestLeaveChat_RestoresHandler(t *testing.T) {
	members := []map[string]interface{}{
		{"member_id": "u1", "member_name": "Alice", "member_type": "user"},
	}
	cm, _, nm := newChatModeWithServer(t, membersHandler(members))
	cm.groupID = "group-123"
	cm.userID = "u1"
	cm.userName = "Alice"
	cm.active = true

	restoredCalled := false
	cm.oldHandler = func(event *nats.PendingPublishMessage) {
		restoredCalled = true
	}

	cm.LeaveChat()

	if cm.active {
		t.Error("expected chat to be inactive after LeaveChat")
	}
	if !nm.IsUnsubscribed() {
		t.Error("expected Unsubscribe to be called")
	}
	handler := nm.GetOnEvent()
	if handler == nil {
		t.Fatal("expected restored handler to be non-nil")
	}
	handler(nil)
	if !restoredCalled {
		t.Error("expected original handler to be restored and invoked")
	}
}
