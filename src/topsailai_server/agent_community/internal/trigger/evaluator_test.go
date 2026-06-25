package trigger

import (
	"context"
	"encoding/json"
	"fmt"
	"strings"
	"testing"
	"time"

	"github.com/topsailai/agent-community/internal/models"
)

func makeMember(id, name string, mt models.MemberType) models.GroupMember {
	return models.GroupMember{
		MemberID:   id,
		MemberName: name,
		MemberType: mt,
	}
}

func makeMessage(id, senderID string, senderType models.MemberType, text, processed string, createAtMs int64) *models.GroupMessage {
	return &models.GroupMessage{
		MessageID:      id,
		SenderID:       senderID,
		SenderType:     senderType,
		MessageText:    text,
		ProcessedMsgID: processed,
		CreateAtMs:     createAtMs,
	}
}

// TestEvaluateAntiTriggerAgentSender verifies agent sender does not trigger.
func TestEvaluateAntiTriggerAgentSender(t *testing.T) {
	e := NewEvaluator(10 * time.Minute)
	members := []models.GroupMember{
		makeMember("user1", "Alice", models.MemberTypeUser),
		makeMember("agent1", "Bot", models.MemberTypeWorkerAgent),
	}
	msg := makeMessage("msg1", "agent1", models.MemberTypeWorkerAgent, "Hello", "", time.Now().UnixMilli())

	result, err := e.Evaluate(context.Background(), msg, members, nil)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if result.ShouldTrigger {
		t.Error("expected no trigger for agent sender")
	}
}

// TestEvaluateAntiTriggerProcessedMsgID verifies processed messages do not trigger.
func TestEvaluateAntiTriggerProcessedMsgID(t *testing.T) {
	e := NewEvaluator(10 * time.Minute)
	members := []models.GroupMember{
		makeMember("user1", "Alice", models.MemberTypeUser),
		makeMember("agent1", "Bot", models.MemberTypeWorkerAgent),
	}
	msg := makeMessage("msg1", "user1", models.MemberTypeUser, "Hello", "processed-id", time.Now().UnixMilli())

	result, err := e.Evaluate(context.Background(), msg, members, nil)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if result.ShouldTrigger {
		t.Error("expected no trigger for processed message")
	}
}

// TestEvaluateAntiTriggerProcessedMsgIDWithMention verifies that a processed
// message containing an agent mention must NOT trigger (NO_TRIGGER_CASES #2).
func TestEvaluateAntiTriggerProcessedMsgIDWithMention(t *testing.T) {
	e := NewEvaluator(10 * time.Minute)
	members := []models.GroupMember{
		makeMember("user1", "Alice", models.MemberTypeUser),
		makeMember("agent1", "Bot", models.MemberTypeWorkerAgent),
	}
	msg := makeMessage("msg1", "user1", models.MemberTypeUser, "Hello @agent1", "processed-id", time.Now().UnixMilli())

	result, err := e.Evaluate(context.Background(), msg, members, nil)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if result.ShouldTrigger {
		t.Error("expected no trigger for processed message even when it mentions an agent")
	}
}

// TestEvaluateAntiTriggerProcessedMsgIDSingleUserAutoTrigger verifies that a
// processed message in a single-user group must NOT auto-trigger the manager
// agent (NO_TRIGGER_CASES #2 takes precedence over auto-trigger).
func TestEvaluateAntiTriggerProcessedMsgIDSingleUserAutoTrigger(t *testing.T) {
	e := NewEvaluator(10 * time.Minute)
	members := []models.GroupMember{
		makeMember("user1", "Alice", models.MemberTypeUser),
		makeMember("mgr1", "Manager", models.MemberTypeManagerAgent),
	}
	msg := makeMessage("msg1", "user1", models.MemberTypeUser, "Hello", "processed-id", time.Now().UnixMilli())

	result, err := e.Evaluate(context.Background(), msg, members, nil)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if result.ShouldTrigger {
		t.Error("expected no auto-trigger for processed message in single-user group")
	}
}

