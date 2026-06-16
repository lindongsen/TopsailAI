// Package nats provides NATS integration for the ACS service.
package nats

import (
	"encoding/json"
	"fmt"
	"time"

	"github.com/nats-io/nats.go"
	"github.com/topsailai/agent-community/internal/models"
	"github.com/topsailai/agent-community/pkg/logger"
)

// PendingPublishMessage represents a message published to group events subject.
type PendingPublishMessage struct {
	Type    string      `json:"type"`
	Action  string      `json:"action"`
	GroupID string      `json:"groupId"`
	Data    interface{} `json:"data"`
}

// PendingMessagePayload represents a pending message sent to NATS for agent processing.
type PendingMessagePayload struct {
	models.GroupMessage
	Trigger interface{} `json:"trigger"`
}

// Publisher publishes messages to NATS subjects.
type Publisher struct {
	js nats.JetStreamContext
}

// NewPublisher creates a new NATS publisher.
func NewPublisher(js nats.JetStreamContext) *Publisher {
	return &Publisher{js: js}
}

// PublishPendingMessage publishes a pending message to the pending-message subject.
func (p *Publisher) PublishPendingMessage(groupID string, msg *models.GroupMessage, trigger interface{}) error {
	subject := pendingMessageSubjectPrefix + groupID

	payload := PendingMessagePayload{
		GroupMessage: *msg,
		Trigger:      trigger,
	}

	data, err := json.Marshal(payload)
	if err != nil {
		return fmt.Errorf("failed to marshal pending message: %w", err)
	}

	// MsgID dedup: use message_id as MsgID
	msgID := msg.MessageID
	_, err = p.js.Publish(subject, data, nats.MsgId(msgID))
	if err != nil {
		return fmt.Errorf("failed to publish pending message: %w", err)
	}

	logger.Info("pending message published", "subject", subject, "message_id", msgID)
	return nil
}

// PublishGroupEvent publishes a group event to the group message subject.
func (p *Publisher) PublishGroupEvent(eventType, action, groupID string, data interface{}) error {
	subject := groupMessageSubjectPrefix + groupID

	event := PendingPublishMessage{
		Type:    eventType,
		Action:  action,
		GroupID: groupID,
		Data:    data,
	}

	payload, err := json.Marshal(event)
	if err != nil {
		return fmt.Errorf("failed to marshal group event: %w", err)
	}

	_, err = p.js.Publish(subject, payload)
	if err != nil {
		return fmt.Errorf("failed to publish group event: %w", err)
	}

	logger.Info("group event published", "subject", subject, "type", eventType, "action", action)
	return nil
}

// PublishMessageCreate publishes a message create event.
func (p *Publisher) PublishMessageCreate(msg *models.GroupMessage) error {
	return p.PublishGroupEvent("message", "create", msg.GroupID, msg)
}

// PublishMessageModify publishes a message modify event.
func (p *Publisher) PublishMessageModify(msg *models.GroupMessage) error {
	return p.PublishGroupEvent("message", "modify", msg.GroupID, msg)
}

// PublishMessageDelete publishes a message delete event.
func (p *Publisher) PublishMessageDelete(msg *models.GroupMessage) error {
	return p.PublishGroupEvent("message", "delete", msg.GroupID, msg)
}

// PublishGroupCreate publishes a group create event.
func (p *Publisher) PublishGroupCreate(group *models.Group) error {
	return p.PublishGroupEvent("group", "create", group.GroupID, group)
}

// PublishGroupModify publishes a group modify event.
func (p *Publisher) PublishGroupModify(group *models.Group) error {
	return p.PublishGroupEvent("group", "modify", group.GroupID, group)
}

// PublishGroupDelete publishes a group delete event.
func (p *Publisher) PublishGroupDelete(groupID string) error {
	return p.PublishGroupEvent("group", "delete", groupID, map[string]string{"group_id": groupID})
}

// PublishGroupMemberCreate publishes a group member create event.
func (p *Publisher) PublishGroupMemberCreate(member *models.GroupMember) error {
	return p.PublishGroupEvent("group_member", "create", member.GroupID, member)
}

// PublishGroupMemberDelete publishes a group_member delete event.
func (p *Publisher) PublishGroupMemberDelete(groupID, memberID string) error {
	return p.PublishGroupEvent("group_member", "delete", groupID, map[string]string{
		"group_id":  groupID,
		"member_id": memberID,
	})
}

// PublishGroupMemberModify publishes a group_member modify event.
func (p *Publisher) PublishGroupMemberModify(member *models.GroupMember) error {
	return p.PublishGroupEvent("group_member", "modify", member.GroupID, member)
}

// PublishAgentResponse publishes an agent response message as a group event.
func (p *Publisher) PublishAgentResponse(msg *models.GroupMessage) error {
	return p.PublishMessageCreate(msg)
}

// PublishSystemError publishes a system error message as a group event.
func (p *Publisher) PublishSystemError(msg *models.GroupMessage) error {
	return p.PublishMessageCreate(msg)
}

// PublishAutoTriggerPendingMessage publishes an auto-trigger pending message.
func (p *Publisher) PublishAutoTriggerPendingMessage(groupID string, msg *models.GroupMessage, trigger interface{}) error {
	return p.PublishPendingMessage(groupID, msg, trigger)
}

// BuildMsgID builds a deduplication MsgID for JetStream using message_id and agent_id.
func BuildMsgID(messageID, agentID string) string {
	return fmt.Sprintf("%s:%s", messageID, agentID)
}

// PublishPendingMessageWithAgentID publishes a pending message with agent-specific MsgID for dedup.
func (p *Publisher) PublishPendingMessageWithAgentID(groupID string, msg *models.GroupMessage, trigger interface{}, agentID string) error {
	subject := pendingMessageSubjectPrefix + groupID

	payload := PendingMessagePayload{
		GroupMessage: *msg,
		Trigger:      trigger,
	}

	data, err := json.Marshal(payload)
	if err != nil {
		return fmt.Errorf("failed to marshal pending message: %w", err)
	}

	msgID := BuildMsgID(msg.MessageID, agentID)
	_, err = p.js.Publish(subject, data, nats.MsgId(msgID))
	if err != nil {
		return fmt.Errorf("failed to publish pending message with agent id: %w", err)
	}

	logger.Info("pending message published with agent id", "subject", subject, "message_id", msgID, "agent_id", agentID)
	return nil
}

// PublishHeartbeat publishes a heartbeat message (for monitoring).
func (p *Publisher) PublishHeartbeat(nodeID string) error {
	subject := "acs.heartbeat"
	payload := map[string]interface{}{
		"node_id":    nodeID,
		"timestamp":  time.Now().UnixMilli(),
		"status":     "healthy",
	}

	data, err := json.Marshal(payload)
	if err != nil {
		return fmt.Errorf("failed to marshal heartbeat: %w", err)
	}

	_, err = p.js.Publish(subject, data)
	if err != nil {
		return fmt.Errorf("failed to publish heartbeat: %w", err)
	}

	return nil
}
