package node

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"log/slog"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/gorilla/websocket"

	"topsailai_connector/internal/protocol"
	"topsailai_connector/internal/security"
)

// dialerTestNodeID is the address the fixture dialer serves under.
//
// It is a fixed value rather than a generated one so a test can assert the hello it
// receives without threading a value through the fixture.
const dialerTestNodeID = "node_0123456789abcdefghijklmnop"

// dialerFixture is a dialer wired to a fake Server.
type dialerFixture struct {
	dialer *Dialer
	server *httptest.Server
	hello  chan protocol.Hello
}

// newDialerFixture builds a dialer pointed at a fake Server.
//
// The fake Server speaks the handshake by hand rather than using the real Server
// package, because the Node must be testable without the Server: a test that
// needed both would fail for either side's reason and would not say which.
func newDialerFixture(t *testing.T, answer func(protocol.Hello) []protocol.Frame) *dialerFixture {
	t.Helper()
	return newDialerFixtureWithLogger(t, answer, slog.New(slog.DiscardHandler))
}

// newDialerFixtureWithLogger builds a dialer whose log lines the caller can
// inspect, so a test can assert what a shutdown does and does not report.
func newDialerFixtureWithLogger(t *testing.T, answer func(protocol.Hello) []protocol.Frame, logger *slog.Logger) *dialerFixture {
	t.Helper()

	hello := make(chan protocol.Hello, 1)
	upgrader := websocket.Upgrader{CheckOrigin: func(*http.Request) bool { return true }}

	server := httptest.NewServer(http.HandlerFunc(func(writer http.ResponseWriter, request *http.Request) {
		conn, err := upgrader.Upgrade(writer, request, nil)
		if err != nil {
			return
		}
		defer func() {
			_ = conn.Close()
		}()

		_, data, err := conn.ReadMessage()
		if err != nil {
			return
		}
		var frame protocol.Frame
		if err := json.Unmarshal(data, &frame); err != nil {
			return
		}
		var received protocol.Hello
		if err := json.Unmarshal(frame.Payload, &received); err != nil {
			return
		}
		hello <- received

		for _, outbound := range answer(received) {
			encoded, err := json.Marshal(outbound)
			if err != nil {
				return
			}
			if err := conn.WriteMessage(websocket.TextMessage, encoded); err != nil {
				return
			}
		}

		// Keep the connection open until the client closes it, so the session has
		// something to read after the handshake.
		for {
			if _, _, err := conn.ReadMessage(); err != nil {
				return
			}
		}
	}))
	t.Cleanup(server.Close)

	config := Config{
		ServerURL:   "ws" + strings.TrimPrefix(server.URL, "http"),
		TunnelToken: security.Secret("tunnel-token-value-1234"),
		ConfigDir:   t.TempDir(),
	}

	nodeID := dialerTestNodeID
	credentials := nodeTestCredentialSet(t)
	holder := NewIdentityHolder(nodeID, credentials)

	dispatcher, err := NewDispatcher(nil, holder, security.DefaultReplayWindow, security.DefaultReplayCapacity, slog.New(slog.DiscardHandler))
	if err != nil {
		t.Fatalf("build dispatcher: %v", err)
	}
	dialer, err := NewDialer(config, nodeID, credentials, dispatcher, logger)
	if err != nil {
		t.Fatalf("build dialer: %v", err)
	}

	return &dialerFixture{dialer: dialer, server: server, hello: hello}
}

// confirmFrame returns a hello_confirm frame.
func confirmFrame() protocol.Frame {
	payload, _ := json.Marshal(protocol.HelloConfirm{Version: protocol.Version, Generation: 1})
	return protocol.Frame{Type: protocol.FrameHelloConfirm, Payload: payload}
}

// errorFrame returns an error frame carrying one code.
func errorFrame(code protocol.Code) protocol.Frame {
	payload, _ := json.Marshal(protocol.Response{Code: code})
	return protocol.Frame{Type: protocol.FrameError, Payload: payload}
}

