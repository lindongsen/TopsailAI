// Package main provides optional NATS real-time event support for the ACS chat CLI.
package main

import (
	"encoding/json"
	"fmt"
	"sync"
	"time"

	"github.com/nats-io/nats.go"
)

// natsClient is the interface used by App for NATS real-time events.
// It is implemented by *NATSClient and by test fakes.
type natsClient interface {
	Connect() error
	SubscribeGroup(groupID string) error
	IsConnected() bool
	Messages() <-chan Message
	Members() <-chan Member
	Close()
}

// jetStreamSubscriber is the minimal JetStream interface needed by NATSClient.
// It is implemented by nats.JetStreamContext and by test fakes.
type jetStreamSubscriber interface {
	Subscribe(subj string, cb nats.MsgHandler, opts ...nats.SubOpt) (*nats.Subscription, error)
}

// jsSubscribeFunc is the JetStream subscribe function used by NATSClient.
// It is overridable by tests to avoid requiring a real NATS server.
var jsSubscribeFunc = func(js jetStreamSubscriber, subj string, cb nats.MsgHandler, opts ...nats.SubOpt) (*nats.Subscription, error) {
	return js.Subscribe(subj, cb, opts...)
}

// NATSClient wraps a NATS connection and JetStream subscription for group events.
type NATSClient struct {
	url       string
	conn      *nats.Conn
	js        jetStreamSubscriber
	sub       *nats.Subscription
	connected bool
	mu        sync.Mutex
	msgCh     chan Message
	memberCh  chan Member
}

// NewNATSClient creates a new NATS client.
func NewNATSClient(url string) *NATSClient {
	return &NATSClient{
		url:      url,
		msgCh:    make(chan Message, 64),
		memberCh: make(chan Member, 64),
	}
}

// Connect establishes a NATS connection and initializes JetStream.
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
	js, err := nc.JetStream()
	if err != nil {
		nc.Close()
		return fmt.Errorf("failed to create jetstream context: %w", err)
	}
	n.conn = nc
	n.js = js
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
	n.js = nil
	n.connected = false
}

// SubscribeGroup subscribes to group events for the given group ID.
// It uses a JetStream ephemeral consumer so multiple CLI sessions can
// independently receive all real-time events for the group.
func (n *NATSClient) SubscribeGroup(groupID string) error {
	n.mu.Lock()
	defer n.mu.Unlock()
	if !n.connected || n.js == nil {
		return fmt.Errorf("not connected")
	}
	subject := fmt.Sprintf("%s.%s", getEnv("ACS_NATS_SUBJECT_GROUP_MESSAGE_PREFIX", "acs.group.message"), groupID)
	sub, err := jsSubscribeFunc(n.js, subject, func(msg *nats.Msg) {
		n.handleMessage(msg.Data)
		_ = msg.Ack()
	}, nats.ManualAck())
	if err != nil {
		return err
	}
	n.sub = sub
	return nil
}

// Messages returns the channel of incoming messages.
func (n *NATSClient) Messages() <-chan Message {
	return n.msgCh
}

// Members returns the channel of incoming member events.
func (n *NATSClient) Members() <-chan Member {
	return n.memberCh
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
		if err := json.Unmarshal(envelope.Data, &msg); err != nil {
			return
		}
		select {
		case n.msgCh <- msg:
		default:
		}
	case "group_member":
		var member Member
		if err := json.Unmarshal(envelope.Data, &member); err != nil {
			return
		}
		select {
		case n.memberCh <- member:
		default:
		}
	}
}
