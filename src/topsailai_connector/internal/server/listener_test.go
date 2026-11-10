package server

import (
	"context"
	"encoding/json"
	"errors"
	"log/slog"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"

	"github.com/gorilla/websocket"

	"topsailai_connector/internal/protocol"
	"topsailai_connector/internal/security"
)

// listenerFixture is a listener wired to a real registry and a real handler.
type listenerFixture struct {
	listener *Listener
	registry *Registry
	server   *httptest.Server
}

// newListenerFixture builds a listener served by an httptest server.
//
// The surfaces are driven over a real socket rather than through the handler
// directly, because the channel is a websocket upgrade and an upgrade cannot be
// exercised without a connection to upgrade.
func newListenerFixture(t *testing.T) *listenerFixture {
	t.Helper()

	config := Config{
		Listen:         "127.0.0.1:0",
		TunnelToken:    security.Secret("tunnel-token-value-1234"),
		ClientToken:    security.Secret("client-token-value-1234"),
		RequestTimeout: 5 * time.Second,
	}

	registry := NewRegistry()
	listener, err := NewListener(config, registry, slog.New(slog.DiscardHandler))
	if err != nil {
		t.Fatalf("build listener: %v", err)
	}

	server := httptest.NewServer(listener.Handler())
	t.Cleanup(func() {
		server.Close()
		_ = registry.CloseAll()
	})

	return &listenerFixture{listener: listener, registry: registry, server: server}
}

// dial opens a websocket connection to the channel.
func (f *listenerFixture) dial(t *testing.T) *websocket.Conn {
	t.Helper()

	url := "ws" + strings.TrimPrefix(f.server.URL, "http") + ChannelPath
	conn, _, err := websocket.DefaultDialer.Dial(url, nil)
	if err != nil {
		t.Fatalf("dial the channel: %v", err)
	}
	t.Cleanup(func() {
		_ = conn.Close()
	})
	return conn
}

// sendHello writes one hello frame.
func sendHello(t *testing.T, conn *websocket.Conn, hello protocol.Hello) {
	t.Helper()

	payload, err := json.Marshal(hello)
	if err != nil {
		t.Fatalf("encode hello: %v", err)
	}
	frame := protocol.Frame{Type: protocol.FrameHello, Payload: payload}
	encoded, err := json.Marshal(frame)
	if err != nil {
		t.Fatalf("encode hello frame: %v", err)
	}
	if err := conn.WriteMessage(websocket.TextMessage, encoded); err != nil {
		t.Fatalf("write hello: %v", err)
	}
}

// readFrame reads one frame with a deadline.
func readFrame(t *testing.T, conn *websocket.Conn) protocol.Frame {
	t.Helper()

	if err := conn.SetReadDeadline(time.Now().Add(5 * time.Second)); err != nil {
		t.Fatalf("set read deadline: %v", err)
	}
	_, data, err := conn.ReadMessage()
	if err != nil {
		t.Fatalf("read frame: %v", err)
	}

	var frame protocol.Frame
	if err := json.Unmarshal(data, &frame); err != nil {
		t.Fatalf("decode frame: %v", err)
	}
	return frame
}

// validHello returns a hello carrying the fixture's tunnel token.
func validHello(nodeID string) protocol.Hello {
	return protocol.Hello{
		Version:     protocol.Version,
		NodeID:      nodeID,
		TunnelToken: []byte("tunnel-token-value-1234"),
		Operations:  []string{"file.read"},
		Scopes:      []string{"project"},
	}
}

// TestChannelAcceptsValidHello checks that a hello carrying the configured tunnel
// token is accepted, registered and answered with a confirmation.
func TestChannelAcceptsValidHello(t *testing.T) {
	fixture := newListenerFixture(t)
	conn := fixture.dial(t)

	sendHello(t, conn, validHello("node_0123456789abcdef0123456789abcdef"))

	frame := readFrame(t, conn)
	if frame.Type != protocol.FrameHelloConfirm {
		t.Fatalf("frame type = %q, want %q", string(frame.Type), string(protocol.FrameHelloConfirm))
	}

	var confirm protocol.HelloConfirm
	if err := json.Unmarshal(frame.Payload, &confirm); err != nil {
		t.Fatalf("decode hello confirm: %v", err)
	}
	if confirm.Version != protocol.Version {
		t.Fatalf("version = %q, want %q", confirm.Version, protocol.Version)
	}
	if confirm.Generation == 0 {
		t.Fatal("generation is zero, want a monotonic counter")
	}

	if fixture.registry.Len() != 1 {
		t.Fatalf("registry length = %d, want 1", fixture.registry.Len())
	}
}

