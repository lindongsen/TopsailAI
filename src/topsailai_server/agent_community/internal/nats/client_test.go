// Package nats provides NATS client tests.
package nats

import (
	"testing"
	"time"

	"github.com/nats-io/nats-server/v2/server"
	"github.com/nats-io/nats.go"
	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
	"github.com/topsailai/agent-community/internal/config"
)

// startEmbeddedNATSServer starts an embedded NATS server for testing.
func startEmbeddedNATSServer(t *testing.T) *server.Server {
	t.Helper()

	opts := &server.Options{
		Port: -1, // Random port
		JetStream: true,
		StoreDir: t.TempDir(),
	}

	s, err := server.NewServer(opts)
	require.NoError(t, err)

	go s.Start()
	if !s.ReadyForConnections(5 * time.Second) {
		t.Fatal("NATS server did not start")
	}

	t.Cleanup(func() {
		s.Shutdown()
	})

	return s
}

// getTestConfig returns a NATS config pointing to the embedded server.
func getTestConfig(t *testing.T, srv *server.Server) *config.NATSConfig {
	t.Helper()
	return &config.NATSConfig{
		Servers:                           srv.ClientURL(),
		StreamGroup:                       "acs_test",
		SubjectGroupPendingMessagePrefix:  "acs.group.pending-message",
		SubjectGroupMessagePrefix:        "acs.group.message",
		PendingMessageNoAck:              false,
		AckWaitSeconds:                   3600,
		MaxDeliver:                       0,
	}
}

func TestNewClient(t *testing.T) {
	cfg := &config.NATSConfig{
		Servers: "nats://localhost:4222",
	}
	client := NewClient(cfg)
	require.NotNil(t, client)
	assert.Nil(t, client.Conn())
	assert.Nil(t, client.JetStream())
	assert.Nil(t, client.KV())
}

func TestClient_Connect(t *testing.T) {
	t.Run("connects successfully", func(t *testing.T) {
		srv := startEmbeddedNATSServer(t)
		cfg := getTestConfig(t, srv)
		client := NewClient(cfg)

		err := client.Connect()
		require.NoError(t, err)
		defer client.Close()

		assert.NotNil(t, client.Conn())
		assert.NotNil(t, client.JetStream())
		assert.NotNil(t, client.KV())
	})

	t.Run("uses default URL when servers is empty", func(t *testing.T) {
		cfg := &config.NATSConfig{
			Servers: "",
		}
		client := NewClient(cfg)

		// When servers is empty, it should use nats.DefaultURL
		// If no server is running at default URL, it should fail
		err := client.Connect()
		// The connection may succeed or fail depending on whether
		// a NATS server is running at the default URL
		// We just verify it doesn't panic and handles the empty string
		if err != nil {
			assert.Contains(t, err.Error(), "failed to connect to nats")
		}
	})

	t.Run("fails with invalid URL", func(t *testing.T) {
		cfg := &config.NATSConfig{
			Servers: "invalid-url",
		}
		client := NewClient(cfg)

		err := client.Connect()
		require.Error(t, err)
		assert.Contains(t, err.Error(), "failed to connect to nats")
	})
}

func TestClient_createLockBucket(t *testing.T) {
	t.Run("creates lock bucket", func(t *testing.T) {
		srv := startEmbeddedNATSServer(t)
		cfg := getTestConfig(t, srv)
		client := NewClient(cfg)

		err := client.Connect()
		require.NoError(t, err)
		defer client.Close()

		// Bucket should be created
		kv := client.KV()
		require.NotNil(t, kv)

		// Verify bucket exists by trying to get it again
		js := client.JetStream()
		kv2, err := js.KeyValue(lockBucketName)
		require.NoError(t, err)
		assert.NotNil(t, kv2)
	})

	t.Run("reuses existing lock bucket", func(t *testing.T) {
		srv := startEmbeddedNATSServer(t)
		cfg := getTestConfig(t, srv)
		client := NewClient(cfg)

		err := client.Connect()
		require.NoError(t, err)
		defer client.Close()

		// Create a new client that connects to the same server
		// The bucket should already exist
		client2 := NewClient(cfg)
		err = client2.Connect()
		require.NoError(t, err)
		defer client2.Close()

		assert.NotNil(t, client2.KV())
	})
}

func TestClient_createStreams(t *testing.T) {
	t.Run("creates streams", func(t *testing.T) {
		srv := startEmbeddedNATSServer(t)
		cfg := getTestConfig(t, srv)
		client := NewClient(cfg)

		err := client.Connect()
		require.NoError(t, err)
		defer client.Close()

		// Verify streams exist
		js := client.JetStream()
		streamInfo, err := js.StreamInfo(pendingMessagesStream)
		require.NoError(t, err)
		assert.Equal(t, pendingMessagesStream, streamInfo.Config.Name)

		streamInfo, err = js.StreamInfo(groupEventsStream)
		require.NoError(t, err)
		assert.Equal(t, groupEventsStream, streamInfo.Config.Name)
	})

	t.Run("handles existing streams", func(t *testing.T) {
		srv := startEmbeddedNATSServer(t)
		cfg := getTestConfig(t, srv)
		client := NewClient(cfg)

		err := client.Connect()
		require.NoError(t, err)
		defer client.Close()

		// Connect again - streams should already exist
		client2 := NewClient(cfg)
		err = client2.Connect()
		require.NoError(t, err)
		defer client2.Close()
	})
}

