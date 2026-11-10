package server

import (
	"context"
	"crypto/rand"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"log/slog"
	"net/http"
	"sync"
	"sync/atomic"
	"time"

	"github.com/gorilla/websocket"

	"topsailai_connector/internal/protocol"
	"topsailai_connector/internal/security"
)

// MaxChannelMessageBytes bounds one message on the channel.
//
// The bound exists because the message is decoded before it is interpreted, so an
// unbounded message is the peer deciding how much memory the Server spends. It
// matches the Node's frame payload cap, so a frame the Node accepted is never
// refused here for size alone.
const MaxChannelMessageBytes = 1 << 20

// handshakeTimeout bounds the hello exchange.
//
// A connection that opens and then says nothing is a connection holding a file
// descriptor and a goroutine. The timeout is short because hello is the first
// frame: a peer that needs longer than this to send it is not a peer that is
// about to work.
const handshakeTimeout = 10 * time.Second

// writeTimeout bounds one frame write.
//
// A write to a peer that has stopped reading blocks once the socket buffer fills.
// Without a deadline that block is permanent, and it holds the write mutex, so
// every other request on the channel waits behind it.
const writeTimeout = 10 * time.Second

// maxInFlight bounds concurrent requests on one channel.
//
// The bound exists because each in-flight request holds a pending entry and a
// goroutine waiting on it. A caller that opens thousands of requests against one
// Node would otherwise make the Server allocate on the caller's behalf.
const maxInFlight = 64

// ErrChannelClosed reports that the connection is gone.
var ErrChannelClosed = errors.New("channel is closed")

// ErrChannelBusy reports that the channel already carries the maximum number of
// requests in flight.
var ErrChannelBusy = errors.New("channel has too many requests in flight")

// channel is one live Node connection.
//
// It implements Channel so the registry can route to it, and it carries the frame
// plumbing so a request can be forwarded over it. It holds no scope table and no
// permission table: it moves frames and nothing else, because the Node is the only
// authority for permissions.
//
// It holds no node token. The token arrives as a field of the request being
// forwarded, is written into one frame and is released with that frame. There is
// deliberately no field here that could hold it, so a later change cannot start
// storing it by accident.
type channel struct {
	nodeID string
	conn   *websocket.Conn
	logger *slog.Logger

	writeMutex sync.Mutex
	closed     atomic.Bool
	closeOnce  sync.Once
	done       chan struct{}

	pendingMutex sync.Mutex
	pending      map[string]chan protocol.Response
}

// newChannel builds a channel over an upgraded connection.
func newChannel(nodeID string, conn *websocket.Conn, logger *slog.Logger) *channel {
	return &channel{
		nodeID:  nodeID,
		conn:    conn,
		logger:  logger,
		done:    make(chan struct{}),
		pending: make(map[string]chan protocol.Response),
	}
}

// NodeID returns the identity the Node reported in hello.
func (c *channel) NodeID() string {
	return c.nodeID
}

// Close releases the connection.
//
// It is safe to call more than once, because a replaced connection is closed by
// the registry and again by the goroutine that owns it. The done channel is closed
// first so a forward waiting on it returns immediately instead of waiting for the
// socket to finish closing.
func (c *channel) Close() error {
	var err error
	c.closeOnce.Do(func() {
		c.closed.Store(true)
		close(c.done)
		err = c.conn.Close()
	})
	return err
}

// writeFrame sends one frame under the write mutex.
//
// The mutex is required because a websocket connection permits one writer at a
// time. Two goroutines writing concurrently interleave their frames, and the peer
// then decodes a message that is half of one frame and half of another.
func (c *channel) writeFrame(frame protocol.Frame) error {
	if c.closed.Load() {
		return ErrChannelClosed
	}

	payload, err := json.Marshal(frame)
	if err != nil {
		return fmt.Errorf("encode frame: %w", err)
	}

	c.writeMutex.Lock()
	defer c.writeMutex.Unlock()

	if err := c.conn.SetWriteDeadline(time.Now().Add(writeTimeout)); err != nil {
		return fmt.Errorf("set write deadline: %w", err)
	}
	if err := c.conn.WriteMessage(websocket.TextMessage, payload); err != nil {
		return fmt.Errorf("write frame: %w", err)
	}
	return nil
}