// TestChannelRefusesWrongTunnelToken checks that a hello with a wrong tunnel token
// is refused and never registered.
func TestChannelRefusesWrongTunnelToken(t *testing.T) {
	fixture := newListenerFixture(t)
	conn := fixture.dial(t)

	hello := validHello("node_0123456789abcdef0123456789abcdef")
	hello.TunnelToken = []byte("wrong-tunnel-token-1234")
	sendHello(t, conn, hello)

	frame := readFrame(t, conn)
	if frame.Type != protocol.FrameError {
		t.Fatalf("frame type = %q, want %q", string(frame.Type), string(protocol.FrameError))
	}

	var response protocol.Response
	if err := json.Unmarshal(frame.Payload, &response); err != nil {
		t.Fatalf("decode refusal: %v", err)
	}
	if response.Code != protocol.CodeUnauthenticated {
		t.Fatalf("code = %v, want %v", response.Code, protocol.CodeUnauthenticated)
	}
	if fixture.registry.Len() != 0 {
		t.Fatalf("registry length = %d, want 0", fixture.registry.Len())
	}
}

// TestChannelRefusesEmptyTunnelToken checks that a hello with no tunnel token is
// refused before the comparison runs, because an empty configured token compared
// against an empty presented token would match.
func TestChannelRefusesEmptyTunnelToken(t *testing.T) {
	fixture := newListenerFixture(t)
	conn := fixture.dial(t)

	hello := validHello("node_0123456789abcdef0123456789abcdef")
	hello.TunnelToken = nil
	sendHello(t, conn, hello)

	frame := readFrame(t, conn)
	if frame.Type != protocol.FrameError {
		t.Fatalf("frame type = %q, want %q", string(frame.Type), string(protocol.FrameError))
	}
	if fixture.registry.Len() != 0 {
		t.Fatalf("registry length = %d, want 0", fixture.registry.Len())
	}
}

// TestChannelRefusesHelloWithoutNodeID checks that a hello with no node id is
// refused, because the Server has no connection to register it under.
func TestChannelRefusesHelloWithoutNodeID(t *testing.T) {
	fixture := newListenerFixture(t)
	conn := fixture.dial(t)

	hello := validHello("")
	sendHello(t, conn, hello)

	frame := readFrame(t, conn)
	if frame.Type != protocol.FrameError {
		t.Fatalf("frame type = %q, want %q", string(frame.Type), string(protocol.FrameError))
	}
	if fixture.registry.Len() != 0 {
		t.Fatalf("registry length = %d, want 0", fixture.registry.Len())
	}
}

// TestChannelRefusesMalformedNodeID checks that a hello whose node id is not well
// formed is refused, so a typo cannot become a routable identity.
func TestChannelRefusesMalformedNodeID(t *testing.T) {
	fixture := newListenerFixture(t)
	conn := fixture.dial(t)

	sendHello(t, conn, validHello("not-a-node-id"))

	frame := readFrame(t, conn)
	if frame.Type != protocol.FrameError {
		t.Fatalf("frame type = %q, want %q", string(frame.Type), string(protocol.FrameError))
	}
	if fixture.registry.Len() != 0 {
		t.Fatalf("registry length = %d, want 0", fixture.registry.Len())
	}
}

// TestChannelRefusesFirstFrameThatIsNotHello checks that a connection opening with
// anything other than hello is refused, because guessing what it meant would be
// inventing a handshake.
func TestChannelRefusesFirstFrameThatIsNotHello(t *testing.T) {
	fixture := newListenerFixture(t)
	conn := fixture.dial(t)

	frame := protocol.Frame{Type: protocol.FrameHeartbeat}
	encoded, err := json.Marshal(frame)
	if err != nil {
		t.Fatalf("encode frame: %v", err)
	}
	if err := conn.WriteMessage(websocket.TextMessage, encoded); err != nil {
		t.Fatalf("write frame: %v", err)
	}

	answer := readFrame(t, conn)
	if answer.Type != protocol.FrameError {
		t.Fatalf("frame type = %q, want %q", string(answer.Type), string(protocol.FrameError))
	}
	if fixture.registry.Len() != 0 {
		t.Fatalf("registry length = %d, want 0", fixture.registry.Len())
	}
}

