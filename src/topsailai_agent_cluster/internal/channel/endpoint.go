package channel

import (
	"context"
	"crypto/tls"
	"errors"
	"fmt"
	"net/http"
	"net/url"
	"strconv"
	"sync"
	"time"

	"github.com/coder/websocket"
	"github.com/coder/websocket/wsjson"
)

// ErrAwaitingServerDial reports that the Endpoint cannot reconnect by itself
// because the Server dials in this direction. The caller must wait for the
// acceptor to attach a new connection instead of dialing.
var ErrAwaitingServerDial = errors.New("endpoint waits for a server-initiated connection")

// EndpointClient is the Endpoint-side channel transport. It supports both
// directions: the Endpoint may dial the Server, or it may accept a connection
// the Server dialed. Initiator records which direction produced the active
// connection so reconnect logic can repeat the same direction.
type EndpointClient struct {
	EndpointID     string
	InstanceID     string
	Hostname       string
	TLSConfig      *tls.Config
	Address        string
	ServerName     string
	RevokedSerials map[string]bool
	Initiator      string
	Conn           *websocket.Conn
	Generation     int64
	mu             sync.Mutex
}

// Dial establishes the Endpoint-initiated WebSocket connection and handshake.
func (c *EndpointClient) Dial(ctx context.Context, address string) error {
	if address == "" {
		return errors.New("channel address is required")
	}
	u, err := url.Parse(address)
	if err != nil {
		return err
	}
	if u.Scheme != "ws" && u.Scheme != "wss" {
		return errors.New("channel address must use ws or wss")
	}
	conn, _, err := websocket.Dial(ctx, address, &websocket.DialOptions{HTTPClient: &http.Client{Transport: &http.Transport{TLSClientConfig: c.TLSConfig}}})
	if err != nil {
		return err
	}
	conn.SetReadLimit(channelReadLimit)
	c.mu.Lock()
	previous := c.Conn
	c.Conn = conn
	c.Address = address
	c.mu.Unlock()
	if previous != nil && previous != conn {
		_ = previous.Close(websocket.StatusNormalClosure, "reconnecting")
	}
	if err := wsjson.Write(ctx, conn, Frame{Type: FrameHello, ProtocolVersion: ProtocolVersion, EndpointID: c.EndpointID, InstanceID: c.InstanceID, Hostname: c.Hostname, Initiator: InitiatorEndpoint}); err != nil {
		_ = conn.Close(websocket.StatusInternalError, "hello failed")
		return err
	}
	var ack Frame
	if err := wsjson.Read(ctx, conn, &ack); err != nil {
		_ = conn.Close(websocket.StatusInternalError, "hello ack failed")
		return err
	}
	if ack.Type == FrameHelloRejected {
		_ = conn.Close(websocket.StatusPolicyViolation, ack.Reason)
		return fmt.Errorf("channel hello rejected: %s", ack.Reason)
	}
	if ack.Type != FrameHelloAck || ack.ConnectionGeneration == "" {
		_ = conn.Close(websocket.StatusPolicyViolation, "invalid hello ack")
		return errors.New("invalid channel hello acknowledgement")
	}
	generation, err := strconv.ParseInt(ack.ConnectionGeneration, 10, 64)
	if err != nil || generation < 1 {
		_ = conn.Close(websocket.StatusPolicyViolation, "invalid generation")
		return errors.New("invalid channel connection generation")
	}
	c.mu.Lock()
	c.Generation = generation
	c.Initiator = InitiatorEndpoint
	c.mu.Unlock()
	return nil
}

// Attach adopts a connection the Server dialed. The Server allocated the
// generation, so the Endpoint records it rather than minting its own; fencing
// therefore behaves identically in both directions.
func (c *EndpointClient) Attach(conn *websocket.Conn, generation int64, initiator string) {
	c.mu.Lock()
	previous := c.Conn
	c.Conn = conn
	c.Generation = generation
	c.Initiator = initiator
	c.mu.Unlock()
	if previous != nil && previous != conn {
		_ = previous.Close(websocket.StatusNormalClosure, "replaced")
	}
}

// Ready reports whether the client has an authenticated active connection.
func (c *EndpointClient) Ready() bool {
	c.mu.Lock()
	defer c.mu.Unlock()
	return c.Conn != nil && c.Generation > 0
}

// Reconnect establishes a fresh authenticated channel using the configured address.
func (c *EndpointClient) Reconnect(ctx context.Context) error {
	c.mu.Lock()
	address := c.Address
	initiator := c.Initiator
	c.mu.Unlock()
	// In the server-initiated direction the Endpoint has no address to dial, so
	// it must wait for the acceptor to attach a new connection instead of
	// repeatedly failing a dial that can never succeed.
	if initiator == InitiatorServer {
		return ErrAwaitingServerDial
	}
	if address == "" {
		return errors.New("channel address is not configured")
	}
	return c.Dial(ctx, address)
}

// SendFrame writes one protocol frame on the active connection.
func (c *EndpointClient) SendFrame(ctx context.Context, frame Frame) error {
	c.mu.Lock()
	conn := c.Conn
	generation := c.Generation
	c.mu.Unlock()
	if conn == nil {
		return ErrOffline
	}
	if frame.ConnectionGeneration == "" {
		frame.ConnectionGeneration = strconv.FormatInt(generation, 10)
	}
	return wsjson.Write(ctx, conn, frame)
}

// SendHeartbeat sends a bounded liveness frame on the active connection.
func (c *EndpointClient) SendHeartbeat(ctx context.Context) error {
	c.mu.Lock()
	conn, generation := c.Conn, c.Generation
	c.mu.Unlock()
	if conn == nil {
		return ErrOffline
	}
	return wsjson.Write(ctx, conn, Frame{Type: FrameHeartbeat, ProtocolVersion: ProtocolVersion, ConnectionGeneration: strconv.FormatInt(generation, 10)})
}

// Read reads one server frame and rejects a generation change.
func (c *EndpointClient) Read(ctx context.Context) (Frame, error) {
	c.mu.Lock()
	conn, generation := c.Conn, c.Generation
	c.mu.Unlock()
	if conn == nil {
		return Frame{}, ErrOffline
	}
	var frame Frame
	if err := wsjson.Read(ctx, conn, &frame); err != nil {
		return Frame{}, err
	}
	if frame.ConnectionGeneration != "" && frame.ConnectionGeneration != strconv.FormatInt(generation, 10) {
		return Frame{}, ErrFenced
	}
	return frame, nil
}

// RunHeartbeat maintains application liveness until the context is cancelled.
func (c *EndpointClient) RunHeartbeat(ctx context.Context, interval time.Duration) error {
	if interval <= 0 {
		return errors.New("heartbeat interval must be positive")
	}
	ticker := time.NewTicker(interval)
	defer ticker.Stop()
	for {
		select {
		case <-ctx.Done():
			return ctx.Err()
		case <-ticker.C:
			if err := c.SendHeartbeat(ctx); err != nil {
				return err
			}
		}
	}
}

// Close closes the active channel.
func (c *EndpointClient) Close() error {
	c.mu.Lock()
	conn := c.Conn
	c.Conn = nil
	c.Generation = 0
	c.mu.Unlock()
	if conn == nil {
		return nil
	}
	return conn.Close(websocket.StatusNormalClosure, "closed")
}
