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

// subscription is an internal abstraction over *nats.Subscription so that
// Subscriber can be unit-tested without a real NATS server.
type subscription interface {
	Unsubscribe() error
}

// jsSubscribe wraps the JetStream Subscribe call. In production it delegates
// directly to the NATS client; tests can replace it to inject fake subscriptions.
var jsSubscribe = func(js nats.JetStreamContext, subj string, cb nats.MsgHandler, opts ...nats.SubOpt) (subscription, error) {
	sub, err := js.Subscribe(subj, cb, opts...)
	if err != nil {
		return nil, err
	}
	return sub, nil
}

// Subscriber subscribes to NATS subjects for real-time updates.
type Subscriber struct {
	js      nats.JetStreamContext
	subs    []subscription
	handler MessageHandler
	acker   func(*nats.Msg) error
}

// NewSubscriber creates a new NATS subscriber.
func NewSubscriber(js nats.JetStreamContext, handler MessageHandler) *Subscriber {
	return &Subscriber{
		js:      js,
		subs:    make([]subscription, 0),
		handler: handler,
		acker:   func(msg *nats.Msg) error { return msg.Ack() },
	}
}

// SubscribeGroup subscribes to group events for a specific group.
func (s *Subscriber) SubscribeGroup(groupID string) error {
	subject := groupMessageSubjectPrefix + groupID

	sub, err := jsSubscribe(s.js, subject, func(msg *nats.Msg) {
		if err := s.handleMessage(msg); err != nil {
			logger.Error("failed to handle group message", "subject", subject, "error", err)
		}
		if err := s.acker(msg); err != nil {
			logger.Error("failed to ack group message", "subject", subject, "error", err)
		}
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

	sub, err := jsSubscribe(s.js, subject, func(msg *nats.Msg) {
		if err := s.handleMessage(msg); err != nil {
			logger.Error("failed to handle group message", "subject", subject, "error", err)
		}
		if err := s.acker(msg); err != nil {
			logger.Error("failed to ack group message", "subject", subject, "error", err)
		}
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

	sub, err := jsSubscribe(s.js, subject, func(msg *nats.Msg) {
		logger.Debug("received pending message", "subject", subject, "data", string(msg.Data))
		if err := s.acker(msg); err != nil {
			logger.Error("failed to ack pending message", "subject", subject, "error", err)
		}
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

	sub, err := jsSubscribe(s.js, subject, func(msg *nats.Msg) {
		var heartbeat map[string]interface{}
		if err := json.Unmarshal(msg.Data, &heartbeat); err != nil {
			logger.Error("failed to unmarshal heartbeat", "error", err)
			if err := s.acker(msg); err != nil {
				logger.Error("failed to ack heartbeat", "error", err)
			}
			return
		}

		nodeID, _ := heartbeat["node_id"].(string)
		timestampFloat, _ := heartbeat["timestamp"].(float64)
		timestamp := int64(timestampFloat)

		if handler != nil {
			handler(nodeID, timestamp)
		}
		if err := s.acker(msg); err != nil {
			logger.Error("failed to ack heartbeat", "error", err)
		}
	}, nats.Durable("heartbeat-monitor"), nats.ManualAck())
	if err != nil {
		return fmt.Errorf("failed to subscribe to heartbeats: %w", err)
	}

	s.subs = append(s.subs, sub)
	logger.Info("subscribed to heartbeats", "subject", subject)
	return nil
}