// TestChannelReplacesLiveConnection checks that a second connection for the same
// node id replaces the first, because one connection serves one Node and two live
// connections would be two answers to one request.
func TestChannelReplacesLiveConnection(t *testing.T) {
	fixture := newListenerFixture(t)
	nodeID := "node_0123456789abcdef0123456789abcdef"

	first := fixture.dial(t)
	sendHello(t, first, validHello(nodeID))
	if frame := readFrame(t, first); frame.Type != protocol.FrameHelloConfirm {
		t.Fatalf("first frame type = %q, want %q", string(frame.Type), string(protocol.FrameHelloConfirm))
	}

	second := fixture.dial(t)
	sendHello(t, second, validHello(nodeID))
	if frame := readFrame(t, second); frame.Type != protocol.FrameHelloConfirm {
		t.Fatalf("second frame type = %q, want %q", string(frame.Type), string(protocol.FrameHelloConfirm))
	}

	if fixture.registry.Len() != 1 {
		t.Fatalf("registry length = %d, want 1", fixture.registry.Len())
	}

	// The replaced connection is closed, so a read on it fails rather than
	// returning a frame from a connection the Node has abandoned.
	if err := first.SetReadDeadline(time.Now().Add(5 * time.Second)); err != nil {
		t.Fatalf("set read deadline: %v", err)
	}
	if _, _, err := first.ReadMessage(); err == nil {
		t.Fatal("expected the replaced connection to be closed")
	}
}

// TestChannelAnswersHeartbeat checks that a heartbeat is answered, so the Node
// learns the link is alive in both directions rather than only that its own write
// succeeded.
func TestChannelAnswersHeartbeat(t *testing.T) {
	fixture := newListenerFixture(t)
	conn := fixture.dial(t)

	sendHello(t, conn, validHello("node_0123456789abcdef0123456789abcdef"))
	if frame := readFrame(t, conn); frame.Type != protocol.FrameHelloConfirm {
		t.Fatalf("frame type = %q, want %q", string(frame.Type), string(protocol.FrameHelloConfirm))
	}

	frame := protocol.Frame{Type: protocol.FrameHeartbeat}
	encoded, err := json.Marshal(frame)
	if err != nil {
		t.Fatalf("encode heartbeat: %v", err)
	}
	if err := conn.WriteMessage(websocket.TextMessage, encoded); err != nil {
		t.Fatalf("write heartbeat: %v", err)
	}

	if answer := readFrame(t, conn); answer.Type != protocol.FrameHeartbeat {
		t.Fatalf("frame type = %q, want %q", string(answer.Type), string(protocol.FrameHeartbeat))
	}
}

// TestChannelRefusesSecondHandshake checks that a second hello on an established
// channel closes it, because a renegotiation this version does not support would
// leave the Server guessing which hello is authoritative.
func TestChannelRefusesSecondHandshake(t *testing.T) {
	fixture := newListenerFixture(t)
	conn := fixture.dial(t)
	nodeID := "node_0123456789abcdef0123456789abcdef"

	sendHello(t, conn, validHello(nodeID))
	if frame := readFrame(t, conn); frame.Type != protocol.FrameHelloConfirm {
		t.Fatalf("frame type = %q, want %q", string(frame.Type), string(protocol.FrameHelloConfirm))
	}

	sendHello(t, conn, validHello(nodeID))

	if err := conn.SetReadDeadline(time.Now().Add(5 * time.Second)); err != nil {
		t.Fatalf("set read deadline: %v", err)
	}
	if _, _, err := conn.ReadMessage(); err == nil {
		t.Fatal("expected the channel to be closed after a second handshake")
	}
}

