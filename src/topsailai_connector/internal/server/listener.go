package server

import (
	"context"
	"crypto/tls"
	"errors"
	"fmt"
	"log/slog"
	"net"
	"net/http"
	"sync/atomic"
	"time"

	"github.com/gorilla/websocket"

	"topsailai_connector/internal/protocol"
)

// ChannelPath is the path the channel is served at.
//
// The path is part of the contract, not an implementation detail: a reverse proxy
// that forwards /v1/ and /channel differently depends on it, so changing it is a
// breaking change to the deployment.
const ChannelPath = "/channel"

// shutdownTimeout bounds a graceful shutdown.
//
// A shutdown that waits forever is a shutdown that never completes, and the
// operator then kills the process, which is the outcome the graceful path exists
// to avoid.
const shutdownTimeout = 10 * time.Second

// Listener serves both surfaces from one listener.
//
// One listener is chosen because two would mean two TLS certificates, two firewall
// rules and two reverse-proxy entries for one service, and because the two
// surfaces share the same registry: a CLI request is routed to a Node connection
// that the channel surface owns. Splitting the listeners would not split the
// state, so it would buy isolation that does not exist.
//
// The consequence is stated plainly in the design: the CLI API is reachable by
// anyone who can reach the channel port. That is acceptable because the API
// authenticates every request with the client token before it reads the node
// token, and because a caller who can reach the port can already attempt a hello.
type Listener struct {
	config      Config
	registry    *Registry
	handler     *Handler
	logger      *slog.Logger
	upgrader    websocket.Upgrader
	generations atomic.Uint64

	server   *http.Server
	listener net.Listener
}

// NewListener builds the listener.
//
// A nil logger falls back to the default logger. A nil registry is not
// substituted, because a listener that cannot route has no answer to give and
// inventing one would be inventing a routing decision.
func NewListener(config Config, registry *Registry, logger *slog.Logger) (*Listener, error) {
	if registry == nil {
		return nil, fmt.Errorf("registry is nil")
	}
	if logger == nil {
		logger = slog.Default()
	}

	listener := &Listener{
		config:   config,
		registry: registry,
		logger:   logger,
		upgrader: websocket.Upgrader{
			ReadBufferSize:  4096,
			WriteBufferSize: 4096,
			// The origin check is disabled because the channel is not a browser
			// surface: a Node is a program with no origin, and a browser cannot
			// present a tunnel token it does not hold. The tunnel token is the
			// authentication, and it is checked before any frame is served.
			CheckOrigin: func(*http.Request) bool { return true },
		},
	}

	// The handler is built here rather than passed in, so the two surfaces cannot
	// be wired to different registries. A caller that supplied its own handler
	// could route the CLI API to a registry the channel never registers into, and
	// the symptom would be a Node that looks connected and answers node_offline.
	listener.handler = NewHandler(config, registry, listener, logger)

	return listener, nil
}

// Forward sends one request to one Node.
//
// It implements Forwarder, so the CLI API reaches a Node through the same registry
// the channel registers into. The lookup happens per request rather than being
// cached, because a cached connection would keep answering after the Node
// reconnected and the answer would come from a connection the Node has abandoned.
func (l *Listener) Forward(ctx context.Context, nodeID string, request protocol.Request) (protocol.Response, error) {
	live, present := l.registry.Lookup(nodeID)
	if !present {
		return protocol.Response{}, ErrNodeOffline
	}

	forwarder, ok := live.(Forwarder)
	if !ok {
		return protocol.Response{}, fmt.Errorf("connection for %q cannot forward", nodeID)
	}
	return forwarder.Forward(ctx, nodeID, request)
}

// Handler returns the HTTP handler serving both surfaces.
//
// It is exposed so a test can drive the surfaces without binding a port, and so a
// deployment that terminates TLS in front of the Server can mount the same handler
// in its own server.
func (l *Listener) Handler() http.Handler {
	mux := http.NewServeMux()
	mux.HandleFunc(ChannelPath, l.serveChannel)
	mux.Handle(OperationPathPrefix, l.handler)
	return mux
}

// Serve binds the configured address and serves until the context is cancelled.
//
// The bind happens before the first log line, so a failure to bind is reported as
// a startup failure rather than as a Server that appears to be running. The
// returned error is the reason serving stopped, and a clean shutdown returns nil.
func (l *Listener) Serve(ctx context.Context) error {
	address := l.config.Listen
	network := "tcp"

	listener, err := net.Listen(network, address)
	if err != nil {
		return fmt.Errorf("listen on %s: %w", address, err)
	}
	l.listener = listener

	if l.config.TLSEnabled() {
		certificate, err := tls.LoadX509KeyPair(l.config.TLSCert, l.config.TLSKey)
		if err != nil {
			_ = listener.Close()
			return fmt.Errorf("load the TLS key pair: %w", err)
		}
		listener = tls.NewListener(listener, &tls.Config{
			Certificates: []tls.Certificate{certificate},
			MinVersion:   tls.VersionTLS12,
		})
	}

	l.server = &http.Server{
		Handler:           l.Handler(),
		ReadHeaderTimeout: 10 * time.Second,
		// The write timeout is deliberately unset: a forwarded request is bounded
		// by the configured request timeout, and a second bound here would cut a
		// slow but healthy answer short with a transport error instead of the
		// node_timeout the caller can act on.
	}

	l.logger.Info("server listening",
		"listen", address,
		"tls", l.config.TLSEnabled(),
		"channel_path", ChannelPath,
		"operation_path_prefix", OperationPathPrefix,
	)

	serveErr := make(chan error, 1)
	go func() {
		serveErr <- l.server.Serve(listener)
	}()

	select {
	case err := <-serveErr:
		if errors.Is(err, http.ErrServerClosed) {
			return nil
		}
		return err
	case <-ctx.Done():
		return l.shutdown()
	}
}

// shutdown stops the listener and closes every live channel.
//
// The channels are closed after the HTTP server stops accepting, so a Node that is
// mid-request is not cut off by a shutdown that has already decided to stop
// answering. Every channel is closed even when an earlier one fails, because a
// shutdown that stops at the first error leaves the remaining Nodes connected to a
// Server that is going away.
func (l *Listener) shutdown() error {
	ctx, cancel := context.WithTimeout(context.Background(), shutdownTimeout)
	defer cancel()

	var first error
	if l.server != nil {
		if err := l.server.Shutdown(ctx); err != nil {
			first = fmt.Errorf("shut down the http server: %w", err)
		}
	}
	if err := l.registry.CloseAll(); err != nil && first == nil {
		first = fmt.Errorf("close the live channels: %w", err)
	}

	l.logger.Info("server stopped")
	return first
}

// Addr returns the address the listener bound.
//
// It is read after Serve has bound, so a test can bind port zero and then learn
// which port the kernel chose. Before the bind it returns the configured address,
// which is what a startup log reports.
func (l *Listener) Addr() string {
	if l.listener != nil {
		return l.listener.Addr().String()
	}
	return l.config.Listen
}
