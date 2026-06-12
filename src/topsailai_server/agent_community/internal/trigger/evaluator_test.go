// Package trigger provides trigger evaluation tests.
package trigger

import (
	"context"
	"encoding/json"
	"testing"
	"time"

	"github.com/topsailai/agent-community/internal/models"
)

// makeMessage creates a test message with given parameters.
func makeMessage(id, senderID string, senderType models.MemberType, text, processedMsgID string, createAtMs int64) *models.GroupMessage {
	return &models.GroupMessage{
		MessageID:      id,
		SenderID:       senderID,
		SenderType:     senderType,
		MessageText:    text,
		ProcessedMsgID: processedMsgID,
		CreateAtMs:     createAtMs,
	}
}

// makeMember creates a test member.
func makeMember(id, name string, memberType models.MemberType) models.GroupMember {
	return models.GroupMember{
		MemberID:   id,
		MemberName: name,
		MemberType: memberType,
	}
}

// TestEvaluateAntiTriggerAgentSender verifies messages from agents are not triggered.
func TestEvaluateAntiTriggerAgentSender(t *testing.T) {
	e := NewEvaluator(10 * time.Minute)
	members := []models.GroupMember{
		makeMember("user1", "Alice", models.MemberTypeUser),
		makeMember("agent1", "Bot", models.MemberTypeWorkerAgent),
	}

	// Message from worker-agent should not trigger
	msg := makeMessage("msg1", "agent1", models.MemberTypeWorkerAgent, "Hello", "", time.Now().UnixMilli())
	result, err := e.Evaluate(context.Background(), msg, members, nil)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if result.ShouldTrigger {
		t.Error("expected no trigger for agent sender")
	}

	// Message from manager-agent should not trigger
	msg2 := makeMessage("msg2", "agent2", models.MemberTypeManagerAgent, "Hello", "", time.Now().UnixMilli())
	result2, err := e.Evaluate(context.Background(), msg2, members, nil)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if result2.ShouldTrigger {
		t.Error("expected no trigger for manager-agent sender")
	}
}

// TestEvaluateAntiTriggerProcessedMsgID verifies messages with processed_msg_id are not triggered.
func TestEvaluateAntiTriggerProcessedMsgID(t *testing.T) {
	e := NewEvaluator(10 * time.Minute)
	members := []models.GroupMember{
		makeMember("user1", "Alice", models.MemberTypeUser),
	}

	msg := makeMessage("msg1", "user1", models.MemberTypeUser, "Hello", "parent1", time.Now().UnixMilli())
	result, err := e.Evaluate(context.Background(), msg, members, nil)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if result.ShouldTrigger {
		t.Error("expected no trigger for message with processed_msg_id")
	}
}

// TestEvaluateSlidingWindow verifies the sliding window anti-loop protection.
func TestEvaluateSlidingWindow(t *testing.T) {
	e := NewEvaluator(10 * time.Minute)
	members := []models.GroupMember{
		makeMember("user1", "Alice", models.MemberTypeUser),
		makeMember("agent1", "Bot", models.MemberTypeWorkerAgent),
		makeMember("mgr1", "Manager", models.MemberTypeManagerAgent),
	}
	now := time.Now().UnixMilli()

	// Build context messages: 25 messages with target at index 15
	// Include 12 consecutive agent messages in the window around target
	contextMessages := make([]models.GroupMessage, 0, 25)

	// Messages 0-4: user messages
	for i := 0; i < 5; i++ {
		contextMessages = append(contextMessages, *makeMessage(
			"msg_u_"+string(rune('a'+i)), "user1", models.MemberTypeUser,
			"user msg", "", now-int64((25-i)*1000),
		))
	}

	// Messages 5-16: 12 consecutive agent messages
	for i := 0; i < 12; i++ {
		contextMessages = append(contextMessages, *makeMessage(
			"msg_a_"+string(rune('a'+i)), "agent1", models.MemberTypeWorkerAgent,
			"agent msg", "", now-int64((20-i)*1000),
		))
	}

	// Messages 17-24: user messages
	for i := 0; i < 8; i++ {
		contextMessages = append(contextMessages, *makeMessage(
			"msg_u2_"+string(rune('a'+i)), "user1", models.MemberTypeUser,
			"user msg", "", now-int64((8-i)*1000),
		))
	}

	// Target message from user at index 15 (in the middle of agent messages)
	targetMsg := makeMessage("target", "user1", models.MemberTypeUser, "Hello", "", now+1000)
	// Insert target into contextMessages at index 15
	contextMessages = append(contextMessages[:15], append([]models.GroupMessage{*targetMsg}, contextMessages[15:]...)...)

	result, err := e.Evaluate(context.Background(), targetMsg, members, contextMessages)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if result.ShouldTrigger {
		t.Error("expected no trigger due to sliding window anti-loop protection")
	}
}

