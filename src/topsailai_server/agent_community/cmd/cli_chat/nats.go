// Package main provides optional NATS real-time event support for the ACS chat CLI.
package main

import (
	"encoding/json"
	"fmt"
	"sync"
	"time"

	"github.com/nats-io/nats.go"
)

// NATSClient wraps a NATS connection and subscription for group events.
type NATSClient struct {
	url       string
	conn      *nats.Conn
	sub       *nats.Subscription
	connected bool
	mu        sync.Mutex
	onMessage func(Message)
	onMember  func(Member)
}

// NewNATSClient creates a new NATS client.
func NewNATSClient(url string) *NATSClient {
	return &NATSClient{url: url}
}

// Connect establishes a NATS connection.
func (n *NATSClient) Connect() error {
	n.mu.Lock()
	defer n.mu.Unlock()
	if n.connected {
		return nil
	}
	nc, err := nats.Connect(n.url, nats.Timeout(5*time.Second))
	if err != nil {
		return err
	}
	n.conn = nc
	n.connected = true
	return nil
}

// IsConnected reports whether the NATS connection is active.
func (n *NATSClient) IsConnected() bool {
	n.mu.Lock()
	defer n.mu.Unlock()
	return n.connected && n.conn != nil && n.conn.IsConnected()
}

// Close closes the NATS connection.
func (n *NATSClient) Close() {
	n.mu.Lock()
	defer n.mu.Unlock()
	if n.sub != nil {
		_ = n.sub.Unsubscribe()
		n.sub = nil
	}
	if n.conn != nil {
		n.conn.Close()
		n.conn = nil
	}
	n.connected = false
}

// SubscribeGroup subscribes to group events for the given group ID.
func (n *NATSClient) SubscribeGroup(groupID string) error {
	n.mu.Lock()
	defer n.mu.Unlock()
	if !n.connected || n.conn == nil {
		return fmt.Errorf("not connected")
	}
	subject := fmt.Sprintf("%s.%s", getEnv("ACS_NATS_SUBJECT_GROUP_MESSAGE_PREFIX", "acs.group.message"), groupID)
	sub, err := n.conn.Subscribe(subject, func(msg *nats.Msg) {
		n.handleMessage(msg.Data)
	})
	if err != nil {
		return err
	}
	n.sub = sub
	return nil
}

func (n *NATSClient) handleMessage(data []byte) {
	var envelope struct {
		Type   string          `json:"type"`
		Action string          `json:"action"`
		Data   json.RawMessage `json:"data"`
	}
	if err := json.Unmarshal(data, &envelope); err != nil {
		return
	}
	switch envelope.Type {
	case "message":
		var msg Message
		if err := json.Unmarshal(envelope.Data, &msg); err == nil && n.onMessage != nil {
			n.onMessage(msg)
		}
	case "group_member":
		var member Member
		if err := json.Unmarshal(envelope.Data, &member); err == nil && n.onMember != nil {
			n.onMember(member)
		}
	}
}