// Forward sends one request to the Node and waits for its answer.
//
// The correlation id is generated here rather than taken from the caller, because
// the caller's request id is a correlation value for its own logs and the wire
// needs one that cannot collide with another caller's. Keeping them separate means
// a caller cannot choose a wire id that matches a request already in flight.
//
// The node token is written into the frame and then released with it. It is never
// copied into a field of this struct, so a retry re-reads it from the caller
// instead of replaying a stored copy.
func (c *channel) Forward(ctx context.Context, nodeID string, request protocol.Request) (protocol.Response, error) {
	if nodeID != c.nodeID {
		return protocol.Response{}, ErrNodeOffline
	}
	if c.closed.Load() {
		return protocol.Response{}, ErrChannelClosed
	}

	requestID, err := newCorrelationID()
	if err != nil {
		return protocol.Response{}, err
	}

	payload, err := json.Marshal(request)
	if err != nil {
		return protocol.Response{}, fmt.Errorf("encode request: %w", err)
	}

	waiter, err := c.addPending(requestID)
	if err != nil {
		return protocol.Response{}, err
	}
	defer c.removePending(requestID)

	frame := protocol.Frame{Type: protocol.FrameRequest, RequestID: requestID, Payload: payload}
	if err := c.writeFrame(frame); err != nil {
		return protocol.Response{}, err
	}

	select {
	case response := <-waiter:
		return response, nil
	case <-ctx.Done():
		return protocol.Response{}, ctx.Err()
	case <-c.done:
		return protocol.Response{}, ErrChannelClosed
	}
}

// addPending registers a waiter for one correlation id.
func (c *channel) addPending(requestID string) (chan protocol.Response, error) {
	c.pendingMutex.Lock()
	defer c.pendingMutex.Unlock()

	if len(c.pending) >= maxInFlight {
		return nil, ErrChannelBusy
	}
	waiter := make(chan protocol.Response, 1)
	c.pending[requestID] = waiter
	return waiter, nil
}

// removePending drops a waiter, whether it was answered or abandoned.
func (c *channel) removePending(requestID string) {
	c.pendingMutex.Lock()
	defer c.pendingMutex.Unlock()
	delete(c.pending, requestID)
}

// deliver hands a response to the waiter registered for its correlation id.
//
// An unknown id is dropped rather than treated as an error, because a response can
// arrive after its waiter gave up on a timeout. Reporting that as a protocol
// violation would close a healthy channel over a request the caller already
// abandoned.
func (c *channel) deliver(requestID string, response protocol.Response) {
	c.pendingMutex.Lock()
	waiter, present := c.pending[requestID]
	c.pendingMutex.Unlock()

	if !present {
		c.logger.Warn("dropping a response with no waiting request", "node_id", c.nodeID, "request_id", requestID)
		return
	}

	select {
	case waiter <- response:
	default:
		c.logger.Warn("dropping a duplicate response", "node_id", c.nodeID, "request_id", requestID)
	}
}

// readLoop reads frames until the connection fails.
//
// It owns the read side for the whole life of the connection, because a websocket
// permits one reader at a time. A response is routed to its waiter; a heartbeat is
// answered so the Node learns the link is alive in both directions; anything else
// is a protocol violation and closes the channel.
func (c *channel) readLoop() {
	defer func() {
		if err := c.Close(); err != nil {
			c.logger.Debug("closing a channel reported an error", "node_id", c.nodeID, "error", err)
		}
	}()

	for {
		_, data, err := c.conn.ReadMessage()
		if err != nil {
			if !c.closed.Load() {
				c.logger.Info("channel read ended", "node_id", c.nodeID, "error", err)
			}
			return
		}
		if len(data) > MaxChannelMessageBytes {
			c.logger.Warn("refusing an oversized channel message", "node_id", c.nodeID, "bytes", len(data))
			return
		}

		var frame protocol.Frame
		if err := json.Unmarshal(data, &frame); err != nil {
			c.logger.Warn("refusing a malformed channel frame", "node_id", c.nodeID, "error", err)
			return
		}
		if !c.handleFrame(frame) {
			return
		}
	}
}