// TestDialerSendsHelloWithTunnelToken checks that the Node presents the tunnel
// token and its own identity in hello, which is what the Server validates.
func TestDialerSendsHelloWithTunnelToken(t *testing.T) {
	fixture := newDialerFixture(t, func(protocol.Hello) []protocol.Frame {
		return []protocol.Frame{confirmFrame()}
	})

	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()

	go func() {
		_ = fixture.dialer.connectOnce(ctx)
	}()

	select {
	case hello := <-fixture.hello:
		if hello.Version != protocol.Version {
			t.Fatalf("version = %q, want %q", hello.Version, protocol.Version)
		}
		if hello.NodeID != "node_0123456789abcdefghijklmnop" {
			t.Fatalf("node id = %q, want the identity id", hello.NodeID)
		}
		if string(hello.TunnelToken) != "tunnel-token-value-1234" {
			t.Fatalf("tunnel token was not presented")
		}
	case <-time.After(5 * time.Second):
		t.Fatal("the node did not send hello")
	}
}

// TestDialerAdvertisesEnabledOperations checks that hello advertises only the
// operations this binary implements, so a Node does not claim a capability it
// cannot serve.
func TestDialerAdvertisesEnabledOperations(t *testing.T) {
	fixture := newDialerFixture(t, func(protocol.Hello) []protocol.Frame {
		return []protocol.Frame{confirmFrame()}
	})

	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()

	go func() {
		_ = fixture.dialer.connectOnce(ctx)
	}()

	select {
	case hello := <-fixture.hello:
		for _, operation := range hello.Operations {
			if operation == string(protocol.OperationFileWrite) || operation == string(protocol.OperationCommandExec) {
				t.Fatalf("hello advertises %q, which this version does not implement", operation)
			}
		}
		if len(hello.Operations) != 3 {
			t.Fatalf("operations = %v, want the three read-only operations", hello.Operations)
		}
	case <-time.After(5 * time.Second):
		t.Fatal("the node did not send hello")
	}
}

// TestDialerRefusesHandshakeError checks that a refusal is reported as
// ErrHandshakeRefused, so the caller can tell a wrong credential from a network
// failure.
func TestDialerRefusesHandshakeError(t *testing.T) {
	fixture := newDialerFixture(t, func(protocol.Hello) []protocol.Frame {
		return []protocol.Frame{errorFrame(protocol.CodeUnauthenticated)}
	})

	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()

	err := fixture.dialer.connectOnce(ctx)
	if !errors.Is(err, ErrHandshakeRefused) {
		t.Fatalf("error = %v, want %v", err, ErrHandshakeRefused)
	}
}

// TestDialerRefusesWrongProtocolVersion checks that a Server speaking a different
// version is refused, so a mismatched pair fails at connect time instead of at the
// first frame.
func TestDialerRefusesWrongProtocolVersion(t *testing.T) {
	fixture := newDialerFixture(t, func(protocol.Hello) []protocol.Frame {
		payload, _ := json.Marshal(protocol.HelloConfirm{Version: "9.9", Generation: 1})
		return []protocol.Frame{{Type: protocol.FrameHelloConfirm, Payload: payload}}
	})

	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()

	if err := fixture.dialer.connectOnce(ctx); err == nil {
		t.Fatal("expected an error for a mismatched protocol version")
	}
}

// TestDialerRefusesUnexpectedHandshakeAnswer checks that an answer that is neither
// a confirmation nor an error is refused, because guessing what it meant would be
// inventing a handshake.
func TestDialerRefusesUnexpectedHandshakeAnswer(t *testing.T) {
	fixture := newDialerFixture(t, func(protocol.Hello) []protocol.Frame {
		return []protocol.Frame{{Type: protocol.FrameHeartbeat}}
	})

	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()

	if err := fixture.dialer.connectOnce(ctx); err == nil {
		t.Fatal("expected an error for an unexpected handshake answer")
	}
}