// TestEvaluateSlidingWindowNoLoop verifies normal messages trigger correctly.
func TestEvaluateSlidingWindowNoLoop(t *testing.T) {
	e := NewEvaluator(10 * time.Minute)
	members := []models.GroupMember{
		makeMember("user1", "Alice", models.MemberTypeUser),
		makeMember("agent1", "Bot", models.MemberTypeManagerAgent),
	}

	// Only 5 consecutive agent messages (below threshold)
	contextMessages := make([]models.GroupMessage, 0, 15)
	now := time.Now().UnixMilli()

	for i := 0; i < 5; i++ {
		contextMessages = append(contextMessages, *makeMessage(
			"msg_a_"+string(rune('a'+i)), "agent1", models.MemberTypeWorkerAgent,
			"agent msg", "", now-int64((10-i)*1000),
		))
	}

	// Target message at the end
	targetMsg := makeMessage("target", "user1", models.MemberTypeUser, "Hello", "", now+1000)
	contextMessages = append(contextMessages, *targetMsg)

	result, err := e.Evaluate(context.Background(), targetMsg, members, contextMessages)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if !result.ShouldTrigger {
		t.Error("expected trigger for normal message")
	}
}

// TestExtractMentions verifies mention extraction from message text.
func TestExtractMentions(t *testing.T) {
	members := []models.GroupMember{
		makeMember("user1", "Alice", models.MemberTypeUser),
		makeMember("agent1", "Bot", models.MemberTypeWorkerAgent),
		makeMember("agent2", "Helper", models.MemberTypeManagerAgent),
	}

	tests := []struct {
		name    string
		text    string
		wantIDs []string
		wantAll bool
	}{
		{
			name:    "no mentions",
			text:    "Hello everyone",
			wantIDs: []string{},
			wantAll: false,
		},
		{
			name:    "mention by id",
			text:    "Hello @agent1, can you help?",
			wantIDs: []string{"agent1"},
			wantAll: false,
		},
		{
			name:    "mention by name",
			text:    "Hello @Bot, can you help?",
			wantIDs: []string{"agent1"},
			wantAll: false,
		},
		{
			name:    "multiple mentions",
			text:    "@agent1 @agent2 please help",
			wantIDs: []string{"agent1", "agent2"},
			wantAll: false,
		},
		{
			name:    "mention all",
			text:    "@all please respond",
			wantIDs: []string{},
			wantAll: true,
		},
		{
			name:    "mention user (not agent)",
			text:    "@user1 what do you think?",
			wantIDs: []string{},
			wantAll: false,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			e := NewEvaluator(10 * time.Minute)
			mentions := e.extractMentions(tt.text, members)

			if mentions.hasAll != tt.wantAll {
				t.Errorf("hasAll = %v, want %v", mentions.hasAll, tt.wantAll)
			}

			gotIDs := make([]string, 0, len(mentions.agents))
			for _, a := range mentions.agents {
				gotIDs = append(gotIDs, a.MemberID)
			}

			if len(gotIDs) != len(tt.wantIDs) {
				t.Errorf("got %d agent mentions, want %d", len(gotIDs), len(tt.wantIDs))
			}
			for i, id := range tt.wantIDs {
				if i >= len(gotIDs) || gotIDs[i] != id {
					t.Errorf("mention[%d] = %v, want %v", i, gotIDs, tt.wantIDs)
					break
				}
			}
		})
	}
}

