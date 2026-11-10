package node

import (
	"encoding/json"
	"errors"
	"fmt"
	"time"

	"github.com/gorilla/websocket"

	"topsailai_connector/internal/protocol"
)

// socketWriteTimeout bounds one frame write on the channel.
//
// A write to a peer that has stopped reading blocks once the socket buffer fills.
// Without a deadline that block is permanent, and the Node then looks alive while
// it is unable to answer anything.
const socketWriteTimeout = 10 * time.Second

// SocketFrameConn carries frames over a websocket connection.
//
// It adapts the transport to FrameConn, so the frame loop keeps deciding what a
// frame means while the connection decides how a frame travels. One message is one
// frame, which is what the Server writes, so the two sides agree on boundaries
// without a length prefix.
type SocketFrameConn struct {
	conn *websocket.Conn
}

// NewSocketFrameConn adapts a websocket connection to FrameConn.
//
// A nil connection is refused here rather than at the first read, because a
// connection that fails on use is a failure reported at the wrong place: the
// caller believes it has a channel and learns otherwise only when a request is
// already in flight.
func NewSocketFrameConn(conn *websocket.Conn) (*SocketFrameConn, error) {
	if conn == nil {
		return nil, errors.New("websocket connection is nil")
	}
	return &SocketFrameConn{conn: conn}, nil
}

// ReadFrame reads the next frame.
//
// The payload is bounded before it is handed on, so a peer cannot make the Node
// allocate an unbounded buffer by declaring a large payload.
func (c *SocketFrameConn) ReadFrame() (protocol.Frame, error) {
	if c == nil || c.conn == nil {
		return protocol.Frame{}, errors.New("frame connection is not readable")
	}

	_, data, err := c.conn.ReadMessage()
	if err != nil {
		return protocol.Frame{}, err
	}
	if len(data) > MaxFramePayloadBytes {
		return protocol.Frame{}, fmt.Errorf("frame is %d bytes, limit is %d", len(data), MaxFramePayloadBytes)
	}

	var frame protocol.Frame
	if err := json.Unmarshal(data, &frame); err != nil {
		return protocol.Frame{}, fmt.Errorf("decode frame: %w", err)
	}
	return frame, nil
}

// WriteFrame sends one frame.
//
// The write deadline is set per frame rather than once, because a deadline set
// once expires and then every later write fails immediately with a timeout that
// has nothing to do with the peer.
func (c *SocketFrameConn) WriteFrame(frame protocol.Frame) error {
	if c == nil || c.conn == nil {
		return errors.New("frame connection is not writable")
	}

	encoded, err := json.Marshal(frame)
	if err != nil {
		return fmt.Errorf("encode frame: %w", err)
	}
	if err := c.conn.SetWriteDeadline(time.Now().Add(socketWriteTimeout)); err != nil {
		return fmt.Errorf("set write deadline: %w", err)
	}
	return c.conn.WriteMessage(websocket.TextMessage, encoded)
}

// Close releases the connection.
func (c *SocketFrameConn) Close() error {
	if c == nil || c.conn == nil {
		return nil
	}
	return c.conn.Close()
}