// TestDialerServesRequestAfterHandshake checks that a request arriving after the
// handshake is dispatched and answered, which is the whole point of the channel.
func TestDialerServesRequestAfterHandshake(t *testing.T) {
	requestFrame := func() protocol.Frame {
		request := signNodeRequest(t, protocol.Request{
			NodeID:    dialerTestNodeID,
			Operation: protocol.OperationFileRead,
			Scope:     security.Scope("project"),
			Path:      "a.txt",
		}, nodeTestCredential)
		payload, _ := json.Marshal(request)
		return protocol.Frame{Type: protocol.FrameRequest, RequestID: "wire-1", Payload: payload}
	}

	answer := make(chan protocol.Frame, 1)
	upgrader := websocket.Upgrader{CheckOrigin: func(*http.Request) bool { return true }}

	server := httptest.NewServer(http.HandlerFunc(func(writer http.ResponseWriter, request *http.Request) {
		conn, err := upgrader.Upgrade(writer, request, nil)
		if err != nil {
			return
		}
		defer func() {
			_ = conn.Close()
		}()

		if _, _, err := conn.ReadMessage(); err != nil {
			return
		}
		encoded, _ := json.Marshal(confirmFrame())
		if err := conn.WriteMessage(websocket.TextMessage, encoded); err != nil {
			return
		}

		outbound, _ := json.Marshal(requestFrame())
		if err := conn.WriteMessage(websocket.TextMessage, outbound); err != nil {
			return
		}

		_, data, err := conn.ReadMessage()
		if err != nil {
			return
		}
		var frame protocol.Frame
		if err := json.Unmarshal(data, &frame); err != nil {
			return
		}
		answer <- frame
	}))
	t.Cleanup(server.Close)

	config := Config{
		ServerURL:   "ws" + strings.TrimPrefix(server.URL, "http"),
		TunnelToken: security.Secret("tunnel-token-value-1234"),
		ConfigDir:   t.TempDir(),
	}
	credentials := nodeTestCredentialSet(t)
	holder := NewIdentityHolder(dialerTestNodeID, credentials)
	dispatcher, err := NewDispatcher(nil, holder, security.DefaultReplayWindow, security.DefaultReplayCapacity, slog.New(slog.DiscardHandler))
	if err != nil {
		t.Fatalf("build dispatcher: %v", err)
	}
	dialer, err := NewDialer(config, dialerTestNodeID, credentials, dispatcher, slog.New(slog.DiscardHandler))
	if err != nil {
		t.Fatalf("build dialer: %v", err)
	}

	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()

	go func() {
		_ = dialer.connectOnce(ctx)
	}()

	select {
	case frame := <-answer:
		if frame.Type != protocol.FrameResponse {
			t.Fatalf("frame type = %q, want %q", string(frame.Type), string(protocol.FrameResponse))
		}
		if frame.RequestID != "wire-1" {
			t.Fatalf("request id = %q, want %q", frame.RequestID, "wire-1")
		}
		var response protocol.Response
		if err := json.Unmarshal(frame.Payload, &response); err != nil {
			t.Fatalf("decode response: %v", err)
		}
		// The dispatcher was built without an authority, so every operation is
		// refused. The refusal is the proof that the request reached the
		// dispatcher rather than being dropped.
		if response.Code == protocol.CodeSuccess {
			t.Fatal("expected a refusal from a dispatcher with no authority")
		}
	case <-time.After(5 * time.Second):
		t.Fatal("the node did not answer the request")
	}
}

// TestDialerRunStopsOnContextCancel checks that cancelling the context stops the
// reconnect loop, so a shutdown does not wait for the retry delay.
func TestDialerRunStopsOnContextCancel(t *testing.T) {
	fixture := newDialerFixture(t, func(protocol.Hello) []protocol.Frame {
		return []protocol.Frame{errorFrame(protocol.CodeUnauthenticated)}
	})

	ctx, cancel := context.WithCancel(context.Background())
	done := make(chan error, 1)
	go func() {
		done <- fixture.dialer.Run(ctx)
	}()

	// Wait for the first attempt so the cancel does not race the dial.
	select {
	case <-fixture.hello:
	case <-time.After(5 * time.Second):
		t.Fatal("the node did not attempt a connection")
	}

	cancel()

	select {
	case err := <-done:
		if err != nil {
			t.Fatalf("run returned %v, want nil after a cancellation", err)
		}
	case <-time.After(5 * time.Second):
		t.Fatal("run did not return after the context was cancelled")
	}
}

// syncBuffer is a bytes.Buffer safe for concurrent use, because the identity
// callback runs on its own goroutine while the test reads the log.
type syncBuffer struct {
	mu     sync.Mutex
	buffer bytes.Buffer
}

// Write appends to the buffer under the lock.
func (b *syncBuffer) Write(p []byte) (int, error) {
	b.mu.Lock()
	defer b.mu.Unlock()
	return b.buffer.Write(p)
}

