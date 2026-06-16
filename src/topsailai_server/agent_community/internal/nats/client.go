// Package nats provides NATS integration for the ACS service.
package nats

import (
	"fmt"
	"time"

	"github.com/nats-io/nats.go"
	"github.com/topsailai/agent-community/internal/config"
	"github.com/topsailai/agent-community/pkg/logger"
)

const (
	lockBucketName = "acs_locks"
	lockTTL        = 7200 * time.Second

	pendingMessagesStream = "acs_pending_messages"
	groupEventsStream     = "acs_group_events"

	pendingMessageSubjectPrefix = "acs.group.pending-message."
	groupMessageSubjectPrefix   = "acs.group.message."

	queueGroupName = "pending-message-workers"
)

// Client wraps NATS connection and JetStream management.
type Client struct {
	cfg  *config.NATSConfig
	conn *nats.Conn
	js   nats.JetStreamContext
	kv   nats.KeyValue
}

// NewClient creates a new NATS client.
func NewClient(cfg *config.NATSConfig) *Client {
	return &Client{cfg: cfg}
}

// Connect establishes connection to NATS and initializes JetStream.
func (c *Client) Connect() error {
	servers := c.cfg.Servers
	if servers == "" {
		servers = nats.DefaultURL
	}

	nc, err := nats.Connect(servers,
		nats.Name("acs-server"),
		nats.ReconnectWait(2*time.Second),
		nats.MaxReconnects(10),
		nats.DisconnectErrHandler(func(_ *nats.Conn, err error) {
			logger.Error("nats disconnected", "error", err)
		}),
		nats.ReconnectHandler(func(_ *nats.Conn) {
			logger.Info("nats reconnected")
		}),
	)
	if err != nil {
		return fmt.Errorf("failed to connect to nats: %w", err)
	}
	c.conn = nc

	js, err := nc.JetStream()
	if err != nil {
		return fmt.Errorf("failed to create jetstream context: %w", err)
	}
	c.js = js

	if err := c.createLockBucket(); err != nil {
		return fmt.Errorf("failed to create lock bucket: %w", err)
	}

	if err := c.createStreams(); err != nil {
		return fmt.Errorf("failed to create streams: %w", err)
	}

	logger.Info("nats client connected", "servers", servers)
	return nil
}

// createLockBucket creates the KV bucket for distributed locks.
func (c *Client) createLockBucket() error {
	// Try to get existing bucket first
	kv, err := c.js.KeyValue(lockBucketName)
	if err == nil {
		c.kv = kv
		return nil
	}

	// Bucket does not exist, create it
	kv, err = c.js.CreateKeyValue(&nats.KeyValueConfig{
		Bucket: lockBucketName,
		TTL:    lockTTL,
	})
	if err != nil {
		return fmt.Errorf("failed to create lock bucket: %w", err)
	}
	c.kv = kv
	return nil
}

// createStreams creates JetStream streams for pending messages and group events.
func (c *Client) createStreams() error {
	// Pending messages stream: work-queue for agent processing
	_, err := c.js.AddStream(&nats.StreamConfig{
		Name:      pendingMessagesStream,
		Subjects:  []string{pendingMessageSubjectPrefix + ">"},
		Retention: nats.WorkQueuePolicy,
		MaxMsgs:   -1,
		MaxBytes:  -1,
		MaxAge:    7 * 24 * time.Hour,
		Storage:   nats.FileStorage,
		Replicas:  1,
	})
	if err != nil {
		if err == nats.ErrStreamNameAlreadyInUse {
			logger.Info("pending messages stream already exists", "stream", pendingMessagesStream)
		} else {
			return fmt.Errorf("failed to create pending messages stream: %w", err)
		}
	}

	// Group events stream: limits policy for pub/sub
	_, err = c.js.AddStream(&nats.StreamConfig{
		Name:      groupEventsStream,
		Subjects:  []string{groupMessageSubjectPrefix + ">"},
		Retention: nats.LimitsPolicy,
		MaxMsgs:   10000,
		MaxBytes:  100 * 1024 * 1024, // 100MB
		MaxAge:    24 * time.Hour,
		Storage:   nats.FileStorage,
		Replicas:  1,
	})
	if err != nil {
		if err == nats.ErrStreamNameAlreadyInUse {
			logger.Info("group events stream already exists", "stream", groupEventsStream)
		} else {
			return fmt.Errorf("failed to create group events stream: %w", err)
		}
	}

	return nil
}

