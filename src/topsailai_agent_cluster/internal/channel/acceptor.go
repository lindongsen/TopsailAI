package channel

import (
	"context"
	"crypto/tls"
	"errors"
	"net/http"
	"strconv"
	"sync"
	"time"

	"github.com/coder/websocket"
	"github.com/coder/websocket/wsjson"
	"topsailai_agent_cluster/internal/security"
)

// EndpointAcceptor accepts a Server-dialed channel connection. It is the mirror
// of Server.Handler: the Server dials, the Endpoint accepts, and the Server
// remains the sole authority for the connection generation. The Endpoint adopts
// the generation the Server allocated so fencing semantics stay identical in
// both directions.
type EndpointAcceptor struct {
	EndpointID     string
	ServerName     string
	TLSConfig      *tls.Config
	RevokedSerials map[string]bool
	Client         *EndpointClient
	OnReject       func(error)
	mu             sync.Mutex
	active         *websocket.Conn
}

// Handler accepts one Server-initiated WebSocket upgrade and attaches it to the
// Endpoint client so the existing read and send paths work unchanged.
func (a *EndpointAcceptor) Handler(w http.ResponseWriter, r *http.Request) {
	if a.Client == nil {
		http.Error(w, "endpoint client is not configured", http.StatusInternalServerError)
		return
	}
	if a.TLSConfig != nil {
		peer, err := peerCertificate(r)
		if err != nil {
			a.reject(err)
			http.Error(w, "mTLS client certificate required", http.StatusUnauthorized)
			return
		}
		if security.IsCertificateRevoked(peer, a.RevokedSerials) {
			a.reject(errCertificateRevoked(peer))
			http.Error(w, "client certificate revoked", http.StatusForbidden)
			return
		}
		if err := security.ValidateServerIdentity(peer, a.ServerName); err != nil {
			a.reject(err)
			http.Error(w, "server identity mismatch", http.StatusForbidden)
			return
		}
	}
	conn, err := websocket.Accept(w, r, &websocket.AcceptOptions{InsecureSkipVerify: true})
	if err != nil {
		a.reject(err)
		return
	}
	conn.SetReadLimit(channelReadLimit)
	var hello Frame
	if err := wsjson.Read(r.Context(), conn, &hello); err != nil {
		a.rejectHello(r.Context(), conn, hello, "invalid_hello", "invalid hello")
		return
	}
	if hello.Type != FrameHello || hello.ProtocolVersion != ProtocolVersion {
		a.rejectHello(r.Context(), conn, hello, "invalid_hello", "invalid hello")
		return
	}
	// An empty initiator is the legacy Endpoint-initiated handshake, which this
	// acceptor must never accept: it only serves connections the Server dialed.
	if hello.Initiator != InitiatorServer {
		a.rejectHello(r.Context(), conn, hello, "wrong_initiator", "acceptor requires a server-initiated connection")
		return
	}
	if hello.EndpointID != a.EndpointID {
		a.rejectHello(r.Context(), conn, hello, "wrong_endpoint", "hello targets another endpoint")
		return
	}
	// The Endpoint validates identity and initiator, then acknowledges. It does
	// not attach yet: the Server assigns the generation when it installs the
	// connection and sends it in hello_confirm, so both sides agree on which link
	// is authoritative. The acknowledgement carries the Endpoint identity because
	// the dialing Server records it on the Peer; without it the Server would store
	// an empty instance ID and a later disconnect could never be matched.
	ack := Frame{Type: FrameHelloAck, ProtocolVersion: ProtocolVersion, EndpointID: a.EndpointID, InstanceID: a.Client.InstanceID, Hostname: a.Client.Hostname, Initiator: InitiatorServer}
	if err := wsjson.Write(context.Background(), conn, ack); err != nil {
		a.reject(err)
		return
	}
	var confirm Frame
	if err := wsjson.Read(r.Context(), conn, &confirm); err != nil {
		a.reject(err)
		return
	}
	if confirm.Type != FrameHelloConfirm || confirm.EndpointID != a.EndpointID {
		a.reject(errors.New("invalid hello confirm"))
		_ = conn.Close(websocket.StatusPolicyViolation, "invalid hello confirm")
		return
	}
	generation, err := strconv.ParseInt(confirm.ConnectionGeneration, 10, 64)
	if err != nil || generation < 1 {
		a.reject(errors.New("invalid connection generation"))
		_ = conn.Close(websocket.StatusPolicyViolation, "invalid connection generation")
		return
	}
	a.mu.Lock()
	previous := a.active
	a.active = conn
	a.mu.Unlock()
	if previous != nil && previous != conn {
		_ = previous.Close(websocket.StatusNormalClosure, "replaced")
	}
	// A superseded connection must not confirm adoption: the Server would then
	// treat a link the Endpoint discarded as successfully established.
	if !a.Client.Attach(conn, generation, InitiatorServer) {
		_ = conn.Close(websocket.StatusNormalClosure, "superseded")
		return
	}
	// The Server waits for this frame before reporting success, so "successfully
	// established" means both sides adopted the same link.
	_ = wsjson.Write(context.Background(), conn, Frame{Type: FrameHelloAttached, ProtocolVersion: ProtocolVersion, EndpointID: a.EndpointID, ConnectionGeneration: strconv.FormatInt(generation, 10), Initiator: InitiatorServer})
}

// rejectHello explains a rejected handshake before closing the connection.
func (a *EndpointAcceptor) rejectHello(ctx context.Context, conn *websocket.Conn, hello Frame, reason, message string) {
	_ = wsjson.Write(ctx, conn, Frame{Type: FrameHelloRejected, ProtocolVersion: ProtocolVersion, RequestID: hello.RequestID, EndpointID: hello.EndpointID, Reason: reason})
	a.reject(errors.New(message))
	_ = conn.Close(websocket.StatusPolicyViolation, message)
}

func (a *EndpointAcceptor) reject(err error) {
	if a.OnReject != nil {
		a.OnReject(err)
	}
}

// Close closes the accepted connection, if any.
func (a *EndpointAcceptor) Close() error {
	a.mu.Lock()
	conn := a.active
	a.active = nil
	a.mu.Unlock()
	if conn == nil {
		return nil
	}
	return conn.Close(websocket.StatusNormalClosure, "closed")
}

// Serve starts an mTLS listener that accepts Server-initiated connections and
// serves them through the acceptor. It returns once the context is cancelled or
// the listener fails, so the caller can treat a returned error as fatal.
func (a *EndpointAcceptor) Serve(ctx context.Context, address string, tlsConfig *tls.Config) error {
	if address == "" {
		return errors.New("endpoint channel listen address is required")
	}
	if tlsConfig == nil {
		return errors.New("endpoint channel TLS configuration is required")
	}
	listener, err := tls.Listen("tcp", address, tlsConfig)
	if err != nil {
		return err
	}
	server := &http.Server{Handler: http.HandlerFunc(a.Handler), ReadHeaderTimeout: 10 * time.Second}
	go func() {
		<-ctx.Done()
		shutdownCtx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
		defer cancel()
		_ = server.Shutdown(shutdownCtx)
	}()
	if serveErr := server.Serve(listener); serveErr != nil && !errors.Is(serveErr, http.ErrServerClosed) {
		return serveErr
	}
	return nil
}