// String returns the log written so far under the lock.
func (b *syncBuffer) String() string {
	b.mu.Lock()
	defer b.mu.Unlock()
	return b.buffer.String()
}

// waitForLog waits until the log contains a marker, so a test can act only once
// the dialer has reached the state it means to exercise.
//
// Waiting on the log rather than on a fixed sleep is what makes the shutdown test
// meaningful: cancelling before the session starts would return from the context
// check at the top of the loop and never reach the blocked read that the socket
// close exists to interrupt.
func (b *syncBuffer) waitForLog(t *testing.T, marker string) {
	t.Helper()
	deadline := time.Now().Add(5 * time.Second)
	for time.Now().Before(deadline) {
		if strings.Contains(b.String(), marker) {
			return
		}
		time.Sleep(5 * time.Millisecond)
	}
	t.Fatalf("the log never contained %q: %q", marker, b.String())
}

// TestDialerShutdownDoesNotReportAnIdentityChange checks that a normal shutdown
// does not claim the identity changed. The change context is derived from the
// session context, so it is cancelled by a shutdown as well as by a real change;
// reporting the shutdown as a change sends an operator looking for a
// regeneration that never happened.
func TestDialerShutdownDoesNotReportAnIdentityChange(t *testing.T) {
	logs := &syncBuffer{}
	fixture := newDialerFixtureWithLogger(t, func(protocol.Hello) []protocol.Frame {
		return []protocol.Frame{confirmFrame()}
	}, slog.New(slog.NewTextHandler(logs, nil)))

	// A real channel rather than nil, because a nil channel never delivers and
	// the watcher goroutine would not start, which is the state that hid this
	// defect from every other test in this file.
	changes := make(chan string, 1)
	fixture.dialer.identityChanges = changes

	ctx, cancel := context.WithCancel(context.Background())
	done := make(chan error, 1)
	go func() {
		done <- fixture.dialer.connectOnce(ctx)
	}()

	// Wait for the session to be serving, not merely for the hello to arrive.
	// Cancelling before the session starts would return from the context check at
	// the top of the loop and never reach the blocked read that the socket close
	// exists to interrupt, so the test would pass without exercising the path.
	logs.waitForLog(t, "channel established")

	cancel()

	select {
	case <-done:
	case <-time.After(5 * time.Second):
		t.Fatal("connectOnce did not return after the context was cancelled")
	}

	// The shutdown branch returns before logging, so the absence of the line is the
	// property. Asserting on the old wording would pass against a log line that no
	// longer exists, which is how a guard stops measuring anything.
	if report := logs.String(); strings.Contains(report, "closing the channel") {
		t.Fatalf("a shutdown reported a channel drop: %q", report)
	}
}

// TestDialerReportsAGenuineIdentityChange checks that a real change is still
// reported. Without this test the shutdown test above could be satisfied by
// deleting the message, which would hide a real regeneration instead of fixing
// the false report.
func TestDialerReportsAGenuineIdentityChange(t *testing.T) {
	logs := &syncBuffer{}
	fixture := newDialerFixtureWithLogger(t, func(protocol.Hello) []protocol.Frame {
		return []protocol.Frame{confirmFrame()}
	}, slog.New(slog.NewTextHandler(logs, nil)))

	changes := make(chan string, 1)
	fixture.dialer.identityChanges = changes

	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	done := make(chan error, 1)
	go func() {
		done <- fixture.dialer.connectOnce(ctx)
	}()

	// Wait for the session to be serving, so the change arrives while the read is
	// blocked and the callback is the thing that ends it.
	logs.waitForLog(t, "channel established")

	changes <- identityChangeReason

	select {
	case <-done:
	case <-time.After(5 * time.Second):
		t.Fatal("connectOnce did not return after an identity change")
	}

	report := logs.String()
	if !strings.Contains(report, "closing the channel") {
		t.Fatalf("an identity change was not reported: %q", report)
	}
	if !strings.Contains(report, `reason="`+identityChangeReason+`"`) {
		t.Fatalf("the identity change was reported with the wrong reason: %q", report)
	}
}