func TestClient_CreatePendingMessageConsumer(t *testing.T) {
	t.Run("creates consumer in reliable mode", func(t *testing.T) {
		srv := startEmbeddedNATSServer(t)
		cfg := getTestConfig(t, srv)
		client := NewClient(cfg)

		err := client.Connect()
		require.NoError(t, err)
		defer client.Close()

		handler := func(msg *nats.Msg) {
			// No-op handler
		}

		sub, err := client.CreatePendingMessageConsumer(handler)
		require.NoError(t, err)
		defer sub.Unsubscribe()

		assert.NotNil(t, sub)
	})

	t.Run("fails to create consumer in no-ack mode on workqueue stream", func(t *testing.T) {
		// Note: NATS workqueue streams require explicit ack.
		// Creating a no-ack consumer on a workqueue stream will fail.
		srv := startEmbeddedNATSServer(t)
		cfg := getTestConfig(t, srv)
		cfg.PendingMessageNoAck = true
		client := NewClient(cfg)

		err := client.Connect()
		require.NoError(t, err)
		defer client.Close()

		handler := func(msg *nats.Msg) {
			// No-op handler
		}

		_, err = client.CreatePendingMessageConsumer(handler)
		require.Error(t, err)
		assert.Contains(t, err.Error(), "workqueue stream requires explicit ack")
	})

	t.Run("fails when not connected", func(t *testing.T) {
		cfg := &config.NATSConfig{}
		client := NewClient(cfg)

		handler := func(msg *nats.Msg) {
			// No-op handler
		}

		_, err := client.CreatePendingMessageConsumer(handler)
		require.Error(t, err)
		assert.Contains(t, err.Error(), "jetstream context not initialized")
	})

	t.Run("reuses existing consumer with same ack wait", func(t *testing.T) {
		srv := startEmbeddedNATSServer(t)
		cfg := getTestConfig(t, srv)
		client := NewClient(cfg)

		err := client.Connect()
		require.NoError(t, err)
		defer client.Close()

		handler := func(msg *nats.Msg) {
			// No-op handler
		}

		// Create consumer first time
		sub1, err := client.CreatePendingMessageConsumer(handler)
		require.NoError(t, err)
		defer sub1.Unsubscribe()

		// Create consumer second time - should reuse
		sub2, err := client.CreatePendingMessageConsumer(handler)
		require.NoError(t, err)
		defer sub2.Unsubscribe()
	})

	t.Run("fails when consumer exists with different ack wait", func(t *testing.T) {
		srv := startEmbeddedNATSServer(t)
		cfg := getTestConfig(t, srv)
		client := NewClient(cfg)

		err := client.Connect()
		require.NoError(t, err)
		defer client.Close()

		handler := func(msg *nats.Msg) {
			// No-op handler
		}

		// Create consumer first time
		sub1, err := client.CreatePendingMessageConsumer(handler)
		require.NoError(t, err)
		defer sub1.Unsubscribe()

		// Create a new client with different AckWait
		cfg2 := getTestConfig(t, srv)
		cfg2.AckWaitSeconds = 7200
		client2 := NewClient(cfg2)

		err = client2.Connect()
		require.NoError(t, err)
		defer client2.Close()

		_, err = client2.CreatePendingMessageConsumer(handler)
		require.Error(t, err)
		assert.Contains(t, err.Error(), "already exists with different AckWait")
	})
}

func TestClient_Getters(t *testing.T) {
	t.Run("returns nil when not connected", func(t *testing.T) {
		cfg := &config.NATSConfig{}
		client := NewClient(cfg)

		assert.Nil(t, client.Conn())
		assert.Nil(t, client.JetStream())
		assert.Nil(t, client.KV())
	})

	t.Run("returns values when connected", func(t *testing.T) {
		srv := startEmbeddedNATSServer(t)
		cfg := getTestConfig(t, srv)
		client := NewClient(cfg)

		err := client.Connect()
		require.NoError(t, err)
		defer client.Close()

		assert.NotNil(t, client.Conn())
		assert.NotNil(t, client.JetStream())
		assert.NotNil(t, client.KV())
	})
}

func TestClient_Close(t *testing.T) {
	t.Run("closes connection when connected", func(t *testing.T) {
		srv := startEmbeddedNATSServer(t)
		cfg := getTestConfig(t, srv)
		client := NewClient(cfg)

		err := client.Connect()
		require.NoError(t, err)

		assert.True(t, client.Conn().IsConnected())

		client.Close()

		assert.False(t, client.Conn().IsConnected())
	})

	t.Run("does not panic when not connected", func(t *testing.T) {
		cfg := &config.NATSConfig{}
		client := NewClient(cfg)

		// Should not panic
		client.Close()
	})
}