// TestChannelRefusesRequestSentToServer checks that a request frame arriving at the
// Server closes the channel, because the Node is the side that answers.
func TestChannelRefusesRequestSentToServer(t *testing.T) {
	fixture := newListenerFixture(t)
	conn := fixture.dial(t)

	sendHello(t, conn, validHello("node_0123456789abcdef0123456789abcdef"))
	if frame := readFrame(t, conn); frame.Type != protocol.FrameHelloConfirm {
		t.Fatalf("frame type = %q, want %q", string(frame.Type), string(protocol.FrameHelloConfirm))
	}

	frame := protocol.Frame{Type: protocol.FrameRequest, RequestID: "wire-1"}
	encoded, err := json.Marshal(frame)
	if err != nil {
		t.Fatalf("encode request: %v", err)
	}
	if err := conn.WriteMessage(websocket.TextMessage, encoded); err != nil {
		t.Fatalf("write request: %v", err)
	}

	if err := conn.SetReadDeadline(time.Now().Add(5 * time.Second)); err != nil {
		t.Fatalf("set read deadline: %v", err)
	}
	if _, _, err := conn.ReadMessage(); err == nil {
		t.Fatal("expected the channel to be closed after a request frame")
	}
}

// TestChannelRefusesUnknownFrameType checks that an unknown frame type closes the
// channel, because a peer speaking a newer protocol must not be silently ignored.
func TestChannelRefusesUnknownFrameType(t *testing.T) {
	fixture := newListenerFixture(t)
	conn := fixture.dial(t)

	sendHello(t, conn, validHello("node_0123456789abcdef0123456789abcdef"))
	if frame := readFrame(t, conn); frame.Type != protocol.FrameHelloConfirm {
		t.Fatalf("frame type = %q, want %q", string(frame.Type), string(protocol.FrameHelloConfirm))
	}

	frame := protocol.Frame{Type: protocol.FrameType("nonsense")}
	encoded, err := json.Marshal(frame)
	if err != nil {
		t.Fatalf("encode frame: %v", err)
	}
	if err := conn.WriteMessage(websocket.TextMessage, encoded); err != nil {
		t.Fatalf("write frame: %v", err)
	}

	if err := conn.SetReadDeadline(time.Now().Add(5 * time.Second)); err != nil {
		t.Fatalf("set read deadline: %v", err)
	}
	if _, _, err := conn.ReadMessage(); err == nil {
		t.Fatal("expected the channel to be closed after an unknown frame type")
	}
}

// TestChannelRefusesNonGetUpgrade checks that a plain GET without an upgrade is
// refused rather than treated as a channel.
func TestChannelRefusesNonGetUpgrade(t *testing.T) {
	fixture := newListenerFixture(t)

	response, err := http.Get(fixture.server.URL + ChannelPath)
	if err != nil {
		t.Fatalf("get the channel: %v", err)
	}
	defer func() {
		_ = response.Body.Close()
	}()

	if response.StatusCode != http.StatusBadRequest {
		t.Fatalf("status = %d, want %d", response.StatusCode, http.StatusBadRequest)
	}
}

// TestChannelRefusesPost checks that a POST to the channel path is refused with a
// method error, because the channel is an upgrade and not a request surface.
func TestChannelRefusesPost(t *testing.T) {
	fixture := newListenerFixture(t)

	response, err := http.Post(fixture.server.URL+ChannelPath, "text/plain", strings.NewReader(""))
	if err != nil {
		t.Fatalf("post the channel: %v", err)
	}
	defer func() {
		_ = response.Body.Close()
	}()

	if response.StatusCode != http.StatusMethodNotAllowed {
		t.Fatalf("status = %d, want %d", response.StatusCode, http.StatusMethodNotAllowed)
	}
}

// TestListenerForwardRefusesOfflineNode checks that forwarding to a node with no
// live connection reports node_offline rather than blocking.
func TestListenerForwardRefusesOfflineNode(t *testing.T) {
	fixture := newListenerFixture(t)

	_, err := fixture.listener.Forward(context.Background(), "node_0123456789abcdef0123456789abcdef", protocol.Request{})
	if !errors.Is(err, ErrNodeOffline) {
		t.Fatalf("error = %v, want %v", err, ErrNodeOffline)
	}
}

