package server

import (
	"context"
	"crypto/tls"
	"errors"
	"log/slog"
	"net"
	"net/http"
	"sync"
	"time"

	"topsailai_agent_cluster/internal/channel"
	"topsailai_agent_cluster/internal/protocol"
	serverstorage "topsailai_agent_cluster/internal/storage/server"
)

// ServiceDeps contains explicit dependencies for the Server lifecycle.
type ServiceDeps struct {
	APIHandler           http.Handler
	ChannelServer        *channel.Server
	Storage              *serverstorage.Store
	Logger               *slog.Logger
	APIListenAddress     string
	ChannelListenAddress string
	ChannelTLSConfig     *tls.Config
	OnChannelFrame       func(channel.Peer, channel.Frame)
	OnReceipt            func(channel.Peer, protocol.ExecutionReceipt)
}

// Service owns the API and mTLS channel listeners.
type Service struct {
	apiHandler   http.Handler
	channel      *channel.Server
	storage      *serverstorage.Store
	logger       *slog.Logger
	apiAddress   string
	channelAddr  string
	channelTLS   *tls.Config
	onFrame      func(channel.Peer, channel.Frame)
	onReceipt    func(channel.Peer, protocol.ExecutionReceipt)
	mu           sync.Mutex
	apiListener  net.Listener
	chanListener net.Listener
	apiHTTP      *http.Server
	chanHTTP     *http.Server
	cancel       context.CancelFunc
	wg           sync.WaitGroup
	closeOnce    sync.Once
	closeErr     error
}

// NewService constructs a Server lifecycle service from explicit dependencies.
func NewService(deps ServiceDeps) (*Service, error) {
	if deps.APIHandler == nil || deps.ChannelServer == nil || deps.Storage == nil {
		return nil, errors.New("API handler, channel server, and storage are required")
	}
	if deps.APIListenAddress == "" || deps.ChannelTLSConfig == nil {
		return nil, errors.New("API listen address and channel TLS configuration are required")
	}
	return &Service{apiHandler: deps.APIHandler, channel: deps.ChannelServer, storage: deps.Storage, logger: deps.Logger, apiAddress: deps.APIListenAddress, channelAddr: deps.ChannelListenAddress, channelTLS: deps.ChannelTLSConfig, onFrame: deps.OnChannelFrame, onReceipt: deps.OnReceipt}, nil
}

// Run starts the API listener, plus the channel listener when one is
// configured, and waits until the context is cancelled. A server-initiated
// deployment configures no channel listen address because the Server dials every
// Endpoint, so the channel listener is optional while the API listener is not.
func (s *Service) Run(ctx context.Context) error {
	if ctx == nil {
		return errors.New("context is required")
	}
	apiListener, err := net.Listen("tcp", s.apiAddress)
	if err != nil {
		return err
	}
	var channelListener net.Listener
	if s.channelAddr != "" {
		channelListener, err = tls.Listen("tcp", s.channelAddr, s.channelTLS)
		if err != nil {
			_ = apiListener.Close()
			return err
		}
	}
	if s.onFrame != nil {
		s.channel.OnFrame = s.onFrame
	}
	if s.onReceipt != nil {
		s.channel.OnReceipt = s.onReceipt
	}
	runCtx, cancel := context.WithCancel(ctx)
	s.mu.Lock()
	s.apiListener, s.chanListener, s.cancel = apiListener, channelListener, cancel
	s.apiHTTP = &http.Server{Handler: s.apiHandler, ReadHeaderTimeout: 10 * time.Second}
	s.mu.Unlock()
	s.wg.Add(1)
	go s.serve(runCtx, s.apiHTTP, apiListener)
	if channelListener != nil {
		s.mu.Lock()
		s.chanHTTP = &http.Server{Handler: http.HandlerFunc(s.channel.Handler), ReadHeaderTimeout: 10 * time.Second}
		s.mu.Unlock()
		s.wg.Add(1)
		go s.serve(runCtx, s.chanHTTP, channelListener)
	}
	<-runCtx.Done()
	cancel()
	s.shutdown()
	s.wg.Wait()
	return nil
}

func (s *Service) serve(ctx context.Context, server *http.Server, listener net.Listener) {
	defer s.wg.Done()
	err := server.Serve(listener)
	if err != nil && !errors.Is(err, http.ErrServerClosed) && ctx.Err() == nil && s.logger != nil {
		s.logger.Error("listener stopped", "error", err)
	}
}

func (s *Service) shutdown() {
	shutdownCtx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	s.mu.Lock()
	apiHTTP, chanHTTP := s.apiHTTP, s.chanHTTP
	apiListener, chanListener := s.apiListener, s.chanListener
	s.mu.Unlock()
	if apiHTTP != nil {
		_ = apiHTTP.Shutdown(shutdownCtx)
	}
	if chanHTTP != nil {
		_ = chanHTTP.Shutdown(shutdownCtx)
	}
	if apiListener != nil {
		_ = apiListener.Close()
	}
	if chanListener != nil {
		_ = chanListener.Close()
	}
	_ = s.channel.Close()
}

// Close gracefully stops both listeners and closes channel and storage resources.
func (s *Service) Close() error {
	s.closeOnce.Do(func() {
		if s.cancel != nil {
			s.cancel()
			s.shutdown()
		}
		s.wg.Wait()
		if err := s.storage.Close(); err != nil {
			s.closeErr = err
		}
	})
	return s.closeErr
}
