// Package message provides context builder tests.
package message

import (
	"strings"
	"testing"
	"time"

	"github.com/topsailai/agent-community/internal/models"
)

// makeGroup creates a test group.
func makeGroup(id, name, context string) *models.Group {
	return &models.Group{
		GroupID:       id,
		GroupName:     name,
		GroupContext:  context,
		CreateAtMs:    time.Now().Add(-24 * time.Hour).UnixMilli(),
		UpdateAtMs:    time.Now().Add(-1 * time.Hour).UnixMilli(),
	}
}

// makeMember creates a test member.
func makeMember(id, name string, memberType models.MemberType) models.GroupMember {
	return models.GroupMember{
		MemberID:          id,
		MemberName:        name,
		MemberType:        memberType,
		MemberDescription: "Test " + name,
	}
}

// makeMessage creates a test message.
func makeMessage(id, groupID, senderID string, senderType models.MemberType, text string, createAtMs int64) models.GroupMessage {
	return models.GroupMessage{
		MessageID:   id,
		GroupID:     groupID,
		SenderID:    senderID,
		SenderType:  senderType,
		MessageText: text,
		CreateAtMs:  createAtMs,
	}
}

// TestBuildInitContext verifies init context format.
func TestBuildInitContext(t *testing.T) {
	cb := NewContextBuilder()
	group := makeGroup("g1", "TestGroup", "This is a test group context")
	members := []models.GroupMember{
		makeMember("user1", "Alice", models.MemberTypeUser),
		makeMember("agent1", "Bot", models.MemberTypeWorkerAgent),
	}
	agentMember := &members[1]

	initCtx := cb.buildInitContext(group, members, agentMember)

	// Check group info
	if !strings.Contains(initCtx, "id=g1") {
		t.Error("missing group id")
	}
	if !strings.Contains(initCtx, "name=TestGroup") {
		t.Error("missing group name")
	}

	// Check group context
	if !strings.Contains(initCtx, "GROUP CONTEXT START") {
		t.Error("missing group context start marker")
	}
	if !strings.Contains(initCtx, "This is a test group context") {
		t.Error("missing group context content")
	}
	if !strings.Contains(initCtx, "GROUP CONTEXT END") {
		t.Error("missing group context end marker")
	}

	// Check members
	if !strings.Contains(initCtx, "id: user1") {
		t.Error("missing user1 member info")
	}
	if !strings.Contains(initCtx, "id: agent1") {
		t.Error("missing agent1 member info")
	}
	if !strings.Contains(initCtx, "type: user") {
		t.Error("missing user type")
	}
	if !strings.Contains(initCtx, "type: worker-agent") {
		t.Error("missing worker-agent type")
	}

	// Check ME section
	if !strings.Contains(initCtx, "ME (Receiver)") {
		t.Error("missing ME section")
	}
	if !strings.Contains(initCtx, "I AM `Bot`(agent1)") {
		t.Error("missing agent identity")
	}
}

// TestBuildMessageContext verifies message context format.
func TestBuildMessageContext(t *testing.T) {
	cb := NewContextBuilder()
	now := time.Now().UnixMilli()

	messages := []models.GroupMessage{
		makeMessage("m1", "g1", "user1", models.MemberTypeUser, "Hello", now-2000),
		makeMessage("m2", "g1", "agent1", models.MemberTypeWorkerAgent, "Hi there", now-1000),
	}

	msgCtx := cb.buildMessageContext(messages)

	if !strings.Contains(msgCtx, "Messages") {
		t.Error("missing Messages header")
	}
	if !strings.Contains(msgCtx, "sender: id=user1") {
		t.Error("missing user1 sender info")
	}
	if !strings.Contains(msgCtx, "Hello") {
		t.Error("missing Hello message")
	}
	if !strings.Contains(msgCtx, "sender: id=agent1") {
		t.Error("missing agent1 sender info")
	}
	if !strings.Contains(msgCtx, "Hi there") {
		t.Error("missing Hi there message")
	}

	// Should have --- separators between messages
	if !strings.Contains(msgCtx, "---") {
		t.Error("missing --- separator between messages")
	}
}