// TestEvaluateSlidingWindow verifies >10 consecutive agent messages block trigger.
func TestEvaluateSlidingWindow(t *testing.T) {
	e := NewEvaluator(10 * time.Minute)
	members := []models.GroupMember{
		makeMember("user1", "Alice", models.MemberTypeUser),
		makeMember("agent1", "Bot", models.MemberTypeWorkerAgent),
	}
	now := time.Now().UnixMilli()

	contextMessages := make([]models.GroupMessage, 0, 21)
	for i := 0; i < 11; i++ {
		contextMessages = append(contextMessages, *makeMessage(
			"msg_a_"+string(rune('a'+i)), "agent1", models.MemberTypeWorkerAgent,
			"agent msg", "", now-int64((20-i)*1000),
		))
	}
	targetMsg := makeMessage("target", "user1", models.MemberTypeUser, "Hello", "", now+1000)
	contextMessages = append(contextMessages, *targetMsg)

	result, err := e.Evaluate(context.Background(), targetMsg, members, contextMessages)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if result.ShouldTrigger {
		t.Error("expected no trigger when >10 consecutive agent messages in window")
	}
}

// TestEvaluateSlidingWindowNoLoop verifies normal messages trigger when a manager is available.
func TestEvaluateSlidingWindowNoLoop(t *testing.T) {
	e := NewEvaluator(10 * time.Minute)
	members := []models.GroupMember{
		makeMember("user1", "Alice", models.MemberTypeUser),
		makeMember("agent1", "Bot", models.MemberTypeWorkerAgent),
		makeMember("mgr1", "Manager", models.MemberTypeManagerAgent),
	}
	now := time.Now().UnixMilli()

	contextMessages := []models.GroupMessage{
		*makeMessage("msg1", "user1", models.MemberTypeUser, "Hello", "", now-2000),
		*makeMessage("msg2", "agent1", models.MemberTypeWorkerAgent, "Hi", "", now-1000),
	}
	targetMsg := makeMessage("target", "user1", models.MemberTypeUser, "How are you?", "", now)

	result, err := e.Evaluate(context.Background(), targetMsg, members, contextMessages)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if !result.ShouldTrigger {
		t.Error("expected trigger for normal user message")
	}
}

// TestExtractMentions verifies mention extraction.
func TestExtractMentions(t *testing.T) {
	e := NewEvaluator(10 * time.Minute)
	members := []models.GroupMember{
		makeMember("user1", "Alice", models.MemberTypeUser),
		makeMember("agent1", "Bot", models.MemberTypeWorkerAgent),
		makeMember("mgr1", "Manager", models.MemberTypeManagerAgent),
	}

	tests := []struct {
		name    string
		text    string
		wantIDs []string
		wantAll bool
	}{
		{"no mentions", "Hello", nil, false},
		{"mention by id", "Hello @agent1", []string{"agent1"}, false},
		{"mention by name", "Hello @Bot", []string{"agent1"}, false},
		{"multiple mentions", "@agent1 @mgr1", []string{"agent1", "mgr1"}, false},
		{"mention all", "@all", nil, true},
		{"mention user (not agent)", "@user1", nil, false},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			result := e.extractMentions(tt.text, members)
			if result.hasAll != tt.wantAll {
				t.Errorf("hasAll = %v, want %v", result.hasAll, tt.wantAll)
			}
			if len(result.agents) != len(tt.wantIDs) {
				t.Fatalf("agent count = %d, want %d", len(result.agents), len(tt.wantIDs))
			}
			for i, id := range tt.wantIDs {
				if result.agents[i].MemberID != id {
					t.Errorf("agent[%d] = %v, want %v", i, result.agents[i].MemberID, id)
				}
			}
		})
	}
}