// TestDialerReportsAReconnectAsAServerChange checks that a repoint is reported as a
// repoint.
//
// This is the defect the reason split exists for. The measured case was a console
// `server ws://new` that logged "identity changed; closing the channel authenticated
// with the retired node id" while the identity had not changed at all, which sends an
// operator looking for a regeneration that never happened.
//
// The test drives RequestReconnect rather than sending on the channel directly, because
// the method is what the console calls: a test that sent the reason itself would pass
// with RequestReconnect wired to the wrong constant.
func TestDialerReportsAReconnectAsAServerChange(t *testing.T) {
	logs := &syncBuffer{}
	fixture := newDialerFixtureWithLogger(t, func(protocol.Hello) []protocol.Frame {
		return []protocol.Frame{confirmFrame()}
	}, slog.New(slog.NewTextHandler(logs, nil)))

	changes := make(chan string, 1)
	fixture.dialer.identityChanges = changes

	// The sending end is published the way Run publishes it, so RequestReconnect has a
	// channel to write to. Without this the method is a no-op and the test would pass
	// against a dialer that never dropped anything.
	fixture.dialer.identityChangeMutex.Lock()
	fixture.dialer.identityChangeRequests = changes
	fixture.dialer.identityChangeMutex.Unlock()

	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	done := make(chan error, 1)
	go func() {
		done <- fixture.dialer.connectOnce(ctx)
	}()

	logs.waitForLog(t, "channel established")

	fixture.dialer.RequestReconnect()

	select {
	case <-done:
	case <-time.After(5 * time.Second):
		t.Fatal("connectOnce did not return after a reconnect request")
	}

	report := logs.String()
	if !strings.Contains(report, "closing the channel") {
		t.Fatalf("a reconnect was not reported: %q", report)
	}
	if !strings.Contains(report, `reason="`+serverChangeReason+`"`) {
		t.Fatalf("a reconnect was reported with the wrong reason: %q", report)
	}
	if strings.Contains(report, `reason="`+identityChangeReason+`"`) {
		t.Fatalf("a reconnect was reported as an identity change: %q", report)
	}
}

// TestDialerDialsTheRepointedAddress checks the property a repoint exists for: the next
// dial goes to the new Server.
//
// The console test proves the runtime holds the new address and that the dialer was
// handed it. Neither proves the dial loop uses it, and a dialer that reported the new
// address while dialling the old one is exactly the failure the operator would describe
// as "the change did not take". This test therefore counts hellos on two fake Servers.
func TestDialerDialsTheRepointedAddress(t *testing.T) {
	first := newHelloCountingServer(t)
	second := newHelloCountingServer(t)

	fixture := newDialerFixture(t, func(protocol.Hello) []protocol.Frame {
		return []protocol.Frame{confirmFrame()}
	})

	// The fixture dials its own fake Server. Point it at the first counting Server so
	// both connections in this test are observed by a counter.
	fixture.dialer.SetServerURL(first.url())

	// connectOnce serves the connection until it ends, so each dial is driven in its own
	// goroutine and ended by cancelling its own context. A single shared context would
	// make the second dial reuse a cancelled one and the test would measure the context
	// rather than the address.
	dialOnce := func(expected *helloCountingServer, want int) {
		t.Helper()

		ctx, cancel := context.WithCancel(context.Background())
		done := make(chan error, 1)
		go func() {
			done <- fixture.dialer.connectOnce(ctx)
		}()

		// Wait for the hello to reach the Server that was dialled, not merely for any
		// hello to arrive: a wait on the total count would break on the previous dial's
		// hello and cancel before the new one was sent, which is how the first version of
		// this test measured nothing.
		deadline := time.Now().Add(5 * time.Second)
		for time.Now().Before(deadline) {
			if expected.count() >= want {
				break
			}
			time.Sleep(5 * time.Millisecond)
		}

		cancel()

		select {
		case <-done:
		case <-time.After(5 * time.Second):
			t.Fatal("connectOnce did not return after the context was cancelled")
		}
	}

	fixture.dialer.SetServerURL(first.url())
	dialOnce(first, 1)

	if got := first.count(); got != 1 {
		t.Fatalf("the first server received %d hellos, want 1", got)
	}
	if got := second.count(); got != 0 {
		t.Fatalf("the second server received %d hellos before the repoint, want 0", got)
	}

	fixture.dialer.SetServerURL(second.url())
	dialOnce(second, 1)

	if got := second.count(); got != 1 {
		t.Fatalf("the second server received %d hellos after a repoint, want 1", got)
	}
	if got := first.count(); got != 1 {
		t.Fatalf("the first server received %d hellos after a repoint, want the unchanged 1", got)
	}
}

