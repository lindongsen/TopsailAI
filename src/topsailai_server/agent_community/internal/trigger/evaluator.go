// Package trigger evaluates whether a message should trigger agent processing.
package trigger

import (
	"context"
	"math/rand"
	"regexp"
	"strings"
	"time"

	"github.com/topsailai/agent-community/internal/models"
)

// TriggerType represents how the agent was triggered.
type TriggerType string

const (
	TriggerTypeMention TriggerType = "mention"
	TriggerTypeAuto    TriggerType = "auto"
	TriggerTypeManual  TriggerType = "manual"
)

// TriggerResult represents the result of trigger evaluation.
type TriggerResult struct {
	ShouldTrigger bool                `json:"should_trigger"`
	Trigger       TriggerInfo         `json:"trigger"`
	Targets       []AgentTarget       `json:"targets"`
}

// TriggerInfo contains metadata about the trigger.
type TriggerInfo struct {
	Type    TriggerType `json:"type"`
	AgentID string      `json:"agent_id,omitempty"`
}

// AgentTarget represents an agent that should process the message.
type AgentTarget struct {
	AgentID       string `json:"agent_id"`
	Mode          string `json:"mode"`
	MessageAppend string `json:"message_append,omitempty"`
}

// Evaluator evaluates messages to determine if agents should be triggered.
type Evaluator struct {
	autoTriggerTimeout time.Duration
}

// NewEvaluator creates a new trigger evaluator.
func NewEvaluator(autoTriggerTimeout time.Duration) *Evaluator {
	return &Evaluator{
		autoTriggerTimeout: autoTriggerTimeout,
	}
}

// Evaluate determines if the given message should trigger agent processing.
// It requires the message, all group members, and surrounding messages for context.
func (e *Evaluator) Evaluate(
	ctx context.Context,
	msg *models.GroupMessage,
	members []models.GroupMember,
	contextMessages []models.GroupMessage,
) (*TriggerResult, error) {
	// Rule: do not trigger if sender is an agent
	if isAgentType(msg.SenderType) {
		return &TriggerResult{ShouldTrigger: false}, nil
	}

	// Rule: do not trigger if processed_msg_id has value
	if msg.ProcessedMsgID != "" {
		return &TriggerResult{ShouldTrigger: false}, nil
	}

	// Rule: sliding window anti-loop protection
	if e.isLoopMessage(msg, contextMessages) {
		return &TriggerResult{ShouldTrigger: false}, nil
	}

	return e.ResolveAgents(ctx, msg, members)
}

// ResolveAgents decides which agents should process a message based on mentions / @all / manager-agent / auto rules.
// This does NOT check NO_TRIGGER_CASES; it is intended for manual trigger reuse.
func (e *Evaluator) ResolveAgents(
	ctx context.Context,
	msg *models.GroupMessage,
	members []models.GroupMember,
) (*TriggerResult, error) {
	// Extract mentions from message text
	mentions := e.extractMentions(msg.MessageText, members)

	// Priority 1: @all triggers manager-agent
	if mentions.hasAll {
		manager := e.findRandomManager(members)
		if manager != nil {
			return &TriggerResult{
				ShouldTrigger: true,
				Trigger:       TriggerInfo{Type: TriggerTypeMention, AgentID: manager.MemberID},
				Targets:       []AgentTarget{{AgentID: manager.MemberID, Mode: "agent"}},
			}, nil
		}
	}

	// Trigger via mentions
	if len(mentions.agents) > 0 {
		return e.evaluateMentions(mentions, members)
	}

	// Auto-trigger rules
	return e.evaluateAutoTrigger(msg, members)
}

// isAgentType checks if the member type is an agent.
func isAgentType(mt models.MemberType) bool {
	return mt == models.MemberTypeManagerAgent || mt == models.MemberTypeWorkerAgent
}

// isLoopMessage checks the sliding window anti-loop condition.
// In 20 messages around this one (10 before, 10 after), if >10 consecutive agent messages, skip.
func (e *Evaluator) isLoopMessage(msg *models.GroupMessage, contextMessages []models.GroupMessage) bool {
	if len(contextMessages) == 0 {
		return false
	}

	// Find the index of the target message in contextMessages
	targetIdx := -1
	for i, m := range contextMessages {
		if m.MessageID == msg.MessageID {
			targetIdx = i
			break
		}
	}

	if targetIdx == -1 {
		return false
	}

	// Get the window: 10 before and 10 after (excluding target, max 20 messages)
	start := targetIdx - 10
	if start < 0 {
		start = 0
	}
	end := targetIdx + 10
	if end >= len(contextMessages) {
		end = len(contextMessages) - 1
	}

	window := make([]models.GroupMessage, 0)
	for i := start; i <= end; i++ {
		if i != targetIdx {
			window = append(window, contextMessages[i])
		}
	}

	// Check for >10 consecutive agent messages in the window
	maxConsecutive := 0
	currentConsecutive := 0

	for _, m := range window {
		if isAgentType(m.SenderType) {
			currentConsecutive++
			if currentConsecutive > maxConsecutive {
				maxConsecutive = currentConsecutive
			}
		} else {
			currentConsecutive = 0
		}
	}

	return maxConsecutive > 10
}