// TestEvaluateMentionSingleAgent verifies single agent mention triggers that agent.
func TestEvaluateMentionSingleAgent(t *testing.T) {
	e := NewEvaluator(10 * time.Minute)
	members := []models.GroupMember{
		makeMember("user1", "Alice", models.MemberTypeUser),
		makeMember("agent1", "Bot", models.MemberTypeWorkerAgent),
	}
	msg := makeMessage("msg1", "user1", models.MemberTypeUser, "Hello @agent1", "", time.Now().UnixMilli())

	result, err := e.Evaluate(context.Background(), msg, members, nil)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if !result.ShouldTrigger {
		t.Fatal("expected trigger")
	}
	if len(result.Targets) != 1 || result.Targets[0].AgentID != "agent1" {
		t.Errorf("targets = %v, want [agent1]", result.Targets)
	}
	if result.Trigger.Type != TriggerTypeMention {
		t.Errorf("trigger type = %v, want mention", result.Trigger.Type)
	}
}
// TestEvaluateMentionMultipleAgentsNoManager verifies multiple agent mentions without manager trigger all agents.
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
		t.Fatal("expected trigger")
	}
	if len(result.Targets) != 2 {
		t.Fatalf("targets count = %d, want 2", len(result.Targets))
	}
	for _, target := range result.Targets {
		if !strings.Contains(target.MessageAppend, "DONOT INVOKE ANY TOOLS") {
			t.Errorf("expected appended instruction for target %s", target.AgentID)
		}
	}
}

// TestEvaluateMentionMultipleAgentsWithManager verifies multiple agent mentions with manager trigger one manager.
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
		t.Fatal("expected trigger")
	}
	if len(result.Targets) != 1 || result.Targets[0].AgentID != "mgr1" {
		t.Errorf("targets = %v, want [mgr1]", result.Targets)
	}
}

// TestEvaluateMentionAll verifies @all triggers manager-agent.
func TestEvaluateMentionAll(t *testing.T) {
	e := NewEvaluator(10 * time.Minute)
	members := []models.GroupMember{
		makeMember("user1", "Alice", models.MemberTypeUser),
		makeMember("agent1", "Bot", models.MemberTypeWorkerAgent),
		makeMember("mgr1", "Manager", models.MemberTypeManagerAgent),
	}
	msg := makeMessage("msg1", "user1", models.MemberTypeUser, "@all", "", time.Now().UnixMilli())

	result, err := e.Evaluate(context.Background(), msg, members, nil)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if !result.ShouldTrigger {
		t.Fatal("expected trigger")
	}
	if len(result.Targets) != 1 || result.Targets[0].AgentID != "mgr1" {
		t.Errorf("targets = %v, want [mgr1]", result.Targets)
	}
}

// TestEvaluateAutoTriggerSingleUser verifies auto-trigger when only one user exists.
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
		t.Fatal("expected auto-trigger for single user")
	}
	if result.Targets[0].AgentID != "mgr1" {
		t.Errorf("targets = %v, want [mgr1]", result.Targets)
	}
}

// TestEvaluateAutoTriggerMultipleUsers verifies no auto-trigger when multiple users exist.
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

// TestEvaluateAutoTriggerTimeout verifies timeout auto-trigger via the dedicated exported method.
func TestEvaluateAutoTriggerTimeout(t *testing.T) {
	timeout := 10 * time.Minute
	e := NewEvaluator(timeout)
	members := []models.GroupMember{
		makeMember("user1", "Alice", models.MemberTypeUser),
		makeMember("user2", "Bob", models.MemberTypeUser),
		makeMember("mgr1", "Manager", models.MemberTypeManagerAgent),
	}
	now := time.Now()
	lastMsgTime := now.Add(-timeout - time.Second)

	lastMsg := makeMessage("msg1", "user1", models.MemberTypeUser, "Hello", "", lastMsgTime.UnixMilli())

	result, err := e.EvaluateAutoTriggerTimeout(context.Background(), lastMsg, members)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if !result.ShouldTrigger {
		t.Fatal("expected timeout auto-trigger")
	}
	if result.Targets[0].AgentID != "mgr1" {
		t.Errorf("targets = %v, want [mgr1]", result.Targets)
	}
}