// TestBuildMessageContextEmpty verifies empty message list.
func TestBuildMessageContextEmpty(t *testing.T) {
	cb := NewContextBuilder()
	msgCtx := cb.buildMessageContext([]models.GroupMessage{})
	if msgCtx != "" {
		t.Errorf("expected empty string, got %q", msgCtx)
	}
}

// TestBuildMessageContextDeletedMessage verifies deleted messages are skipped.
func TestBuildMessageContextDeletedMessage(t *testing.T) {
	cb := NewContextBuilder()
	now := time.Now().UnixMilli()

	messages := []models.GroupMessage{
		makeMessage("m1", "g1", "user1", models.MemberTypeUser, "Hello", now-2000),
		{MessageID: "m2", GroupID: "g1", SenderID: "agent1", SenderType: models.MemberTypeWorkerAgent, MessageText: "Deleted", CreateAtMs: now - 1000, IsDeleted: true},
	}

	msgCtx := cb.buildMessageContext(messages)
	if strings.Contains(msgCtx, "Deleted") {
		t.Error("deleted message should not appear in context")
	}
	if !strings.Contains(msgCtx, "Hello") {
		t.Error("non-deleted message should appear")
	}
}
// TestBuildMessageContextSeparator verifies --- separators between messages.
func TestBuildMessageContextSeparator(t *testing.T) {
	cb := NewContextBuilder()
	now := time.Now().UnixMilli()

	messages := []models.GroupMessage{
		makeMessage("m1", "g1", "user1", models.MemberTypeUser, "Hello", now-2000),
		makeMessage("m2", "g1", "agent1", models.MemberTypeWorkerAgent, "Hi there", now-1000),
	}

	msgCtx := cb.buildMessageContext(messages)

	// Should have --- between messages
	parts := strings.Split(msgCtx, "\n---\n")
	if len(parts) < 3 {
		t.Errorf("expected --- separators between messages, got %q", msgCtx)
	}

	// Should start with --- after Messages header
	if !strings.Contains(msgCtx, "## Messages\n\n---\n") {
		t.Errorf("expected --- after Messages header, got %q", msgCtx)
	}

	// Should end with trailing ---
	if !strings.HasSuffix(msgCtx, "---\n") {
		t.Errorf("expected trailing ---, got %q", msgCtx)
	}
}


// TestBuildContextWithoutLastRead verifies context building without last_read_message_id.
func TestBuildContextWithoutLastRead(t *testing.T) {
	cb := NewContextBuilder()
	group := makeGroup("g1", "TestGroup", "Context")
	members := []models.GroupMember{
		makeMember("user1", "Alice", models.MemberTypeUser),
		makeMember("agent1", "Bot", models.MemberTypeWorkerAgent),
	}
	agentMember := &members[1]
	now := time.Now().UnixMilli()

	allMessages := []models.GroupMessage{
		makeMessage("m1", "g1", "user1", models.MemberTypeUser, "Old message", now-int64(25*time.Hour/time.Millisecond)),
		makeMessage("m2", "g1", "user1", models.MemberTypeUser, "Recent message", now-int64(1*time.Hour/time.Millisecond)),
	}

	pendingMsg := makeMessage("m3", "g1", "user1", models.MemberTypeUser, "Pending", now)

	context, err := cb.BuildContext(group, members, agentMember, allMessages, "", &pendingMsg)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}

	// Should contain init context
	if !strings.Contains(context, "TestGroup") {
		t.Error("missing group name in context")
	}

	// Should contain recent message (within 1 day)
	if !strings.Contains(context, "Recent message") {
		t.Error("missing recent message")
	}

	// Should contain pending message
	if !strings.Contains(context, "Pending") {
		t.Error("missing pending message")
	}

	// Old message (older than 1 day) should not be included
	if strings.Contains(context, "Old message") {
		t.Error("old message should not be in recent context")
	}
}