// mentionResult holds extracted mention information.
type mentionResult struct {
	agents []models.GroupMember
	hasAll bool
}

// extractMentions extracts @mentions from message text.
func (e *Evaluator) extractMentions(text string, members []models.GroupMember) mentionResult {
	result := mentionResult{agents: make([]models.GroupMember, 0)}

	if text == "" {
		return result
	}

	// Check for @all
	if strings.Contains(text, "@all") {
		result.hasAll = true
		return result
	}

	// Pattern to match @member_id or @member_name
	re := regexp.MustCompile(`@([\w\-]+)`)
	matches := re.FindAllStringSubmatch(text, -1)

	mentionedIDs := make(map[string]bool)
	for _, match := range matches {
		if len(match) < 2 {
			continue
		}
		mention := match[1]

		for _, m := range members {
			if m.MemberID == mention || m.MemberName == mention {
				if !mentionedIDs[m.MemberID] {
					mentionedIDs[m.MemberID] = true
					if isAgentType(m.MemberType) {
						result.agents = append(result.agents, m)
					}
				}
				break
			}
		}
	}

	return result
}

// evaluateMentions evaluates trigger rules based on mentions.
func (e *Evaluator) evaluateMentions(mentions mentionResult, members []models.GroupMember) (*TriggerResult, error) {
	agentMentions := mentions.agents

	if len(agentMentions) == 0 {
		return &TriggerResult{ShouldTrigger: false}, nil
	}

	// Single agent mention
	if len(agentMentions) == 1 {
		return &TriggerResult{
			ShouldTrigger: true,
			Trigger:       TriggerInfo{Type: TriggerTypeMention, AgentID: agentMentions[0].MemberID},
			Targets:       []AgentTarget{{AgentID: agentMentions[0].MemberID, Mode: "agent"}},
		}, nil
	}

	// Multiple agent mentions
	managers := e.findAllManagers(agentMentions)
	if len(managers) == 0 {
		// No manager in mentions: concurrent call to all mentioned agents, mode=chat
		// Append instruction to not invoke tools
		appendText := "! DONOT INVOKE ANY TOOLS/SKILLS, Think directly and give the final answer !"
		targets := make([]AgentTarget, 0, len(agentMentions))
		for _, agent := range agentMentions {
			targets = append(targets, AgentTarget{
				AgentID:       agent.MemberID,
				Mode:          "agent",
				MessageAppend: appendText,
			})
		}
		return &TriggerResult{
			ShouldTrigger: true,
			Trigger:       TriggerInfo{Type: TriggerTypeMention},
			Targets:       targets,
		}, nil
	}

	// Manager exists in mentions: pick one random manager, mode=agent
	manager := managers[rand.Intn(len(managers))]
	return &TriggerResult{
		ShouldTrigger: true,
		Trigger:       TriggerInfo{Type: TriggerTypeMention, AgentID: manager.MemberID},
		Targets:       []AgentTarget{{AgentID: manager.MemberID, Mode: "agent"}},
	}, nil
}

// evaluateAutoTrigger evaluates auto-trigger rules.
func (e *Evaluator) evaluateAutoTrigger(msg *models.GroupMessage, members []models.GroupMember) (*TriggerResult, error) {
	// Count users in the group
	userCount := 0
	for _, m := range members {
		if m.MemberType == models.MemberTypeUser {
			userCount++
		}
	}

	// Rule: only 1 user in group + no mentions -> trigger manager-agent
	if userCount == 1 {
		manager := e.findRandomManager(members)
		if manager != nil {
			return &TriggerResult{
				ShouldTrigger: true,
				Trigger:       TriggerInfo{Type: TriggerTypeAuto, AgentID: manager.MemberID},
				Targets:       []AgentTarget{{AgentID: manager.MemberID, Mode: "agent"}},
			}, nil
		}
	}

	// Rule: last message from user + > timeout -> trigger manager-agent
	// This is evaluated by the periodic auto-trigger task, not per-message
	// Return false here; the periodic task will handle this
	return &TriggerResult{ShouldTrigger: false}, nil
}