// TestExtractMentionsFromText verifies the standalone text mention extractor.
func TestExtractMentionsFromText(t *testing.T) {
	members := []models.GroupMember{
		makeMember("user1", "Alice", models.MemberTypeUser),
		makeMember("agent1", "Bot", models.MemberTypeWorkerAgent),
	}
	text := "Hello @agent1 and @Bot"
	mentions := ExtractMentionsFromText(text, members)
	if len(mentions) != 1 {
		t.Fatalf("mentions count = %d, want 1", len(mentions))
	}
	if mentions[0].MemberID != "agent1" {
		t.Errorf("first mention = %v, want agent1", mentions[0])
	}
}

// TestExtractMentionsFromTextAll verifies @all extraction.
func TestExtractMentionsFromTextAll(t *testing.T) {
	members := []models.GroupMember{
		makeMember("user1", "Alice", models.MemberTypeUser),
		makeMember("agent1", "Bot", models.MemberTypeWorkerAgent),
	}
	text := "@all please respond"
	mentions := ExtractMentionsFromText(text, members)
	if len(mentions) != 2 {
		t.Fatalf("mentions count = %d, want 2", len(mentions))
	}
	foundAll := false
	for _, m := range mentions {
		if m.MemberID == "user1" || m.MemberID == "agent1" {
			foundAll = true
		}
	}
	if !foundAll {
		t.Errorf("mentions = %v, want all members", mentions)
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

// TestEvaluate_SlidingWindowBoundary10 verifies exactly 10 consecutive agent messages still allow trigger.
func TestEvaluate_SlidingWindowBoundary10(t *testing.T) {
	e := NewEvaluator(10 * time.Minute)
	members := []models.GroupMember{
		makeMember("user1", "Alice", models.MemberTypeUser),
		makeMember("agent1", "Bot", models.MemberTypeWorkerAgent),
		makeMember("mgr1", "Manager", models.MemberTypeManagerAgent),
	}
	now := time.Now().UnixMilli()

	contextMessages := make([]models.GroupMessage, 0, 11)
	for i := 0; i < 10; i++ {
		contextMessages = append(contextMessages, *makeMessage(
			"msg_a_"+string(rune('a'+i)), "agent1", models.MemberTypeWorkerAgent,
			"agent msg", "", now-int64((20-i)*1000),
		))
	}

	targetMsg := makeMessage("target", "user1", models.MemberTypeUser, "Hello", "", now+1000)
	contextMessages = append(contextMessages, *targetMsg)

	result, err := e.Evaluate(context.Background(), targetMsg, members, contextMessages)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if !result.ShouldTrigger {
		t.Error("expected trigger when exactly 10 consecutive agent messages in window")
	}
}

// TestEvaluate_SlidingWindowBoundary11 verifies 11 consecutive agent messages block trigger.
func TestEvaluate_SlidingWindowBoundary11(t *testing.T) {
	e := NewEvaluator(10 * time.Minute)
	members := []models.GroupMember{
		makeMember("user1", "Alice", models.MemberTypeUser),
		makeMember("agent1", "Bot", models.MemberTypeWorkerAgent),
		makeMember("mgr1", "Manager", models.MemberTypeManagerAgent),
	}
	now := time.Now().UnixMilli()

	// Build 11 agent messages: 10 before the target and 1 after, so the 20-message
	// window around the target contains 11 consecutive agent messages.
	contextMessages := make([]models.GroupMessage, 0, 12)
	for i := 0; i < 10; i++ {
		contextMessages = append(contextMessages, *makeMessage(
			fmt.Sprintf("msg_a_%d", i), "agent1", models.MemberTypeWorkerAgent,
			"agent msg", "", now-int64((20-i)*1000),
		))
	}

	targetMsg := makeMessage("target", "user1", models.MemberTypeUser, "Hello", "", now+1000)
	contextMessages = append(contextMessages, *targetMsg)
	contextMessages = append(contextMessages, *makeMessage(
		"msg_after", "agent1", models.MemberTypeWorkerAgent,
		"agent msg", "", now+2000,
	))

	result, err := e.Evaluate(context.Background(), targetMsg, members, contextMessages)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if result.ShouldTrigger {
		t.Error("expected no trigger when 11 consecutive agent messages in window")
	}
}

// TestEvaluate_SlidingWindowExcludesDeletedAgentMessages verifies that deleted
// agent messages are not counted toward the consecutive-agent run.
func TestEvaluate_SlidingWindowExcludesDeletedAgentMessages(t *testing.T) {
	e := NewEvaluator(10 * time.Minute)
	members := []models.GroupMember{
		makeMember("user1", "Alice", models.MemberTypeUser),
		makeMember("agent1", "Bot", models.MemberTypeWorkerAgent),
		makeMember("mgr1", "Manager", models.MemberTypeManagerAgent),
	}
	now := time.Now().UnixMilli()

	// Build 11 agent messages before target, but mark 2 as deleted.
	// After excluding deleted messages, only 9 consecutive agent messages remain,
	// so the trigger should proceed.
	contextMessages := make([]models.GroupMessage, 0, 12)
	for i := 0; i < 11; i++ {
		m := makeMessage(
			fmt.Sprintf("msg_a_%d", i), "agent1", models.MemberTypeWorkerAgent,
			"agent msg", "", now-int64((20-i)*1000),
		)
		if i < 2 {
			m.IsDeleted = true
			m.DeleteAtMs = now - int64((20-i)*1000) + 1
		}
		contextMessages = append(contextMessages, *m)
	}

	targetMsg := makeMessage("target", "user1", models.MemberTypeUser, "Hello", "", now+1000)
	contextMessages = append(contextMessages, *targetMsg)

	result, err := e.Evaluate(context.Background(), targetMsg, members, contextMessages)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if !result.ShouldTrigger {
		t.Error("expected trigger when deleted agent messages are excluded from consecutive count")
	}
}

// TestEvaluate_SlidingWindowExcludesDeletedNonAgentMessages verifies that deleted
// non-agent messages do not break a consecutive-agent run.
func TestEvaluate_SlidingWindowExcludesDeletedNonAgentMessages(t *testing.T) {
	e := NewEvaluator(10 * time.Minute)
	members := []models.GroupMember{
		makeMember("user1", "Alice", models.MemberTypeUser),
		makeMember("agent1", "Bot", models.MemberTypeWorkerAgent),
		makeMember("mgr1", "Manager", models.MemberTypeManagerAgent),
	}
	now := time.Now().UnixMilli()

	// Build 10 agent messages, then a deleted user message, then 1 more agent message.
	// Excluding the deleted user message leaves 11 consecutive agent messages in the
	// window around the target, so the trigger should be blocked.
	contextMessages := make([]models.GroupMessage, 0, 13)
	for i := 0; i < 10; i++ {
		contextMessages = append(contextMessages, *makeMessage(
			fmt.Sprintf("msg_a_%d", i), "agent1", models.MemberTypeWorkerAgent,
			"agent msg", "", now-int64((20-i)*1000),
		))
	}
	deletedUserMsg := makeMessage(
		"msg_user_deleted", "user1", models.MemberTypeUser, "deleted", "", now-9000,
	)
	deletedUserMsg.IsDeleted = true
	deletedUserMsg.DeleteAtMs = now - 8999
	contextMessages = append(contextMessages, *deletedUserMsg)

	targetMsg := makeMessage("target", "user1", models.MemberTypeUser, "Hello", "", now+1000)
	contextMessages = append(contextMessages, *targetMsg)

	contextMessages = append(contextMessages, *makeMessage(
		"msg_after", "agent1", models.MemberTypeWorkerAgent,
		"agent msg", "", now+2000,
	))

	result, err := e.Evaluate(context.Background(), targetMsg, members, contextMessages)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if result.ShouldTrigger {
		t.Error("expected no trigger when deleted non-agent messages are excluded and 11 agent messages are consecutive")
	}
}

// TestEvaluate_TargetMessageDeleted verifies that a deleted target message is
// not found in the filtered context and loop protection is skipped.
func TestEvaluate_TargetMessageDeleted(t *testing.T) {
	e := NewEvaluator(10 * time.Minute)
	members := []models.GroupMember{
		makeMember("user1", "Alice", models.MemberTypeUser),
		makeMember("mgr1", "Manager", models.MemberTypeManagerAgent),
	}
	now := time.Now().UnixMilli()

	contextMessages := []models.GroupMessage{
		*makeMessage("msg1", "agent1", models.MemberTypeWorkerAgent, "agent", "", now-1000),
	}
	targetMsg := makeMessage("target", "user1", models.MemberTypeUser, "Hello", "", now)
	targetMsg.IsDeleted = true
	targetMsg.DeleteAtMs = now + 1

	result, err := e.Evaluate(context.Background(), targetMsg, members, contextMessages)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if !result.ShouldTrigger {
		t.Error("expected trigger when target message is deleted and not in filtered context")
	}
}

// TestEvaluate_TargetNotInContext verifies evaluation continues when target is missing from context.
func TestEvaluate_TargetNotInContext(t *testing.T) {
	e := NewEvaluator(10 * time.Minute)
	members := []models.GroupMember{
		makeMember("user1", "Alice", models.MemberTypeUser),
		makeMember("mgr1", "Manager", models.MemberTypeManagerAgent),
	}
	now := time.Now().UnixMilli()

	contextMessages := []models.GroupMessage{
		*makeMessage("msg1", "user1", models.MemberTypeUser, "Hello", "", now-1000),
	}
	targetMsg := makeMessage("target", "user1", models.MemberTypeUser, "Hello", "", now)

	result, err := e.Evaluate(context.Background(), targetMsg, members, contextMessages)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if !result.ShouldTrigger {
		t.Error("expected trigger when target not in context (no loop protection applied)")
	}
}

// TestResolveAgents_AllNoManager verifies @all without manager does not trigger.
func TestResolveAgents_AllNoManager(t *testing.T) {
	e := NewEvaluator(10 * time.Minute)
	members := []models.GroupMember{
		makeMember("user1", "Alice", models.MemberTypeUser),
		makeMember("agent1", "Bot", models.MemberTypeWorkerAgent),
	}
	msg := makeMessage("msg1", "user1", models.MemberTypeUser, "@all", "", time.Now().UnixMilli())

	result, err := e.ResolveAgents(context.Background(), msg, members)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if result.ShouldTrigger {
		t.Error("expected no trigger when @all but no manager")
	}
}

// TestResolveAgents_SingleUserNoManager verifies single-user group without manager does not auto-trigger.
func TestResolveAgents_SingleUserNoManager(t *testing.T) {
	e := NewEvaluator(10 * time.Minute)
	members := []models.GroupMember{
		makeMember("user1", "Alice", models.MemberTypeUser),
	}
	msg := makeMessage("msg1", "user1", models.MemberTypeUser, "Hello", "", time.Now().UnixMilli())

	result, err := e.ResolveAgents(context.Background(), msg, members)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if result.ShouldTrigger {
		t.Error("expected no auto-trigger when single user and no manager")
	}
}

// TestResolveAgents_DuplicateMentions verifies duplicate mentions are deduplicated.
func TestResolveAgents_DuplicateMentions(t *testing.T) {
	e := NewEvaluator(10 * time.Minute)
	members := []models.GroupMember{
		makeMember("agent1", "Bot", models.MemberTypeWorkerAgent),
	}
	msg := makeMessage("msg1", "user1", models.MemberTypeUser, "@agent1 @agent1 @Bot", "", time.Now().UnixMilli())

	result, err := e.ResolveAgents(context.Background(), msg, members)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if !result.ShouldTrigger {
		t.Fatal("expected trigger")
	}
	if len(result.Targets) != 1 || result.Targets[0].AgentID != "agent1" {
		t.Errorf("targets = %v, want [agent1]", result.Targets)
	}
}

// TestEvaluateMentions_MultipleManagers verifies multiple manager mentions picks one manager.
func TestEvaluateMentions_MultipleManagers(t *testing.T) {
	e := NewEvaluator(10 * time.Minute)
	members := []models.GroupMember{
		makeMember("mgr1", "Manager1", models.MemberTypeManagerAgent),
		makeMember("mgr2", "Manager2", models.MemberTypeManagerAgent),
	}
	msg := makeMessage("msg1", "user1", models.MemberTypeUser, "@mgr1 @mgr2", "", time.Now().UnixMilli())

	result, err := e.ResolveAgents(context.Background(), msg, members)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if !result.ShouldTrigger {
		t.Fatal("expected trigger")
	}
	if len(result.Targets) != 1 {
		t.Fatalf("expected exactly one target, got %v", result.Targets)
	}
	if result.Targets[0].AgentID != "mgr1" && result.Targets[0].AgentID != "mgr2" {
		t.Errorf("expected mgr1 or mgr2, got %s", result.Targets[0].AgentID)
	}
	if result.Targets[0].Mode != "agent" {
		t.Errorf("expected mode agent, got %s", result.Targets[0].Mode)
	}
}

// TestEvaluateAutoTrigger_ZeroUsers verifies no auto-trigger when zero users.
func TestEvaluateAutoTrigger_ZeroUsers(t *testing.T) {
	e := NewEvaluator(10 * time.Minute)
	members := []models.GroupMember{
		makeMember("agent1", "Bot", models.MemberTypeWorkerAgent),
		makeMember("mgr1", "Manager", models.MemberTypeManagerAgent),
	}
	msg := makeMessage("msg1", "agent1", models.MemberTypeWorkerAgent, "Hello", "", time.Now().UnixMilli())

	result, err := e.ResolveAgents(context.Background(), msg, members)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if result.ShouldTrigger {
		t.Error("expected no auto-trigger when zero users")
	}
}

// TestEvaluateAutoTriggerTimeout_NilMessage verifies nil last message does not trigger.
func TestEvaluateAutoTriggerTimeout_NilMessage(t *testing.T) {
	e := NewEvaluator(10 * time.Minute)
	members := []models.GroupMember{
		makeMember("user1", "Alice", models.MemberTypeUser),
		makeMember("mgr1", "Manager", models.MemberTypeManagerAgent),
	}

	result, err := e.EvaluateAutoTriggerTimeout(context.Background(), nil, members)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if result.ShouldTrigger {
		t.Error("expected no trigger for nil last message")
	}
}

// TestEvaluateAutoTriggerTimeout_Boundary verifies timeout boundary behavior.
func TestEvaluateAutoTriggerTimeout_Boundary(t *testing.T) {
	timeout := 10 * time.Minute
	e := NewEvaluator(timeout)
	members := []models.GroupMember{
		makeMember("user1", "Alice", models.MemberTypeUser),
		makeMember("mgr1", "Manager", models.MemberTypeManagerAgent),
	}

	// Just under timeout: should NOT trigger
	msgTime := time.Now().Add(-timeout).Add(10 * time.Millisecond)
	lastMsgUnderTimeout := makeMessage("msg1", "user1", models.MemberTypeUser, "Hello", "", msgTime.UnixMilli())
	result, err := e.EvaluateAutoTriggerTimeout(context.Background(), lastMsgUnderTimeout, members)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if result.ShouldTrigger {
		t.Error("expected no trigger just under timeout boundary")
	}

	// One second past timeout: should trigger
	lastMsgPastTimeout := makeMessage("msg2", "user1", models.MemberTypeUser, "Hello", "", time.Now().Add(-timeout-1*time.Second).UnixMilli())
	result, err = e.EvaluateAutoTriggerTimeout(context.Background(), lastMsgPastTimeout, members)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if !result.ShouldTrigger {
		t.Error("expected trigger past timeout boundary")
	}
}

// TestExtractMentions_NameCollision verifies first matching member wins on name collision.
func TestExtractMentions_NameCollision(t *testing.T) {
	e := NewEvaluator(10 * time.Minute)
	members := []models.GroupMember{
		makeMember("agent1", "Bot", models.MemberTypeWorkerAgent),
		makeMember("agent2", "Bot", models.MemberTypeWorkerAgent),
	}
	msg := makeMessage("msg1", "user1", models.MemberTypeUser, "@Bot", "", time.Now().UnixMilli())

	mentions := e.extractMentions(msg.MessageText, members)
	if len(mentions.agents) != 1 || mentions.agents[0].MemberID != "agent1" {
		t.Errorf("mentions = %v, want [agent1]", mentions.agents)
	}
}

// TestExtractMentions_SpecialCharacters verifies mentions with underscores and hyphens.
func TestExtractMentions_SpecialCharacters(t *testing.T) {
	e := NewEvaluator(10 * time.Minute)
	members := []models.GroupMember{
		makeMember("agent_1", "Bot-1", models.MemberTypeWorkerAgent),
		makeMember("agent-2", "Bot_2", models.MemberTypeWorkerAgent),
	}
	text := "Hello @agent_1 and @agent-2"
	mentions := e.extractMentions(text, members)
	if len(mentions.agents) != 2 {
		t.Fatalf("mentions count = %d, want 2", len(mentions.agents))
	}
	ids := make(map[string]bool)
	for _, m := range mentions.agents {
		ids[m.MemberID] = true
	}
	if !ids["agent_1"] || !ids["agent-2"] {
		t.Errorf("mentions = %v, want agent_1 and agent-2", mentions.agents)
	}
}

// TestExtractMentions_AllMixed verifies @all takes precedence over other mentions.
func TestExtractMentions_AllMixed(t *testing.T) {
	e := NewEvaluator(10 * time.Minute)
	members := []models.GroupMember{
		makeMember("user1", "Alice", models.MemberTypeUser),
		makeMember("agent1", "Bot", models.MemberTypeWorkerAgent),
		makeMember("mgr1", "Manager", models.MemberTypeManagerAgent),
	}
	text := "@all @agent1"
	mentions := e.extractMentions(text, members)
	if !mentions.hasAll {
		t.Error("expected hasAll true")
	}
	if len(mentions.agents) != 0 {
		t.Errorf("expected no agents when @all present, got %v", mentions.agents)
	}
}

// TestFindRandomManager_Empty verifies findRandomManager returns nil for empty/all-worker members.
func TestFindRandomManager_Empty(t *testing.T) {
	e := NewEvaluator(10 * time.Minute)
	if m := e.findRandomManager(nil); m != nil {
		t.Errorf("expected nil manager for nil members, got %v", m)
	}
	members := []models.GroupMember{
		makeMember("agent1", "Bot", models.MemberTypeWorkerAgent),
	}
	if m := e.findRandomManager(members); m != nil {
		t.Errorf("expected nil manager for all-worker members, got %v", m)
	}
}

// TestParseTriggerFromNATS_MissingFields verifies parsing handles missing fields gracefully.
func TestParseTriggerFromNATS_MissingFields(t *testing.T) {
	trigger, targets, err := ParseTriggerFromNATS(map[string]interface{}{})
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if trigger.Type != "" || trigger.AgentID != "" {
		t.Errorf("expected empty trigger, got %+v", trigger)
	}
	if len(targets) != 0 {
		t.Errorf("expected empty targets, got %v", targets)
	}

	// Trigger fields at top level with no targets
	data := map[string]interface{}{
		"type":     "mention",
		"agent_id": "agent1",
	}
	trigger, targets, err = ParseTriggerFromNATS(data)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if trigger.Type != "mention" || trigger.AgentID != "agent1" {
		t.Errorf("trigger = %+v, want mention/agent1", trigger)
	}
	if len(targets) != 0 {
		t.Errorf("expected empty targets, got %v", targets)
	}

	// Malformed targets should be skipped
	data["targets"] = []interface{}{
		map[string]interface{}{"agent_id": 123, "mode": "agent"},
		map[string]interface{}{"agent_id": "agent2", "mode": "agent"},
	}
	trigger, targets, err = ParseTriggerFromNATS(data)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if len(targets) != 2 || targets[0].AgentID != "" || targets[1].AgentID != "agent2" {
		t.Errorf("targets = %v, want [empty, agent2]", targets)
	}
}
