package channel

import (
	"context"
	"crypto/tls"
	"errors"
	"fmt"
	"net/http"
	"net/url"
	"strconv"

	"github.com/coder/websocket"
	"github.com/coder/websocket/wsjson"
)

// DialEndpoint establishes a Server-initiated connection to one Endpoint. It is
// the mirror of EndpointClient.Dial: the Server dials, the Endpoint accepts, and
// the Server still allocates the connection generation so fencing stays
// identical in both directions.
//
// The generation is assigned by installPeer, under the same lock that installs
// the peer. The Endpoint attaches only after the hello_confirm frame carries that
// generation, so both sides always agree on which link is authoritative and the
// newest install wins. A failed dial therefore never fences a healthy peer,
// because nothing is installed until the handshake has succeeded.
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
	hello := Frame{Type: FrameHello, ProtocolVersion: ProtocolVersion, EndpointID: endpointID, Initiator: InitiatorServer}
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
	if ack.Type != FrameHelloAck {
		_ = conn.Close(websocket.StatusPolicyViolation, "invalid hello ack")
		return nil, errors.New("invalid endpoint hello acknowledgement")
	}
	// The Endpoint has validated identity and initiator but has not attached yet.
	// Installing here assigns the generation, and the confirm frame tells the
	// Endpoint which generation to adopt.
	peer := s.installPeer(endpointID, ack.InstanceID, ack.Hostname, InitiatorServer, conn)
	confirm := Frame{Type: FrameHelloConfirm, ProtocolVersion: ProtocolVersion, ConnectionGeneration: strconv.FormatInt(peer.ConnectionGeneration, 10), EndpointID: endpointID}
	if err := wsjson.Write(ctx, conn, confirm); err != nil {
		s.remove(peer)
		_ = conn.Close(websocket.StatusInternalError, "hello confirm failed")
		return nil, err
	}
	// Wait for the Endpoint to confirm it adopted this generation. Reporting
	// success on install alone would let a dial that the Endpoint discarded look
	// established, and the caller would then treat a dead link as the winner.
	var attached Frame
	if err := wsjson.Read(ctx, conn, &attached); err != nil {
		s.remove(peer)
		_ = conn.Close(websocket.StatusInternalError, "hello attached failed")
		return nil, err
	}
	if attached.Type != FrameHelloAttached || attached.EndpointID != endpointID || attached.ConnectionGeneration != confirm.ConnectionGeneration {
		s.remove(peer)
		_ = conn.Close(websocket.StatusPolicyViolation, "invalid hello attached")
		return nil, errors.New("endpoint did not confirm the assigned connection generation")
	}
	go s.readLoop(context.Background(), peer)
	return peer, nil
}