// TestBuildContextWithLastRead verifies context building with last_read_message_id.
func TestBuildContextWithLastRead(t *testing.T) {
	cb := NewContextBuilder()
	group := makeGroup("g1", "TestGroup", "Context")
	members := []models.GroupMember{
		makeMember("user1", "Alice", models.MemberTypeUser),
		makeMember("agent1", "Bot", models.MemberTypeWorkerAgent),
	}
	agentMember := &members[1]
	now := time.Now().UnixMilli()

	allMessages := []models.GroupMessage{
		makeMessage("m1", "g1", "user1", models.MemberTypeUser, "Message 1", now-3000),
		makeMessage("m2", "g1", "agent1", models.MemberTypeWorkerAgent, "Message 2", now-2000),
		makeMessage("m3", "g1", "user1", models.MemberTypeUser, "Message 3", now-1000),
	}

	pendingMsg := makeMessage("m3", "g1", "user1", models.MemberTypeUser, "Message 3", now-1000)

	context, err := cb.BuildContext(group, members, agentMember, allMessages, "m1", &pendingMsg)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}

	// Should contain all messages from m1 to m3
	if !strings.Contains(context, "Message 1") {
		t.Error("missing Message 1 (last_read)")
	}
	if !strings.Contains(context, "Message 2") {
		t.Error("missing Message 2")
	}
	if !strings.Contains(context, "Message 3") {
		t.Error("missing Message 3 (pending)")
	}

	// Init context should NOT be present when last_read_message_id exists
	if strings.Contains(context, "## group_member") {
		t.Error("init context should not be included when last_read_message_id exists")
	}
	if strings.Contains(context, "ME (Receiver)") {
		t.Error("ME section should not be included when last_read_message_id exists")
	}
	if strings.Contains(context, "GROUP CONTEXT START") {
		t.Error("group context should not be included when last_read_message_id exists")
	}
}

// TestBuildContextNilGroup verifies error on nil group.
func TestBuildContextNilGroup(t *testing.T) {
	cb := NewContextBuilder()
	members := []models.GroupMember{
		makeMember("agent1", "Bot", models.MemberTypeWorkerAgent),
	}
	agentMember := &members[0]
	now := time.Now().UnixMilli()
	pendingMsg := makeMessage("m1", "g1", "user1", models.MemberTypeUser, "Test", now)

	_, err := cb.BuildContext(nil, members, agentMember, nil, "", &pendingMsg)
	if err == nil {
		t.Error("expected error for nil group")
	}
}

// TestBuildContextNilAgent verifies error on nil agent member.
func TestBuildContextNilAgent(t *testing.T) {
	cb := NewContextBuilder()
	group := makeGroup("g1", "TestGroup", "Context")
	now := time.Now().UnixMilli()
	pendingMsg := makeMessage("m1", "g1", "user1", models.MemberTypeUser, "Test", now)

	_, err := cb.BuildContext(group, nil, nil, nil, "", &pendingMsg)
	if err == nil {
		t.Error("expected error for nil agent member")
	}
}

// TestBuildContextNilPendingMessage verifies error on nil pending message.
func TestBuildContextNilPendingMessage(t *testing.T) {
	cb := NewContextBuilder()
	group := makeGroup("g1", "TestGroup", "Context")
	members := []models.GroupMember{
		makeMember("agent1", "Bot", models.MemberTypeWorkerAgent),
	}
	agentMember := &members[0]

	_, err := cb.BuildContext(group, members, agentMember, nil, "", nil)
	if err == nil {
		t.Error("expected error for nil pending message")
	}
}

// TestGetRecentMessages verifies recent message filtering.
func TestGetRecentMessages(t *testing.T) {
	cb := NewContextBuilder()
	now := time.Now().UnixMilli()

	allMessages := []models.GroupMessage{
		makeMessage("m1", "g1", "user1", models.MemberTypeUser, "Old", now-int64(25*time.Hour/time.Millisecond)),
		makeMessage("m2", "g1", "user1", models.MemberTypeUser, "Recent", now-int64(1*time.Hour/time.Millisecond)),
		makeMessage("m3", "g1", "user1", models.MemberTypeUser, "Future", now+1000),
	}

	pendingMsg := makeMessage("m2", "g1", "user1", models.MemberTypeUser, "Recent", now-int64(1*time.Hour/time.Millisecond))

	recent := cb.getRecentMessages(allMessages, &pendingMsg, 24*time.Hour)

	// Should include only 1 message (pending message m2, not duplicated)
	if len(recent) != 1 {
		t.Fatalf("expected 1 recent message, got %d", len(recent))
	}

	// Should include pending message
	foundPending := false
	for _, m := range recent {
		if m.MessageID == "m2" {
			foundPending = true
			break
		}
	}
	if !foundPending {
		t.Error("pending message should be included")
	}
}