// TestListenerForwardRelaysResponse checks that a forwarded request reaches the
// Node over the channel and its answer comes back unchanged.
func TestListenerForwardRelaysResponse(t *testing.T) {
	fixture := newListenerFixture(t)
	nodeID := "node_0123456789abcdef0123456789abcdef"
	conn := fixture.dial(t)

	sendHello(t, conn, validHello(nodeID))
	if frame := readFrame(t, conn); frame.Type != protocol.FrameHelloConfirm {
		t.Fatalf("frame type = %q, want %q", string(frame.Type), string(protocol.FrameHelloConfirm))
	}

	// The Node side answers the forwarded request from a goroutine, so the
	// forward call and the answer are concurrent, which is what a real channel
	// does.
	answered := make(chan struct{})
	go func() {
		defer close(answered)
		frame := readFrame(t, conn)

		var request protocol.Request
		if err := json.Unmarshal(frame.Payload, &request); err != nil {
			t.Errorf("decode forwarded request: %v", err)
			return
		}
		if request.Operation != protocol.OperationFileRead {
			t.Errorf("operation = %q, want %q", string(request.Operation), string(protocol.OperationFileRead))
		}
		if request.NodeToken != security.Secret("node-token-value-1234") {
			t.Errorf("node token was not relayed unchanged")
		}

		response := protocol.Response{Code: protocol.CodeSuccess, Data: []byte(`{"content":"aGk="}`)}
		payload, err := json.Marshal(response)
		if err != nil {
			t.Errorf("encode response: %v", err)
			return
		}
		answer := protocol.Frame{Type: protocol.FrameResponse, RequestID: frame.RequestID, Payload: payload}
		encoded, err := json.Marshal(answer)
		if err != nil {
			t.Errorf("encode response frame: %v", err)
			return
		}
		if err := conn.WriteMessage(websocket.TextMessage, encoded); err != nil {
			t.Errorf("write response: %v", err)
		}
	}()

	request := protocol.Request{
		NodeID:    nodeID,
		NodeToken: security.Secret("node-token-value-1234"),
		Operation: protocol.OperationFileRead,
		Scope:     security.Scope("project"),
		Path:      "a.txt",
	}

	response, err := fixture.listener.Forward(context.Background(), nodeID, request)
	if err != nil {
		t.Fatalf("forward: %v", err)
	}
	if response.Code != protocol.CodeSuccess {
		t.Fatalf("code = %v, want %v", response.Code, protocol.CodeSuccess)
	}
	if string(response.Data) != `{"content":"aGk="}` {
		t.Fatalf("data = %q, want the node answer unchanged", response.Data)
	}

	<-answered
}

// TestListenerForwardRefusesWrongNodeID checks that a forward addressed to a
// different node id than the connection reports is refused, so a request cannot be
// delivered to a Node it was not addressed to.
func TestListenerForwardRefusesWrongNodeID(t *testing.T) {
	fixture := newListenerFixture(t)
	nodeID := "node_0123456789abcdef0123456789abcdef"
	conn := fixture.dial(t)

	sendHello(t, conn, validHello(nodeID))
	if frame := readFrame(t, conn); frame.Type != protocol.FrameHelloConfirm {
		t.Fatalf("frame type = %q, want %q", string(frame.Type), string(protocol.FrameHelloConfirm))
	}

	_, err := fixture.listener.Forward(context.Background(), "node_ffffffffffffffffffffffffffffffff", protocol.Request{})
	if !errors.Is(err, ErrNodeOffline) {
		t.Fatalf("error = %v, want %v", err, ErrNodeOffline)
	}
}

// TestListenerForwardHonoursContext checks that a forward returns when the caller
// gives up, so a Node that never answers does not hold the caller forever.
func TestListenerForwardHonoursContext(t *testing.T) {
	fixture := newListenerFixture(t)
	nodeID := "node_0123456789abcdef0123456789abcdef"
	conn := fixture.dial(t)

	sendHello(t, conn, validHello(nodeID))
	if frame := readFrame(t, conn); frame.Type != protocol.FrameHelloConfirm {
		t.Fatalf("frame type = %q, want %q", string(frame.Type), string(protocol.FrameHelloConfirm))
	}

	ctx, cancel := context.WithTimeout(context.Background(), 100*time.Millisecond)
	defer cancel()

	_, err := fixture.listener.Forward(ctx, nodeID, protocol.Request{NodeID: nodeID})
	if !errors.Is(err, context.DeadlineExceeded) {
		t.Fatalf("error = %v, want %v", err, context.DeadlineExceeded)
	}
}