// CreatePendingMessageConsumer creates a durable consumer for pending messages.
func (c *Client) CreatePendingMessageConsumer(handler nats.MsgHandler) (*nats.Subscription, error) {
	if c.js == nil {
		return nil, fmt.Errorf("failed to create pending message consumer: jetstream context not initialized")
	}

	consumerName := "pending-message-consumer"
	var requestedAckWait time.Duration

	if !c.cfg.PendingMessageNoAck {
		ackWaitSeconds := c.cfg.AckWaitSeconds
		if ackWaitSeconds <= 0 {
			ackWaitSeconds = 3600 // default 1 hour
		}
		requestedAckWait = time.Duration(ackWaitSeconds) * time.Second

		// Check if consumer already exists with different AckWait
		info, err := c.js.ConsumerInfo(pendingMessagesStream, consumerName)
		if err != nil {
			// Consumer does not exist, proceed with creation
			if err != nats.ErrConsumerNotFound {
				// Log unexpected error but continue
				logger.Warn("failed to check existing consumer info", "error", err)
			}
		} else {
			// Consumer exists, compare AckWait
			existingAckWait := info.Config.AckWait
			if existingAckWait != requestedAckWait {
				return nil, fmt.Errorf(
					"NATS consumer \"%s\" already exists with different AckWait configuration.\n"+
					"  Existing AckWait: %s\n"+
					"  Requested AckWait: %s\n\n"+
					"To fix this, delete the existing consumer and restart the service:\n"+
					"  nats consumer rm %s %s -f\n\n"+
					"Note: Unacknowledged messages will be redelivered after the consumer is recreated.",
					consumerName, existingAckWait.String(), requestedAckWait.String(),
					pendingMessagesStream, consumerName,
				)
			}
		}
	}

	var subOpts []nats.SubOpt

	subOpts = append(subOpts,
		nats.Durable(consumerName),
		nats.MaxDeliver(3),
	)

	if c.cfg.PendingMessageNoAck {
		// Fire-and-forget mode: no ack required from consumer
		subOpts = append(subOpts, nats.AckNone())
		logger.Info("nats consumer created with no-ack mode (fire-and-forget)")
	} else {
		// Reliable mode: manual ack with configurable ack wait
		subOpts = append(subOpts, nats.ManualAck())
		subOpts = append(subOpts, nats.AckWait(requestedAckWait))
		subOpts = append(subOpts, nats.MaxAckPending(10))
		logger.Info("nats consumer created with manual-ack mode", "ack_wait", requestedAckWait.String())
	}

	sub, err := c.js.QueueSubscribe(
		pendingMessageSubjectPrefix+">",
		queueGroupName,
		handler,
		subOpts...,
	)
	if err != nil {
		return nil, fmt.Errorf("failed to create pending message consumer: %w", err)
	}
	return sub, nil
}

// JetStream returns the JetStream context.
func (c *Client) JetStream() nats.JetStreamContext {
	return c.js
}

// KV returns the KeyValue store for distributed locks.
func (c *Client) KV() nats.KeyValue {
	return c.kv
}

// Conn returns the NATS connection.
func (c *Client) Conn() *nats.Conn {
	return c.conn
}

// Close closes the NATS connection.
func (c *Client) Close() {
	if c.conn != nil {
		c.conn.Close()
		logger.Info("nats client disconnected")
	}
}
