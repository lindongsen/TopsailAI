// Package main provides NATS subscription and HTTP polling fallback for the ACS CLI terminal.
package main

import (
	"context"
	"fmt"
	"sync"
	"time"

	natspkg "github.com/nats-io/nats.go"
	"github.com/topsailai/agent-community/internal/nats"
)

const (
	defaultGroupMessageSubjectPrefix = "acs.group.message."
	pollInterval                    = 2 * time.Second
)

// NATSManager manages NATS connection, subscription, and HTTP polling fallback.
type NATSManager struct {
	conn          *natspkg.Conn
	js            natspkg.JetStreamContext
	subscriber    *nats.Subscriber
	apiClient     *APIClient
	onEvent       func(*nats.PendingPublishMessage)
	groupID       string
	cancelPoll    context.CancelFunc
	pollWg        sync.WaitGroup
	mu            sync.Mutex
	connected     bool
	lastPollTime  int64
}

// NewNATSManager creates a new NATS manager.
func NewNATSManager(apiClient *APIClient, onEvent func(*nats.PendingPublishMessage)) *NATSManager {
	return &NATSManager{
		apiClient: apiClient,
		onEvent:   onEvent,
	}
}

// Connect establishes a connection to NATS servers.
func (m *NATSManager) Connect() error {
	servers := getEnv("ACS_NATS_SERVERS", defaultNATSServers)

	nc, err := natspkg.Connect(servers,
		natspkg.Name("acs-cli"),
		natspkg.ReconnectWait(2*time.Second),
		natspkg.MaxReconnects(10),
		natspkg.DisconnectErrHandler(func(_ *natspkg.Conn, err error) {
			printWarning(fmt.Sprintf("NATS disconnected: %v", err))
			m.setConnected(false)
		}),
		natspkg.ReconnectHandler(func(_ *natspkg.Conn) {
			printSuccess("NATS reconnected")
			m.setConnected(true)
		}),
	)
	if err != nil {
		printWarning(fmt.Sprintf("Failed to connect to NATS: %v", err))
		printInfo("Falling back to HTTP polling mode.")
		return fmt.Errorf("nats connect failed: %w", err)
	}

	js, err := nc.JetStream()
	if err != nil {
		nc.Close()
		printWarning(fmt.Sprintf("Failed to create JetStream context: %v", err))
		return fmt.Errorf("jetstream context failed: %w", err)
	}

	m.conn = nc
	m.js = js
	m.subscriber = nats.NewSubscriber(js, func(msg *nats.PendingPublishMessage) error {
		if m.onEvent != nil {
			m.onEvent(msg)
		}
		return nil
	})
	m.setConnected(true)
	printSuccess("Connected to NATS")
	return nil
}

// setConnected sets the connected state safely.
func (m *NATSManager) setConnected(v bool) {
	m.mu.Lock()
	defer m.mu.Unlock()
	m.connected = v
}

// IsConnected returns true if NATS is connected.
func (m *NATSManager) IsConnected() bool {
	m.mu.Lock()
	defer m.mu.Unlock()
	return m.connected
}

// SubscribeGroup subscribes to group events. If NATS is unavailable, starts HTTP polling.
func (m *NATSManager) SubscribeGroup(groupID string) error {
	m.groupID = groupID

	// Stop any existing polling goroutine to avoid leaks on re-subscription.
	if m.cancelPoll != nil {
		m.cancelPoll()
		m.pollWg.Wait()
		m.cancelPoll = nil
	}

	if m.IsConnected() && m.subscriber != nil {
		if err := m.subscriber.SubscribeGroup(groupID); err != nil {
			printWarning(fmt.Sprintf("Failed to subscribe via NATS: %v", err))
			printInfo("Falling back to HTTP polling mode.")
			m.startPolling(groupID)
			return nil
		}
		printSuccess(fmt.Sprintf("Subscribed to group %s via NATS", groupID))
		return nil
	}

	printInfo("NATS unavailable. Starting HTTP polling mode.")
	m.startPolling(groupID)
	return nil
}

// Unsubscribe stops NATS subscription and HTTP polling.
func (m *NATSManager) Unsubscribe() error {
	if m.cancelPoll != nil {
		m.cancelPoll()
		m.pollWg.Wait()
		m.cancelPoll = nil
	}

	if m.subscriber != nil {
		if err := m.subscriber.Unsubscribe(); err != nil {
			return err
		}
	}

	m.groupID = ""
	return nil
}

// startPolling starts HTTP polling for group messages every 2 seconds.
func (m *NATSManager) startPolling(groupID string) {
	ctx, cancel := context.WithCancel(context.Background())
	m.cancelPoll = cancel
	m.pollWg.Add(1)

	go func() {
		defer m.pollWg.Done()
		ticker := time.NewTicker(pollInterval)
		defer ticker.Stop()

		for {
			select {
			case <-ctx.Done():
				return
			case <-ticker.C:
				m.pollMessages(groupID)
			}
		}
	}()
}

// pollMessages fetches new messages via HTTP and dispatches them as events.
func (m *NATSManager) pollMessages(groupID string) {
	q := ListQuery{
		Limit:   50,
		OrderBy: "desc",
		SortKey: "create_at_ms",
	}

	resp, err := m.apiClient.ListMessages(groupID, q)
	if err != nil {
		return
	}

	var result struct {
		Items []map[string]interface{} `json:"items"`
	}
	if err := resp.GetData(&result); err != nil {
		return
	}

	if len(result.Items) == 0 {
		return
	}

	// Process messages from oldest to newest.
	var maxTime int64
	for i := len(result.Items) - 1; i >= 0; i-- {
		msg := result.Items[i]
		msgID, _ := msg["message_id"].(string)
		if msgID == "" {
			continue
		}

		// Use create_at_ms for deduplication instead of string comparison on UUIDs.
		var msgTime int64
		switch v := msg["create_at_ms"].(type) {
		case float64:
			msgTime = int64(v)
		case int64:
			msgTime = v
		case int:
			msgTime = int64(v)
		}

		if m.lastPollTime > 0 && msgTime > 0 && msgTime <= m.lastPollTime {
			continue
		}
		if msgTime > maxTime {
			maxTime = msgTime
		}

		if m.onEvent != nil {
			event := &nats.PendingPublishMessage{
				Type:    "message",
				Action:  "create",
				GroupID: groupID,
				Data:    msg,
			}
			m.onEvent(event)
		}
	}

	if maxTime > 0 {
		m.lastPollTime = maxTime
	}
}

// Close closes the NATS connection.
func (m *NATSManager) Close() {
	_ = m.Unsubscribe()
	if m.conn != nil {
		m.conn.Close()
	}
}