// TestListenerForwardReturnsWhenChannelCloses checks that a forward waiting on a
// channel returns when the channel closes, rather than waiting for a response that
// will never arrive.
func TestListenerForwardReturnsWhenChannelCloses(t *testing.T) {
	fixture := newListenerFixture(t)
	nodeID := "node_0123456789abcdef0123456789abcdef"
	conn := fixture.dial(t)

	sendHello(t, conn, validHello(nodeID))
	if frame := readFrame(t, conn); frame.Type != protocol.FrameHelloConfirm {
		t.Fatalf("frame type = %q, want %q", string(frame.Type), string(protocol.FrameHelloConfirm))
	}

	go func() {
		time.Sleep(50 * time.Millisecond)
		_ = conn.Close()
	}()

	_, err := fixture.listener.Forward(context.Background(), nodeID, protocol.Request{NodeID: nodeID})
	if err == nil {
		t.Fatal("expected an error when the channel closes mid-request")
	}
}

// TestNewListenerRefusesNilRegistry checks that a listener without a registry is
// refused, because a listener that cannot route has no answer to give.
func TestNewListenerRefusesNilRegistry(t *testing.T) {
	if _, err := NewListener(Config{}, nil, slog.New(slog.DiscardHandler)); err == nil {
		t.Fatal("expected an error for a nil registry")
	}
}

// TestListenerHandlerServesBothSurfaces checks that one handler serves the channel
// path and the operation path, so the two surfaces cannot be mounted separately.
func TestListenerHandlerServesBothSurfaces(t *testing.T) {
	fixture := newListenerFixture(t)

	// The operation path is reachable and refuses a request with no client token,
	// which proves the CLI surface is mounted on the same handler.
	request, err := http.NewRequest(http.MethodPost, fixture.server.URL+OperationPathPrefix+"node_0123456789abcdef0123456789abcdef"+OperationPathSuffix, strings.NewReader("{}"))
	if err != nil {
		t.Fatalf("build request: %v", err)
	}
	request.Header.Set("Content-Type", "application/json")

	response, err := http.DefaultClient.Do(request)
	if err != nil {
		t.Fatalf("post the operation path: %v", err)
	}
	defer func() {
		_ = response.Body.Close()
	}()

	if response.StatusCode != http.StatusUnauthorized {
		t.Fatalf("status = %d, want %d", response.StatusCode, http.StatusUnauthorized)
	}
}

// TestListenerServeRefusesBadAddress checks that a bind failure is reported as a
// startup failure rather than as a Server that appears to be running.
func TestListenerServeRefusesBadAddress(t *testing.T) {
	config := Config{
		Listen:         "127.0.0.1:99999",
		TunnelToken:    security.Secret("tunnel-token-value-1234"),
		ClientToken:    security.Secret("client-token-value-1234"),
		RequestTimeout: time.Second,
	}
	listener, err := NewListener(config, NewRegistry(), slog.New(slog.DiscardHandler))
	if err != nil {
		t.Fatalf("build listener: %v", err)
	}

	if err := listener.Serve(context.Background()); err == nil {
		t.Fatal("expected an error for an unusable address")
	}
}

// TestListenerServeStopsOnContextCancel checks that cancelling the context stops
// the listener and closes the live channels.
func TestListenerServeStopsOnContextCancel(t *testing.T) {
	config := Config{
		Listen:         "127.0.0.1:0",
		TunnelToken:    security.Secret("tunnel-token-value-1234"),
		ClientToken:    security.Secret("client-token-value-1234"),
		RequestTimeout: time.Second,
	}
	registry := NewRegistry()
	listener, err := NewListener(config, registry, slog.New(slog.DiscardHandler))
	if err != nil {
		t.Fatalf("build listener: %v", err)
	}

	ctx, cancel := context.WithCancel(context.Background())
	done := make(chan error, 1)
	go func() {
		done <- listener.Serve(ctx)
	}()

	// Wait for the bind so the cancel does not race the listen call. Addr reports
	// the configured address until Serve has bound, so a different value means the
	// kernel has chosen a port and the listener is live.
	deadline := time.Now().Add(5 * time.Second)
	for listener.Addr() == config.Listen {
		if time.Now().After(deadline) {
			t.Fatal("the listener did not bind")
		}
		time.Sleep(5 * time.Millisecond)
	}

	cancel()

	select {
	case err := <-done:
		if err != nil {
			t.Fatalf("serve returned %v, want nil after a clean shutdown", err)
		}
	case <-time.After(10 * time.Second):
		t.Fatal("serve did not return after the context was cancelled")
	}
}