// handleFrame acts on one frame and reports whether the loop continues.
func (c *channel) handleFrame(frame protocol.Frame) bool {
	switch frame.Type {
	case protocol.FrameResponse:
		var response protocol.Response
		if err := json.Unmarshal(frame.Payload, &response); err != nil {
			c.logger.Warn("refusing a malformed response payload", "node_id", c.nodeID, "request_id", frame.RequestID, "error", err)
			return true
		}
		c.deliver(frame.RequestID, response)
		return true

	case protocol.FrameHeartbeat:
		if err := c.writeFrame(protocol.Frame{Type: protocol.FrameHeartbeat}); err != nil {
			c.logger.Info("answering a heartbeat failed", "node_id", c.nodeID, "error", err)
			return false
		}
		return true

	case protocol.FrameError:
		c.logger.Warn("the node reported an error", "node_id", c.nodeID, "request_id", frame.RequestID)
		return true

	case protocol.FrameHello, protocol.FrameHelloConfirm:
		c.logger.Warn("refusing a second handshake on an established channel", "node_id", c.nodeID, "type", string(frame.Type))
		return false

	case protocol.FrameRequest:
		c.logger.Warn("refusing a request sent to the server", "node_id", c.nodeID)
		return false

	default:
		c.logger.Warn("refusing an unknown frame type", "node_id", c.nodeID, "type", string(frame.Type))
		return false
	}
}

// acceptChannel performs the handshake and starts serving frames.
//
// The check order is fixed and each step is a refusal:
//
//  1. The first frame must be hello. A peer that opens with anything else is not
//     speaking this protocol, and guessing what it meant would be inventing a
//     handshake.
//  2. The hello must carry a version, a node id and a tunnel token. The token is
//     checked for presence before it is compared, because an empty configured
//     token compared against an empty presented token would match.
//  3. The tunnel token must match. The comparison is constant time, so a wrong
//     token cannot be recovered byte by byte from the response time.
//  4. The node id must be well formed, which the registry enforces when it
//     registers the connection.
//
// A refusal is reported as one generic error frame. The reason is logged with the
// node id and never sent, because a caller probing the channel learns only that it
// was refused, not which check refused it.
func (l *Listener) acceptChannel(conn *websocket.Conn) {
	logger := l.logger

	if err := conn.SetReadDeadline(time.Now().Add(handshakeTimeout)); err != nil {
		logger.Warn("setting the handshake deadline failed", "error", err)
		_ = conn.Close()
		return
	}

	hello, err := readHello(conn)
	if err != nil {
		logger.Warn("refusing a channel that did not open with hello", "error", err)
		refuseChannel(conn, protocol.CodeInvalidArgument)
		return
	}

	if err := hello.Validate(); err != nil {
		logger.Warn("refusing an incomplete hello", "error", err)
		refuseChannel(conn, protocol.CodeInvalidArgument)
		return
	}

	if !l.config.TunnelToken.Equal(security.Secret(hello.TunnelToken)) {
		logger.Warn("refusing a hello with a wrong tunnel token", "node_id", hello.NodeID)
		refuseChannel(conn, protocol.CodeUnauthenticated)
		return
	}

	if err := conn.SetReadDeadline(time.Time{}); err != nil {
		logger.Warn("clearing the handshake deadline failed", "error", err)
		_ = conn.Close()
		return
	}

	live := newChannel(hello.NodeID, conn, logger)
	registration, replaced, err := l.registry.Register(live)
	if err != nil {
		logger.Warn("refusing a hello with an unusable node id", "node_id", hello.NodeID, "error", err)
		refuseChannel(conn, protocol.CodeInvalidArgument)
		return
	}

	if replaced != nil {
		logger.Info("replacing a live connection for the same node", "node_id", hello.NodeID)
		if err := replaced.Close(); err != nil {
			logger.Debug("closing the replaced connection reported an error", "node_id", hello.NodeID, "error", err)
		}
	}

	generation := l.generations.Add(1)
	confirm := protocol.HelloConfirm{Version: protocol.Version, Generation: generation}
	payload, err := json.Marshal(confirm)
	if err != nil {
		logger.Error("encoding hello_confirm failed", "node_id", hello.NodeID, "error", err)
		l.registry.Unregister(registration)
		_ = live.Close()
		return
	}

	if err := live.writeFrame(protocol.Frame{Type: protocol.FrameHelloConfirm, Payload: payload}); err != nil {
		logger.Warn("writing hello_confirm failed", "node_id", hello.NodeID, "error", err)
		l.registry.Unregister(registration)
		_ = live.Close()
		return
	}

	logger.Info("channel established",
		"node_id", hello.NodeID,
		"generation", generation,
		"operations", hello.Operations,
		"scopes", hello.Scopes,
	)

	live.readLoop()

	if l.registry.Unregister(registration) {
		logger.Info("channel closed", "node_id", hello.NodeID)
	}
}

