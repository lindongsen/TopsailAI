// Package nats provides NATS integration for the ACS service.
package nats

import (
	"encoding/json"
	"fmt"

	"github.com/nats-io/nats.go"
	"github.com/topsailai/agent-community/pkg/logger"
)

// MessageHandler is a callback function for handling received messages.
type MessageHandler func(msg *PendingPublishMessage) error

// Subscriber subscribes to NATS subjects for real-time updates.
type Subscriber struct {
	js       nats.JetStreamContext
	subs     []*nats.Subscription
	handler  MessageHandler
}

// NewSubscriber creates a new NATS subscriber.
func NewSubscriber(js nats.JetStreamContext, handler MessageHandler) *Subscriber {
	return &Subscriber{
		js:      js,
		subs:    make([]*nats.Subscription, 0),
		handler: handler,
	}
}

// SubscribeGroup subscribes to group events for a specific group.
func (s *Subscriber) SubscribeGroup(groupID string) error {
	subject := groupMessageSubjectPrefix + groupID

	sub, err := s.js.Subscribe(subject, func(msg *nats.Msg) {
		if err := s.handleMessage(msg); err != nil {
			logger.Error("failed to handle group message", "subject", subject, "error", err)
		}
		msg.Ack()
	}, nats.Durable("cli-"+groupID), nats.ManualAck())
	if err != nil {
		return fmt.Errorf("failed to subscribe to group %s: %w", groupID, err)
	}

	s.subs = append(s.subs, sub)
	logger.Info("subscribed to group events", "group_id", groupID, "subject", subject)
	return nil
}

// SubscribeGroups subscribes to group events for multiple groups.
func (s *Subscriber) SubscribeGroups(groupIDs []string) error {
	for _, groupID := range groupIDs {
		if err := s.SubscribeGroup(groupID); err != nil {
			return fmt.Errorf("failed to subscribe to group %s: %w", groupID, err)
		}
	}
	return nil
}

// SubscribeAllGroups subscribes to all group events using wildcard.
func (s *Subscriber) SubscribeAllGroups() error {
	subject := groupMessageSubjectPrefix + ">"

	sub, err := s.js.Subscribe(subject, func(msg *nats.Msg) {
		if err := s.handleMessage(msg); err != nil {
			logger.Error("failed to handle group message", "subject", subject, "error", err)
		}
		msg.Ack()
	}, nats.Durable("cli-all-groups"), nats.ManualAck())
	if err != nil {
		return fmt.Errorf("failed to subscribe to all groups: %w", err)
	}

	s.subs = append(s.subs, sub)
	logger.Info("subscribed to all group events", "subject", subject)
	return nil
}

// handleMessage handles an incoming NATS message.
func (s *Subscriber) handleMessage(msg *nats.Msg) error {
	var event PendingPublishMessage
	if err := json.Unmarshal(msg.Data, &event); err != nil {
		return fmt.Errorf("failed to unmarshal message: %w", err)
	}

	if s.handler != nil {
		if err := s.handler(&event); err != nil {
			return fmt.Errorf("handler error: %w", err)
		}
	}

	return nil
}

// Unsubscribe unsubscribes from all active subscriptions.
func (s *Subscriber) Unsubscribe() error {
	for _, sub := range s.subs {
		if err := sub.Unsubscribe(); err != nil {
			logger.Error("failed to unsubscribe", "error", err)
		}
	}
	s.subs = s.subs[:0]
	logger.Info("unsubscribed from all group events")
	return nil
}

// IsSubscribed returns true if there are active subscriptions.
func (s *Subscriber) IsSubscribed() bool {
	return len(s.subs) > 0
}

// SubscriptionCount returns the number of active subscriptions.
func (s *Subscriber) SubscriptionCount() int {
	return len(s.subs)
}

// SubscribePendingMessages subscribes to pending messages for a specific group (for monitoring).
func (s *Subscriber) SubscribePendingMessages(groupID string) error {
	subject := pendingMessageSubjectPrefix + groupID

	sub, err := s.js.Subscribe(subject, func(msg *nats.Msg) {
		logger.Debug("received pending message", "subject", subject, "data", string(msg.Data))
		msg.Ack()
	}, nats.Durable("pending-monitor-"+groupID), nats.ManualAck())
	if err != nil {
		return fmt.Errorf("failed to subscribe to pending messages for group %s: %w", groupID, err)
	}

	s.subs = append(s.subs, sub)
	logger.Info("subscribed to pending messages", "group_id", groupID, "subject", subject)
	return nil
}

// SubscribeHeartbeats subscribes to heartbeat messages (for monitoring).
func (s *Subscriber) SubscribeHeartbeats(handler func(nodeID string, timestamp int64)) error {
	subject := "acs.heartbeat"

	sub, err := s.js.Subscribe(subject, func(msg *nats.Msg) {
		var heartbeat map[string]interface{}
		if err := json.Unmarshal(msg.Data, &heartbeat); err != nil {
			logger.Error("failed to unmarshal heartbeat", "error", err)
			msg.Ack()
			return
		}

		nodeID, _ := heartbeat["node_id"].(string)
		timestampFloat, _ := heartbeat["timestamp"].(float64)
		timestamp := int64(timestampFloat)

		if handler != nil {
			handler(nodeID, timestamp)
		}
		msg.Ack()
	}, nats.Durable("heartbeat-monitor"), nats.ManualAck())
	if err != nil {
		return fmt.Errorf("failed to subscribe to heartbeats: %w", err)
	}

	s.subs = append(s.subs, sub)
	logger.Info("subscribed to heartbeats", "subject", subject)
	return nil
}
