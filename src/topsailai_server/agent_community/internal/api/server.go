// Package api provides HTTP API routing and server setup for the ACS service.
package api

import (
	"context"
	"fmt"
	"net/http"
	"os"
	"os/signal"
	"syscall"
	"time"

	"github.com/topsailai/agent-community/internal/config"
	"github.com/topsailai/agent-community/pkg/logger"
)

// Server wraps an HTTP server with graceful shutdown support.
type Server struct {
	httpServer *http.Server
	log        *logger.Logger
}

// NewServer creates a new HTTP server with the given router and configuration.
func NewServer(cfg *config.Config, router *Router, log *logger.Logger) *Server {
	addr := fmt.Sprintf("%s:%d", cfg.Server.GetListenAddress(), cfg.Server.Port)

	httpServer := &http.Server{
		Addr:         addr,
		Handler:      router.Engine(),
		ReadTimeout:  cfg.Server.ReadTimeout,
		WriteTimeout: cfg.Server.WriteTimeout,
	}

	return &Server{
		httpServer: httpServer,
		log:        log,
	}
}

// Start starts the HTTP server and blocks until shutdown.
func (s *Server) Start() error {
	s.log.Info("api", "", "starting http server", "addr", s.httpServer.Addr)

	// Start server in a goroutine
	errChan := make(chan error, 1)
	go func() {
		if err := s.httpServer.ListenAndServe(); err != nil && err != http.ErrServerClosed {
			errChan <- err
		}
	}()

	// Wait for interrupt signal or server error
	sigChan := make(chan os.Signal, 1)
	signal.Notify(sigChan, syscall.SIGINT, syscall.SIGTERM)

	select {
	case err := <-errChan:
		s.log.Error("api", "", "http server error", "error", err.Error())
		return err
	case sig := <-sigChan:
		s.log.Info("api", "", "received shutdown signal", "signal", sig.String())
		return s.Shutdown()
	}
}

// Shutdown gracefully shuts down the HTTP server.
func (s *Server) Shutdown() error {
	s.log.Info("api", "", "shutting down http server")

	ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
	defer cancel()

	if err := s.httpServer.Shutdown(ctx); err != nil {
		s.log.Error("api", "", "http server shutdown error", "error", err.Error())
		return err
	}

	s.log.Info("api", "", "http server stopped gracefully")
	return nil
}