// readHello reads the first frame and decodes it as a hello.
func readHello(conn *websocket.Conn) (protocol.Hello, error) {
	_, data, err := conn.ReadMessage()
	if err != nil {
		return protocol.Hello{}, fmt.Errorf("read hello: %w", err)
	}
	if len(data) > MaxChannelMessageBytes {
		return protocol.Hello{}, fmt.Errorf("hello is %d bytes, limit is %d", len(data), MaxChannelMessageBytes)
	}

	var frame protocol.Frame
	if err := json.Unmarshal(data, &frame); err != nil {
		return protocol.Hello{}, fmt.Errorf("decode hello frame: %w", err)
	}
	if frame.Type != protocol.FrameHello {
		return protocol.Hello{}, fmt.Errorf("first frame is %q, want %q", string(frame.Type), string(protocol.FrameHello))
	}

	var hello protocol.Hello
	if err := json.Unmarshal(frame.Payload, &hello); err != nil {
		return protocol.Hello{}, fmt.Errorf("decode hello payload: %w", err)
	}
	return hello, nil
}

// refuseChannel reports a refusal and closes the connection.
//
// The frame carries a code and no detail, because the detail is the part that
// would tell a prober which check refused it.
func refuseChannel(conn *websocket.Conn, code protocol.Code) {
	payload, err := json.Marshal(protocol.Response{Code: code})
	if err != nil {
		_ = conn.Close()
		return
	}
	frame := protocol.Frame{Type: protocol.FrameError, Payload: payload}
	encoded, err := json.Marshal(frame)
	if err != nil {
		_ = conn.Close()
		return
	}

	_ = conn.SetWriteDeadline(time.Now().Add(writeTimeout))
	_ = conn.WriteMessage(websocket.TextMessage, encoded)
	_ = conn.Close()
}

// newCorrelationID returns a random identifier for one wire request.
func newCorrelationID() (string, error) {
	buffer := make([]byte, 16)
	if _, err := rand.Read(buffer); err != nil {
		return "", fmt.Errorf("generate correlation id: %w", err)
	}
	return "wire_" + hex.EncodeToString(buffer), nil
}

// serveChannel upgrades one HTTP request into a channel.
func (l *Listener) serveChannel(writer http.ResponseWriter, request *http.Request) {
	if request.Method != http.MethodGet {
		writer.Header().Set("Allow", http.MethodGet)
		http.Error(writer, "the channel is a websocket upgrade", http.StatusMethodNotAllowed)
		return
	}

	conn, err := l.upgrader.Upgrade(writer, request, nil)
	if err != nil {
		l.logger.Warn("upgrading a channel failed", "error", err)
		return
	}

	l.acceptChannel(conn)
}