// TestEvaluateMentionSingleAgent verifies single agent mention triggers correctly.
func TestEvaluateMentionSingleAgent(t *testing.T) {
	e := NewEvaluator(10 * time.Minute)
	members := []models.GroupMember{
		makeMember("user1", "Alice", models.MemberTypeUser),
		makeMember("agent1", "Bot", models.MemberTypeWorkerAgent),
	}

	msg := makeMessage("msg1", "user1", models.MemberTypeUser, "@agent1 help me", "", time.Now().UnixMilli())
	result, err := e.Evaluate(context.Background(), msg, members, nil)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if !result.ShouldTrigger {
		t.Fatal("expected trigger for single agent mention")
	}
	if result.Trigger.Type != TriggerTypeMention {
		t.Errorf("trigger type = %v, want %v", result.Trigger.Type, TriggerTypeMention)
	}
	if len(result.Targets) != 1 || result.Targets[0].AgentID != "agent1" {
		t.Errorf("targets = %v, want [{agent1 agent}]", result.Targets)
	}
	if result.Targets[0].Mode != "agent" {
		t.Errorf("mode = %v, want agent", result.Targets[0].Mode)
	}
}

// TestEvaluateMentionMultipleAgentsNoManager verifies multiple agent mentions without manager trigger concurrently.
func TestEvaluateMentionMultipleAgentsNoManager(t *testing.T) {
	e := NewEvaluator(10 * time.Minute)
	members := []models.GroupMember{
		makeMember("user1", "Alice", models.MemberTypeUser),
		makeMember("agent1", "Bot1", models.MemberTypeWorkerAgent),
		makeMember("agent2", "Bot2", models.MemberTypeWorkerAgent),
	}

	msg := makeMessage("msg1", "user1", models.MemberTypeUser, "@agent1 @agent2 help", "", time.Now().UnixMilli())
	result, err := e.Evaluate(context.Background(), msg, members, nil)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if !result.ShouldTrigger {
		t.Fatal("expected trigger for multiple agent mentions")
	}
	if len(result.Targets) != 2 {
		t.Fatalf("expected 2 targets, got %d", len(result.Targets))
	}
	if result.Targets[0].Mode != "agent" || result.Targets[1].Mode != "agent" {
		t.Error("expected agent mode for multiple agents without manager")
	}
}

// TestEvaluateMentionMultipleAgentsWithManager verifies manager is selected when present in mentions.
func TestEvaluateMentionMultipleAgentsWithManager(t *testing.T) {
	e := NewEvaluator(10 * time.Minute)
	members := []models.GroupMember{
		makeMember("user1", "Alice", models.MemberTypeUser),
		makeMember("agent1", "Bot1", models.MemberTypeWorkerAgent),
		makeMember("mgr1", "Manager", models.MemberTypeManagerAgent),
	}

	msg := makeMessage("msg1", "user1", models.MemberTypeUser, "@agent1 @mgr1 help", "", time.Now().UnixMilli())
	result, err := e.Evaluate(context.Background(), msg, members, nil)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if !result.ShouldTrigger {
		t.Fatal("expected trigger for mentions with manager")
	}
	if len(result.Targets) != 1 {
		t.Fatalf("expected 1 target, got %d", len(result.Targets))
	}
	if result.Targets[0].AgentID != "mgr1" {
		t.Errorf("target agent = %v, want mgr1", result.Targets[0].AgentID)
	}
	if result.Targets[0].Mode != "agent" {
		t.Errorf("mode = %v, want agent", result.Targets[0].Mode)
	}
}