// helloCountingServer is a fake Server that counts the hellos it receives.
type helloCountingServer struct {
	server *httptest.Server
	hello  chan protocol.Hello
}

// url returns the ws address of the counting Server.
func (s *helloCountingServer) url() string {
	return "ws" + strings.TrimPrefix(s.server.URL, "http")
}

// count returns how many hellos the Server has received so far.
func (s *helloCountingServer) count() int {
	return len(s.hello)
}

// newHelloCountingServer starts a fake Server that answers every hello with a
// confirmation and keeps the connection open.
func newHelloCountingServer(t *testing.T) *helloCountingServer {
	t.Helper()

	hello := make(chan protocol.Hello, 8)
	upgrader := websocket.Upgrader{CheckOrigin: func(*http.Request) bool { return true }}

	server := httptest.NewServer(http.HandlerFunc(func(writer http.ResponseWriter, request *http.Request) {
		conn, err := upgrader.Upgrade(writer, request, nil)
		if err != nil {
			return
		}
		defer func() {
			_ = conn.Close()
		}()

		_, data, err := conn.ReadMessage()
		if err != nil {
			return
		}
		var frame protocol.Frame
		if err := json.Unmarshal(data, &frame); err != nil {
			return
		}
		var received protocol.Hello
		if err := json.Unmarshal(frame.Payload, &received); err != nil {
			return
		}
		hello <- received

		encoded, err := json.Marshal(confirmFrame())
		if err != nil {
			return
		}
		if err := conn.WriteMessage(websocket.TextMessage, encoded); err != nil {
			return
		}

		for {
			if _, _, err := conn.ReadMessage(); err != nil {
				return
			}
		}
	}))
	t.Cleanup(server.Close)

	return &helloCountingServer{server: server, hello: hello}
}

// TestNewDialerRefusesNilDispatcher checks that a dialer without a dispatcher is
// refused, because it would accept requests and have no answer.
func TestNewDialerRefusesNilDispatcher(t *testing.T) {
	if _, err := NewDialer(Config{}, dialerTestNodeID, nodeTestCredentialSet(t), nil, slog.New(slog.DiscardHandler)); err == nil {
		t.Fatal("expected an error for a nil dispatcher")
	}
}

// TestNewDialerRefusesUnusableIdentity checks that a dialer with a malformed node
// id is refused, because the Server would refuse the hello and the failure would
// appear as a network problem.
func TestNewDialerRefusesUnusableIdentity(t *testing.T) {
	credentials := nodeTestCredentialSet(t)
	holder := NewIdentityHolder("not-a-node-id", credentials)
	dispatcher, err := NewDispatcher(nil, holder, security.DefaultReplayWindow, security.DefaultReplayCapacity, slog.New(slog.DiscardHandler))
	if err != nil {
		t.Fatalf("build dispatcher: %v", err)
	}

	if _, err := NewDialer(Config{}, "not-a-node-id", credentials, dispatcher, slog.New(slog.DiscardHandler)); err == nil {
		t.Fatal("expected an error for an unusable identity")
	}
}

// TestNewSocketFrameConnRefusesNil checks that a nil connection is refused at
// construction, so the failure is reported where the mistake was made rather than
// at the first read.
func TestNewSocketFrameConnRefusesNil(t *testing.T) {
	if _, err := NewSocketFrameConn(nil); err == nil {
		t.Fatal("expected an error for a nil connection")
	}
}

// TestSocketFrameConnRefusesNilReceiver checks that a nil adapter reports an error
// instead of panicking, because a panic on a request path is a denial of service.
func TestSocketFrameConnRefusesNilReceiver(t *testing.T) {
	var conn *SocketFrameConn

	if _, err := conn.ReadFrame(); err == nil {
		t.Fatal("expected an error reading from a nil connection")
	}
	if err := conn.WriteFrame(protocol.Frame{}); err == nil {
		t.Fatal("expected an error writing to a nil connection")
	}
	if err := conn.Close(); err != nil {
		t.Fatalf("closing a nil connection returned %v, want nil", err)
	}
}
