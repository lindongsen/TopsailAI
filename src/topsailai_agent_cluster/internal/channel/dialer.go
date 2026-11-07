package channel

import (
	"context"
	"crypto/tls"
	"errors"
	"fmt"
	"net/http"
	"net/url"
	"strconv"
	"time"

	"github.com/coder/websocket"
	"github.com/coder/websocket/wsjson"
)

// DialEndpoint establishes a Server-initiated connection to one Endpoint. It is
// the mirror of EndpointClient.Dial: the Server dials, the Endpoint accepts, and
// the Server still allocates the connection generation so fencing stays
// identical in both directions.
//
// The generation is proposed with Peek and committed with Acquire only after the
// handshake succeeds, so a failed dial never fences a healthy peer.
func (s *Server) DialEndpoint(ctx context.Context, endpointID, address string, tlsConfig *tls.Config) (*Peer, error) {
	if endpointID == "" {
		return nil, errors.New("endpoint identity is required")
	}
	if address == "" {
		return nil, errors.New("endpoint channel address is required")
	}
	u, err := url.Parse(address)
	if err != nil {
		return nil, err
	}
	if u.Scheme != "ws" && u.Scheme != "wss" {
		return nil, errors.New("endpoint channel address must use ws or wss")
	}
	conn, _, err := websocket.Dial(ctx, address, &websocket.DialOptions{HTTPClient: &http.Client{Transport: &http.Transport{TLSClientConfig: tlsConfig}}})
	if err != nil {
		return nil, err
	}
	conn.SetReadLimit(channelReadLimit)
	proposed := s.Fence.Peek(endpointID)
	hello := Frame{Type: FrameHello, ProtocolVersion: ProtocolVersion, EndpointID: endpointID, ConnectionGeneration: strconv.FormatInt(proposed, 10), Initiator: InitiatorServer}
	if err := wsjson.Write(ctx, conn, hello); err != nil {
		_ = conn.Close(websocket.StatusInternalError, "hello failed")
		return nil, err
	}
	var ack Frame
	if err := wsjson.Read(ctx, conn, &ack); err != nil {
		_ = conn.Close(websocket.StatusInternalError, "hello ack failed")
		return nil, err
	}
	if ack.Type == FrameHelloRejected {
		_ = conn.Close(websocket.StatusPolicyViolation, ack.Reason)
		return nil, fmt.Errorf("endpoint hello rejected: %s", ack.Reason)
	}
	if ack.Type != FrameHelloAck || ack.ConnectionGeneration == "" {
		_ = conn.Close(websocket.StatusPolicyViolation, "invalid hello ack")
		return nil, errors.New("invalid endpoint hello acknowledgement")
	}
	// The Endpoint echoes the generation it adopted. A different value means the
	// two sides disagree about authority, so the connection is unusable.
	if ack.ConnectionGeneration != strconv.FormatInt(proposed, 10) {
		_ = conn.Close(websocket.StatusPolicyViolation, "generation mismatch")
		return nil, errors.New("endpoint adopted a different connection generation")
	}
	generation := s.Fence.Acquire(endpointID)
	// Acquire decides authority, so a concurrent connection can win the race
	// between Peek and Acquire. The Endpoint adopted the proposed value, so a
	// different committed value means the two sides disagree and the connection
	// must not be used.
	if generation != proposed {
		_ = conn.Close(websocket.StatusPolicyViolation, "generation superseded")
		return nil, errors.New("connection generation was superseded during handshake")
	}
	peer := &Peer{EndpointID: endpointID, InstanceID: ack.InstanceID, Hostname: ack.Hostname, ConnectionGeneration: generation, Conn: conn, LastSeen: time.Now(), Initiator: InitiatorServer}
	s.Mu.Lock()
	if old := s.Active[endpointID]; old != nil {
		_ = old.Conn.CloseNow()
	}
	s.Active[endpointID] = peer
	s.Mu.Unlock()
	go s.readLoop(context.Background(), peer)
	return peer, nil
}