// TestEvaluateMentionAll verifies @all triggers manager-agent with high priority.
func TestEvaluateMentionAll(t *testing.T) {
	e := NewEvaluator(10 * time.Minute)
	members := []models.GroupMember{
		makeMember("user1", "Alice", models.MemberTypeUser),
		makeMember("agent1", "Bot", models.MemberTypeWorkerAgent),
		makeMember("mgr1", "Manager", models.MemberTypeManagerAgent),
	}

	msg := makeMessage("msg1", "user1", models.MemberTypeUser, "@all please help", "", time.Now().UnixMilli())
	result, err := e.Evaluate(context.Background(), msg, members, nil)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if !result.ShouldTrigger {
		t.Fatal("expected trigger for @all mention")
	}
	if result.Trigger.Type != TriggerTypeMention {
		t.Errorf("trigger type = %v, want %v", result.Trigger.Type, TriggerTypeMention)
	}
	if len(result.Targets) != 1 || result.Targets[0].AgentID != "mgr1" {
		t.Errorf("targets = %v, want [{mgr1 agent}]", result.Targets)
	}
}

// TestEvaluateAutoTriggerSingleUser verifies auto-trigger when only 1 user in group.
func TestEvaluateAutoTriggerSingleUser(t *testing.T) {
	e := NewEvaluator(10 * time.Minute)
	members := []models.GroupMember{
		makeMember("user1", "Alice", models.MemberTypeUser),
		makeMember("mgr1", "Manager", models.MemberTypeManagerAgent),
	}

	msg := makeMessage("msg1", "user1", models.MemberTypeUser, "Hello", "", time.Now().UnixMilli())
	result, err := e.Evaluate(context.Background(), msg, members, nil)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if !result.ShouldTrigger {
		t.Fatal("expected auto-trigger for single user group")
	}
	if result.Trigger.Type != TriggerTypeAuto {
		t.Errorf("trigger type = %v, want %v", result.Trigger.Type, TriggerTypeAuto)
	}
	if len(result.Targets) != 1 || result.Targets[0].AgentID != "mgr1" {
		t.Errorf("targets = %v, want [{mgr1 agent}]", result.Targets)
	}
}

// TestEvaluateAutoTriggerMultipleUsers verifies no auto-trigger when multiple users.
func TestEvaluateAutoTriggerMultipleUsers(t *testing.T) {
	e := NewEvaluator(10 * time.Minute)
	members := []models.GroupMember{
		makeMember("user1", "Alice", models.MemberTypeUser),
		makeMember("user2", "Bob", models.MemberTypeUser),
		makeMember("mgr1", "Manager", models.MemberTypeManagerAgent),
	}

	msg := makeMessage("msg1", "user1", models.MemberTypeUser, "Hello", "", time.Now().UnixMilli())
	result, err := e.Evaluate(context.Background(), msg, members, nil)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if result.ShouldTrigger {
		t.Error("expected no auto-trigger for multiple users")
	}
}

// TestEvaluateAutoTriggerTimeout verifies timeout-based auto-trigger evaluation.
func TestEvaluateAutoTriggerTimeout(t *testing.T) {
	timeout := 10 * time.Minute
	e := NewEvaluator(timeout)
	members := []models.GroupMember{
		makeMember("user1", "Alice", models.MemberTypeUser),
		makeMember("mgr1", "Manager", models.MemberTypeManagerAgent),
	}

	// Message older than timeout
	oldMsg := makeMessage("msg1", "user1", models.MemberTypeUser, "Hello", "", time.Now().Add(-20*time.Minute).UnixMilli())
	result, err := e.EvaluateAutoTriggerTimeout(context.Background(), oldMsg, members)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if !result.ShouldTrigger {
		t.Fatal("expected timeout auto-trigger for old message")
	}

	// Message newer than timeout
	newMsg := makeMessage("msg2", "user1", models.MemberTypeUser, "Hello", "", time.Now().Add(-5*time.Minute).UnixMilli())
	result2, err := e.EvaluateAutoTriggerTimeout(context.Background(), newMsg, members)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if result2.ShouldTrigger {
		t.Error("expected no timeout auto-trigger for recent message")
	}

	// Agent sender should not trigger
	agentMsg := makeMessage("msg3", "agent1", models.MemberTypeWorkerAgent, "Hello", "", time.Now().Add(-20*time.Minute).UnixMilli())
	result3, err := e.EvaluateAutoTriggerTimeout(context.Background(), agentMsg, members)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if result3.ShouldTrigger {
		t.Error("expected no timeout auto-trigger for agent sender")
	}
}