// EvaluateAutoTriggerTimeout evaluates the timeout-based auto-trigger for a group.
// This should be called by the periodic task.
func (e *Evaluator) EvaluateAutoTriggerTimeout(
	ctx context.Context,
	lastMessage *models.GroupMessage,
	members []models.GroupMember,
) (*TriggerResult, error) {
	if lastMessage == nil {
		return &TriggerResult{ShouldTrigger: false}, nil
	}

	// Only trigger if last message is from a user
	if isAgentType(lastMessage.SenderType) {
		return &TriggerResult{ShouldTrigger: false}, nil
	}

	// Check if timeout has elapsed
	elapsed := time.Since(time.UnixMilli(lastMessage.CreateAtMs))
	if elapsed < e.autoTriggerTimeout {
		return &TriggerResult{ShouldTrigger: false}, nil
	}

	manager := e.findRandomManager(members)
	if manager != nil {
		return &TriggerResult{
			ShouldTrigger: true,
			Trigger:       TriggerInfo{Type: TriggerTypeAuto, AgentID: manager.MemberID},
			Targets:       []AgentTarget{{AgentID: manager.MemberID, Mode: "agent"}},
		}, nil
	}

	return &TriggerResult{ShouldTrigger: false}, nil
}

// findRandomManager returns a random manager-agent from the members.
func (e *Evaluator) findRandomManager(members []models.GroupMember) *models.GroupMember {
	managers := e.findAllManagers(members)
	if len(managers) == 0 {
		return nil
	}
	return &managers[rand.Intn(len(managers))]
}

// findAllManagers returns all manager-agents from the given members.
func (e *Evaluator) findAllManagers(members []models.GroupMember) []models.GroupMember {
	managers := make([]models.GroupMember, 0)
	for _, m := range members {
		if m.MemberType == models.MemberTypeManagerAgent {
			managers = append(managers, m)
		}
	}
	return managers
}

// ExtractMentionsFromText extracts all mentions from a message text for storage.
func ExtractMentionsFromText(text string, members []models.GroupMember) []models.Mention {
	mentions := make([]models.Mention, 0)
	if text == "" {
		return mentions
	}

	// Check for @all: include all members
	if strings.Contains(text, "@all") {
		for _, m := range members {
			mentions = append(mentions, models.Mention{
				MemberID:   m.MemberID,
				MemberName: m.MemberName,
				MemberType: string(m.MemberType),
			})
		}
		return mentions
	}

	re := regexp.MustCompile(`@([\w\-]+)`)
	matches := re.FindAllStringSubmatch(text, -1)

	mentionedIDs := make(map[string]bool)
	for _, match := range matches {
		if len(match) < 2 {
			continue
		}
		mention := match[1]

		for _, m := range members {
			if m.MemberID == mention || m.MemberName == mention {
				if !mentionedIDs[m.MemberID] {
					mentionedIDs[m.MemberID] = true
					mentions = append(mentions, models.Mention{
						MemberID:   m.MemberID,
						MemberName: m.MemberName,
						MemberType: string(m.MemberType),
					})
				}
				break
			}
		}
	}

	return mentions
}

// FormatTriggerForNATS formats trigger info for NATS pending message payload.
func FormatTriggerForNATS(trigger TriggerInfo, targets []AgentTarget) map[string]interface{} {
	return map[string]interface{}{
		"type":     string(trigger.Type),
		"agent_id": trigger.AgentID,
		"targets":  targets,
	}
}

// ParseTriggerFromNATS parses trigger info from NATS pending message payload.
func ParseTriggerFromNATS(data map[string]interface{}) (TriggerInfo, []AgentTarget, error) {
	triggerType, _ := data["type"].(string)
	agentID, _ := data["agent_id"].(string)

	trigger := TriggerInfo{
		Type:    TriggerType(triggerType),
		AgentID: agentID,
	}

	targets := make([]AgentTarget, 0)
	if t, ok := data["targets"].([]interface{}); ok {
		for _, item := range t {
			if m, ok := item.(map[string]interface{}); ok {
				agentID, _ := m["agent_id"].(string)
				mode, _ := m["mode"].(string)
				messageAppend, _ := m["message_append"].(string)
				targets = append(targets, AgentTarget{
					AgentID:       agentID,
					Mode:          mode,
					MessageAppend: messageAppend,
				})
			}
		}
	}

	return trigger, targets, nil
}
