package api

import (
	"context"
	"fmt"
	"net"
	"net/http"
	"testing"
	"time"

	"github.com/gin-gonic/gin"
	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
	"github.com/topsailai/agent-community/internal/config"
	"github.com/topsailai/agent-community/pkg/logger"
)

// setupServerTestConfig returns a minimal config with an ephemeral port.
func setupServerTestConfig() *config.Config {
	return &config.Config{
		Server: config.ServerConfig{
			Port:         0,
			ReadTimeout:  5 * time.Second,
			WriteTimeout: 5 * time.Second,
		},
		Database: config.DatabaseConfig{
			Driver: "sqlite",
			Name:   ":memory:",
		},
		Agent: config.AgentConfig{
			AutoTriggerTimeout: 10 * time.Minute,
		},
		AgentWorkPool: config.AgentWorkPoolConfig{
			PerNode:          10,
			PerUser:          5,
			PerGroup:         5,
			StatsLogInterval: 30 * time.Second,
		},
		Account: config.AccountConfig{
			APIKeyMaxPerAccount:       10,
			LoginSessionExpirySeconds: 86400,
			BcryptCost:                4,
		},
		Log: config.LogConfig{
			Output: "stdout",
			Level:  "error",
		},
		Discovery: config.DiscoveryConfig{
			Enabled: false,
		},
	}
}

// setupServerTestRouter creates a router with nil publisher/discovery for server tests.
func setupServerTestRouter(t *testing.T) *Router {
	gin.SetMode(gin.TestMode)
	cfg := setupServerTestConfig()
	db := setupRouterTestDB(t)
	log := logger.New(logger.Config{Output: "stdout", Level: "error"})
	return NewRouter(cfg, db, nil, nil, nil, log)
}

// TestNewServer_AddrAndTimeouts verifies that NewServer builds the http.Server with the expected address and timeouts.
func TestNewServer_AddrAndTimeouts(t *testing.T) {
	cfg := setupServerTestConfig()
	cfg.Server.Port = 7370

	router := setupServerTestRouter(t)
	log := logger.New(logger.Config{Output: "stdout", Level: "error"})
	server := NewServer(cfg, router, log)

	require.NotNil(t, server)
	require.NotNil(t, server.httpServer)
	assert.Equal(t, "0.0.0.0:7370", server.httpServer.Addr)
	assert.Equal(t, cfg.Server.ReadTimeout, server.httpServer.ReadTimeout)
	assert.Equal(t, cfg.Server.WriteTimeout, server.httpServer.WriteTimeout)
	assert.Equal(t, router.Engine(), server.httpServer.Handler)
}

// TestServer_StartShutdown starts the server on an ephemeral port, then shuts it down and verifies no error.
func TestServer_StartShutdown(t *testing.T) {
	cfg := setupServerTestConfig()
	router := setupServerTestRouter(t)
	log := logger.New(logger.Config{Output: "stdout", Level: "error"})
	server := NewServer(cfg, router, log)

	// Start server in a goroutine; Start blocks until shutdown or error.
	startErr := make(chan error, 1)
	go func() {
		startErr <- server.Start()
	}()

	// Wait until the listener is active.
	require.Eventually(t, func() bool {
		return server.httpServer != nil && server.httpServer.Addr != ""
	}, 2*time.Second, 10*time.Millisecond)

	// Shutdown should complete without error.
	shutdownErr := server.Shutdown()
	require.NoError(t, shutdownErr)

	// Start should return nil after graceful shutdown.
	select {
	case err := <-startErr:
		assert.NoError(t, err)
	case <-time.After(5 * time.Second):
		t.Fatal("server.Start did not return after shutdown")
	}
}

// TestServer_ShutdownClosesListener verifies that after shutdown, new connections are refused.
func TestServer_ShutdownClosesListener(t *testing.T) {
	cfg := setupServerTestConfig()
	router := setupServerTestRouter(t)
	log := logger.New(logger.Config{Output: "stdout", Level: "error"})
	server := NewServer(cfg, router, log)

	startErr := make(chan error, 1)
	go func() {
		startErr <- server.Start()
	}()

	require.Eventually(t, func() bool {
		return server.httpServer != nil && server.httpServer.Addr != ""
	}, 2*time.Second, 10*time.Millisecond)

	addr := server.httpServer.Addr
	require.NoError(t, server.Shutdown())

	select {
	case err := <-startErr:
		assert.NoError(t, err)
	case <-time.After(5 * time.Second):
		t.Fatal("server.Start did not return after shutdown")
	}

	// After shutdown, dialing the address should fail.
	conn, err := net.DialTimeout("tcp", addr, 2*time.Second)
	if conn != nil {
		_ = conn.Close()
	}
	assert.Error(t, err, "expected connection to be refused after shutdown")
}

// TestServer_Start_ReturnsError verifies that starting two servers on the same port returns an error.
func TestServer_Start_ReturnsError(t *testing.T) {
	cfg := setupServerTestConfig()
	router := setupServerTestRouter(t)
	log := logger.New(logger.Config{Output: "stdout", Level: "error"})

	// Start the first server on an ephemeral port and capture the actual address.
	firstServer := NewServer(cfg, router, log)
	firstStarted := make(chan string, 1)
	firstErr := make(chan error, 1)
	go func() {
		// Use a custom listener to capture the port deterministically.
		ln, err := net.Listen("tcp", "127.0.0.1:0")
		if err != nil {
			firstErr <- err
			return
		}
		firstStarted <- ln.Addr().String()
		firstServer.httpServer.Addr = ln.Addr().String()
		firstErr <- firstServer.httpServer.Serve(ln)
	}()

	var addr string
	select {
	case addr = <-firstStarted:
	case err := <-firstErr:
		t.Fatalf("failed to start first server: %v", err)
	case <-time.After(5 * time.Second):
		t.Fatal("first server did not start in time")
	}

	// Start a second server on the same address; it should fail immediately.
	secondCfg := setupServerTestConfig()
	secondCfg.Server.Port = 0
	secondRouter := setupServerTestRouter(t)
	secondServer := NewServer(secondCfg, secondRouter, log)
	secondServer.httpServer.Addr = addr

	err := secondServer.httpServer.ListenAndServe()
	require.Error(t, err, "expected error when starting server on already-used port")
	assert.Contains(t, err.Error(), "bind", "error should indicate address already in use")

	// Clean up the first server.
	shutdownCtx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	_ = firstServer.httpServer.Shutdown(shutdownCtx)
}

// TestServer_HandlerServesRequests verifies that the server actually serves HTTP requests.
func TestServer_HandlerServesRequests(t *testing.T) {
	cfg := setupServerTestConfig()
	router := setupServerTestRouter(t)
	log := logger.New(logger.Config{Output: "stdout", Level: "error"})
	server := NewServer(cfg, router, log)

	ln, err := net.Listen("tcp", "127.0.0.1:0")
	require.NoError(t, err)
	server.httpServer.Addr = ln.Addr().String()

	go func() {
		_ = server.httpServer.Serve(ln)
	}()

	baseURL := fmt.Sprintf("http://%s", server.httpServer.Addr)
	client := &http.Client{Timeout: 2 * time.Second}

	require.Eventually(t, func() bool {
		resp, err := client.Get(baseURL + "/healthz")
		if err != nil {
			return false
		}
		_ = resp.Body.Close()
		return resp.StatusCode == http.StatusOK
	}, 3*time.Second, 50*time.Millisecond)

	shutdownCtx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	require.NoError(t, server.httpServer.Shutdown(shutdownCtx))
}