// TestGetMessagesFromLastRead verifies message range extraction.
func TestGetMessagesFromLastRead(t *testing.T) {
	cb := NewContextBuilder()
	now := time.Now().UnixMilli()

	allMessages := []models.GroupMessage{
		makeMessage("m1", "g1", "user1", models.MemberTypeUser, "Msg1", now-3000),
		makeMessage("m2", "g1", "user1", models.MemberTypeUser, "Msg2", now-2000),
		makeMessage("m3", "g1", "user1", models.MemberTypeUser, "Msg3", now-1000),
		makeMessage("m4", "g1", "user1", models.MemberTypeUser, "Msg4", now),
	}

	pendingMsg := makeMessage("m3", "g1", "user1", models.MemberTypeUser, "Msg3", now-1000)

	result := cb.getMessagesFromLastRead(allMessages, "m1", &pendingMsg)

	if len(result) != 3 {
		t.Fatalf("expected 3 messages, got %d", len(result))
	}
	if result[0].MessageID != "m1" {
		t.Errorf("first message = %v, want m1", result[0].MessageID)
	}
	if result[2].MessageID != "m3" {
		t.Errorf("last message = %v, want m3", result[2].MessageID)
	}
}

// TestBuildAgentResponseMessage verifies agent response message building.
func TestBuildAgentResponseMessage(t *testing.T) {
	cb := NewContextBuilder()
	agentMember := &models.GroupMember{
		MemberID:   "agent1",
		MemberName: "Bot",
		MemberType: models.MemberTypeWorkerAgent,
	}

	msg := cb.BuildAgentResponseMessage("g1", agentMember, "Response text", "pending1", "resp1")

	if msg.GroupID != "g1" {
		t.Errorf("group_id = %v", msg.GroupID)
	}
	if msg.MessageID != "resp1" {
		t.Errorf("message_id = %v", msg.MessageID)
	}
	if msg.MessageText != "Response text" {
		t.Errorf("message_text = %v", msg.MessageText)
	}
	if msg.SenderID != "agent1" {
		t.Errorf("sender_id = %v", msg.SenderID)
	}
	if msg.SenderType != models.MemberTypeWorkerAgent {
		t.Errorf("sender_type = %v", msg.SenderType)
	}
	if msg.ProcessedMsgID != "pending1" {
		t.Errorf("processed_msg_id = %v", msg.ProcessedMsgID)
	}
	if msg.IsDeleted {
		t.Error("response message should not be deleted")
	}
}

// TestBuildSystemErrorMessage verifies system error message building.
func TestBuildSystemErrorMessage(t *testing.T) {
	cb := NewContextBuilder()
	managerAgent := &models.GroupMember{
		MemberID:   "mgr1",
		MemberName: "Manager",
		MemberType: models.MemberTypeManagerAgent,
	}

	msg := cb.BuildSystemErrorMessage("g1", managerAgent, "Agent timeout", "pending1", "err1")

	if msg.GroupID != "g1" {
		t.Errorf("group_id = %v", msg.GroupID)
	}
	if msg.MessageID != "err1" {
		t.Errorf("message_id = %v", msg.MessageID)
	}
	if msg.MessageText != "[System Error] Agent timeout" {
		t.Errorf("message_text = %v", msg.MessageText)
	}
	if msg.SenderID != "mgr1" {
		t.Errorf("sender_id = %v", msg.SenderID)
	}
	if msg.SenderType != models.MemberTypeManagerAgent {
		t.Errorf("sender_type = %v", msg.SenderType)
	}
	if msg.ProcessedMsgID != "pending1" {
		t.Errorf("processed_msg_id = %v", msg.ProcessedMsgID)
	}
}
