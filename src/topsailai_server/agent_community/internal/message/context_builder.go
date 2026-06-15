// Package message provides context message building for agent consumption.
package message

import (
	"fmt"
	"strings"
	"time"

	"github.com/topsailai/agent-community/internal/models"
)

// ContextBuilder builds context messages for agent consumption.
type ContextBuilder struct{}

// NewContextBuilder creates a new context builder.
func NewContextBuilder() *ContextBuilder {
	return &ContextBuilder{}
}

// BuildContext builds the context messages for an agent.
// If lastReadMessageID is empty: init_context_message + recent 1 day messages.
// If lastReadMessageID exists: messages from lastReadMessageID to pendingMessage (inclusive).
func (cb *ContextBuilder) BuildContext(
	group *models.Group,
	members []models.GroupMember,
	agentMember *models.GroupMember,
	allMessages []models.GroupMessage,
	lastReadMessageID string,
	pendingMessage *models.GroupMessage,
) (string, error) {
	if group == nil || agentMember == nil || pendingMessage == nil {
		return "", fmt.Errorf("group, agent member, and pending message are required")
	}

	var contextMessages []models.GroupMessage
	var initContext string

	if lastReadMessageID == "" {
		// No last_read_message_id: init context + recent 1 day messages
		contextMessages = cb.getRecentMessages(allMessages, pendingMessage, 24*time.Hour)
		initContext = cb.buildInitContext(group, members, agentMember)
	} else {
		// Has last_read_message_id: messages from lastReadMessageID to pendingMessage (inclusive)
		contextMessages = cb.getMessagesFromLastRead(allMessages, lastReadMessageID, pendingMessage)
	}

	// Build message context
	messageContext := cb.buildMessageContext(contextMessages)

	if initContext != "" {
		return initContext + "\n" + messageContext, nil
	}
	return messageContext, nil
}

// getRecentMessages returns messages within the recent duration up to pendingMessage.
func (cb *ContextBuilder) getRecentMessages(
	allMessages []models.GroupMessage,
	pendingMessage *models.GroupMessage,
	duration time.Duration,
) []models.GroupMessage {
	cutoff := time.Now().Add(-duration).UnixMilli()
	result := make([]models.GroupMessage, 0)

	for _, msg := range allMessages {
		if msg.MessageID == pendingMessage.MessageID {
			continue
		}
		if msg.CreateAtMs >= cutoff && msg.CreateAtMs <= pendingMessage.CreateAtMs {
			result = append(result, msg)
		}
	}

	// Include the pending message itself
	result = append(result, *pendingMessage)

	return result
}

// getMessagesFromLastRead returns messages from lastReadMessageID to pendingMessage (inclusive).
func (cb *ContextBuilder) getMessagesFromLastRead(
	allMessages []models.GroupMessage,
	lastReadMessageID string,
	pendingMessage *models.GroupMessage,
) []models.GroupMessage {
	result := make([]models.GroupMessage, 0)
	foundStart := false

	for _, msg := range allMessages {
		if msg.MessageID == lastReadMessageID {
			foundStart = true
		}

		if foundStart {
			result = append(result, msg)
			if msg.MessageID == pendingMessage.MessageID {
				break
			}
		}
	}

	return result
}

// buildInitContext builds the init context message as specified in ORIGIN.md.
func (cb *ContextBuilder) buildInitContext(
	group *models.Group,
	members []models.GroupMember,
	agentMember *models.GroupMember,
) string {
	var sb strings.Builder

	// Group info
	sb.WriteString(fmt.Sprintf("## group\n"))
	sb.WriteString(fmt.Sprintf("id=%s\n", group.GroupID))
	sb.WriteString(fmt.Sprintf("name=%s\n\n", group.GroupName))

	// Group context
	sb.WriteString("> GROUP CONTEXT START\n")
	if group.GroupContext != "" {
		sb.WriteString(group.GroupContext)
		sb.WriteString("\n")
	}
	sb.WriteString("> GROUP CONTEXT END\n\n")

	// Group members
	sb.WriteString("## group_member\n\n")
	for _, m := range members {
		sb.WriteString(fmt.Sprintf("- id: %s\n", m.MemberID))
		sb.WriteString(fmt.Sprintf("  name: %s\n", m.MemberName))
		if m.MemberDescription != "" {
			sb.WriteString(fmt.Sprintf("  description: %s\n", m.MemberDescription))
		}
		sb.WriteString(fmt.Sprintf("  type: %s\n\n", m.MemberType))
	}

	// ME (Receiver)
	sb.WriteString(fmt.Sprintf("## ME (Receiver)\n\n"))
	sb.WriteString(fmt.Sprintf("I AM `%s`(%s)\n", agentMember.MemberName, agentMember.MemberID))

	return sb.String()
}

// buildMessageContext builds the message context from messages.
func (cb *ContextBuilder) buildMessageContext(messages []models.GroupMessage) string {
	if len(messages) == 0 {
		return ""
	}

	var sb strings.Builder
	sb.WriteString("\n## Messages\n\n")

	var msgTexts []string
	for _, msg := range messages {
		if msg.IsDeleted {
			continue
		}
		var msgSb strings.Builder
		msgSb.WriteString(cb.formatMessage(&msg))
		msgTexts = append(msgTexts, msgSb.String())
	}

	if len(msgTexts) == 0 {
		return sb.String()
	}

	for _, text := range msgTexts {
		sb.WriteString("---\n")
		sb.WriteString(text)
		sb.WriteString("\n")
	}
	sb.WriteString("---\n")

	return sb.String()
}

// formatMessage formats a single message according to the send message format.
func (cb *ContextBuilder) formatMessage(msg *models.GroupMessage) string {
	var sb strings.Builder

	sb.WriteString(fmt.Sprintf("> sender: id=%s, name=%s\n", msg.SenderID, getSenderName(msg)))
	sb.WriteString(fmt.Sprintf("> message:\n"))
	sb.WriteString(msg.MessageText)

	return sb.String()
}

// getSenderName returns the sender name from a message.
// Since GroupMessage doesn't store sender name, we return sender_id as fallback.
func getSenderName(msg *models.GroupMessage) string {
	// Try to extract from mentions if available
	// For now, return sender_id as name fallback
	return msg.SenderID
}

// BuildAgentResponseMessage builds a new GroupMessage from an agent's response.
func (cb *ContextBuilder) BuildAgentResponseMessage(
	groupID string,
	agentMember *models.GroupMember,
	responseText string,
	processedMsgID string,
	messageID string,
) *models.GroupMessage {
	return &models.GroupMessage{
		GroupID:        groupID,
		MessageID:      messageID,
		MessageText:    responseText,
		SenderID:       agentMember.MemberID,
		SenderType:     agentMember.MemberType,
		ProcessedMsgID: processedMsgID,
		IsDeleted:      false,
	}
}

// BuildSystemErrorMessage builds a system error message as manager-agent.
func (cb *ContextBuilder) BuildSystemErrorMessage(
	groupID string,
	managerAgent *models.GroupMember,
	errorText string,
	processedMsgID string,
	messageID string,
) *models.GroupMessage {
	return &models.GroupMessage{
		GroupID:        groupID,
		MessageID:      messageID,
		MessageText:    fmt.Sprintf("[System Error] %s", errorText),
		SenderID:       managerAgent.MemberID,
		SenderType:     models.MemberTypeManagerAgent,
		ProcessedMsgID: processedMsgID,
		IsDeleted:      false,
	}
}