// TestExtractMentionsFromText verifies the exported mention extraction function.
func TestExtractMentionsFromText(t *testing.T) {
	members := []models.GroupMember{
		makeMember("user1", "Alice", models.MemberTypeUser),
		makeMember("agent1", "Bot", models.MemberTypeWorkerAgent),
	}

	mentions := ExtractMentionsFromText("@agent1 @user1 hello", members)
	if len(mentions) != 2 {
		t.Fatalf("expected 2 mentions, got %d", len(mentions))
	}
	if mentions[0].MemberID != "agent1" {
		t.Errorf("first mention = %v, want agent1", mentions[0].MemberID)
	}
	if mentions[1].MemberID != "user1" {
		t.Errorf("second mention = %v, want user1", mentions[1].MemberID)
	}
}

// TestExtractMentionsFromTextAll verifies @all includes all members.
func TestExtractMentionsFromTextAll(t *testing.T) {
	members := []models.GroupMember{
		makeMember("user1", "Alice", models.MemberTypeUser),
		makeMember("agent1", "Bot", models.MemberTypeWorkerAgent),
		makeMember("mgr1", "Manager", models.MemberTypeManagerAgent),
	}

	mentions := ExtractMentionsFromText("@all please help", members)
	if len(mentions) != 3 {
		t.Fatalf("expected 3 mentions for @all, got %d", len(mentions))
	}
	if mentions[0].MemberID != "user1" {
		t.Errorf("first mention = %v, want user1", mentions[0].MemberID)
	}
	if mentions[1].MemberID != "agent1" {
		t.Errorf("second mention = %v, want agent1", mentions[1].MemberID)
	}
	if mentions[2].MemberID != "mgr1" {
		t.Errorf("third mention = %v, want mgr1", mentions[2].MemberID)
	}
}

// TestFormatAndParseTrigger verifies trigger serialization round-trip.
func TestFormatAndParseTrigger(t *testing.T) {
	trigger := TriggerInfo{Type: TriggerTypeMention, AgentID: "agent1"}
	targets := []AgentTarget{
		{AgentID: "agent1", Mode: "agent"},
	}

	data := FormatTriggerForNATS(trigger, targets)

	// Simulate JSON round-trip as would happen over NATS
	jsonData, err := json.Marshal(data)
	if err != nil {
		t.Fatalf("failed to marshal: %v", err)
	}

	var roundTrip map[string]interface{}
	if err := json.Unmarshal(jsonData, &roundTrip); err != nil {
		t.Fatalf("failed to unmarshal: %v", err)
	}

	parsedTrigger, parsedTargets, err := ParseTriggerFromNATS(roundTrip)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if parsedTrigger.Type != trigger.Type {
		t.Errorf("trigger type = %v, want %v", parsedTrigger.Type, trigger.Type)
	}
	if parsedTrigger.AgentID != trigger.AgentID {
		t.Errorf("trigger agent_id = %v, want %v", parsedTrigger.AgentID, trigger.AgentID)
	}
	if len(parsedTargets) != 1 || parsedTargets[0].AgentID != "agent1" {
		t.Errorf("parsed targets = %v, want [{agent1 agent}]", parsedTargets)
	}
}
