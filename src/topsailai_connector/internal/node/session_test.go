package node

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"io"
	"log/slog"
	"strings"
	"sync"
	"testing"

	"topsailai_connector/internal/protocol"
)

// scriptedConn replays a fixed sequence of frames and records what was written.
//
// A scripted sequence is how a test states the exact order the loop must handle,
// including orders a real peer would rarely produce, such as a request after a
// malformed frame.
type scriptedConn struct {
	mutex    sync.Mutex
	frames   []protocol.Frame
	index    int
	readErr  error
	writeErr error
	written  []protocol.Frame
}

// ReadFrame returns the next scripted frame, then the configured error.
func (c *scriptedConn) ReadFrame() (protocol.Frame, error) {
	c.mutex.Lock()
	defer c.mutex.Unlock()

	if c.index < len(c.frames) {
		frame := c.frames[c.index]
		c.index++
		return frame, nil
	}
	if c.readErr != nil {
		return protocol.Frame{}, c.readErr
	}
	return protocol.Frame{}, io.EOF
}

// WriteFrame records the frame and returns the configured error.
func (c *scriptedConn) WriteFrame(frame protocol.Frame) error {
	c.mutex.Lock()
	defer c.mutex.Unlock()

	if c.writeErr != nil {
		return c.writeErr
	}
	c.written = append(c.written, frame)
	return nil
}

// answers returns the frames written so far.
func (c *scriptedConn) answers() []protocol.Frame {
	c.mutex.Lock()
	defer c.mutex.Unlock()
	return append([]protocol.Frame(nil), c.written...)
}

// sessionFixture is a session over a scripted connection.
type sessionFixture struct {
	session  *Session
	conn     *scriptedConn
	dispatch *dispatchFixture
}

// newSessionFixture builds a session over the given dispatcher fixture.
//
// The dispatcher fixture is passed in rather than built here on purpose. A
// session that built its own fixture would hold a different Node identity from
// the one a test used to sign its request, so every request would be refused for
// a reason the test never intended to exercise.
func newSessionFixture(t *testing.T, dispatch *dispatchFixture, frames ...protocol.Frame) *sessionFixture {
	t.Helper()

	conn := &scriptedConn{frames: frames}
	logger := slog.New(slog.NewTextHandler(io.Discard, nil))

	return &sessionFixture{
		session:  NewSession(dispatch.dispatcher, conn, logger),
		conn:     conn,
		dispatch: dispatch,
	}
}

// requestFrame encodes a request into a request frame.
func requestFrame(t *testing.T, requestID string, request protocol.Request) protocol.Frame {
	t.Helper()

	payload, err := json.Marshal(request)
	if err != nil {
		t.Fatalf("marshal request: %v", err)
	}
	return protocol.Frame{Type: protocol.FrameRequest, RequestID: requestID, Payload: payload}
}

// decodeResponse decodes a response frame payload.
func decodeResponse(t *testing.T, frame protocol.Frame) protocol.Response {
	t.Helper()

	var response protocol.Response
	if err := json.Unmarshal(frame.Payload, &response); err != nil {
		t.Fatalf("decode response %q: %v", frame.Payload, err)
	}
	return response
}

// TestSessionServesRequest checks that a request frame is dispatched and answered
// with a response frame carrying the same request id.
func TestSessionServesRequest(t *testing.T) {
	dispatch := newDispatchFixture(t)
	request := dispatch.request(protocol.OperationFileRead, "project", "inside.txt")

	fixture := newSessionFixture(t, dispatch, requestFrame(t, "req_1", request))

	if err := fixture.session.Serve(context.Background()); err != nil {
		t.Fatalf("Serve() = %v, want nil", err)
	}

	answers := fixture.conn.answers()
	if len(answers) != 1 {
		t.Fatalf("wrote %d frames, want 1", len(answers))
	}
	if answers[0].Type != protocol.FrameResponse {
		t.Fatalf("frame type = %q, want response", answers[0].Type)
	}
	if answers[0].RequestID != "req_1" {
		t.Fatalf("request id = %q, want req_1", answers[0].RequestID)
	}

	response := decodeResponse(t, answers[0])
	if response.Code != protocol.CodeSuccess {
		t.Fatalf("code = %s, want success", response.Code.Name())
	}
	if len(response.Data) == 0 {
		t.Fatal("successful read carried no data")
	}
}

// TestSessionRelaysRefusal checks that a refusal from the dispatcher reaches the
// peer as a response frame with the same code.
func TestSessionRelaysRefusal(t *testing.T) {
	dispatch := newDispatchFixture(t)
	request := dispatch.request(protocol.OperationFileRead, "scratch", "inside.txt")

	fixture := newSessionFixture(t, dispatch, requestFrame(t, "req_2", request))

	if err := fixture.session.Serve(context.Background()); err != nil {
		t.Fatalf("Serve() = %v, want nil", err)
	}

	answers := fixture.conn.answers()
	if len(answers) != 1 {
		t.Fatalf("wrote %d frames, want 1", len(answers))
	}

	response := decodeResponse(t, answers[0])
	if response.Code != protocol.CodeDenied {
		t.Fatalf("code = %s, want denied", response.Code.Name())
	}
	if len(response.Data) != 0 {
		t.Fatalf("refusal carried data %q", response.Data)
	}
}

// TestSessionAnswersMalformedRequestFrame checks that a payload which does not
// decode is answered rather than dropped.
//
// A dropped request leaves the caller waiting for an answer that will never
// arrive, which is indistinguishable from a Node that is not answering.
func TestSessionAnswersMalformedRequestFrame(t *testing.T) {
	cases := []struct {
		name    string
		payload []byte
	}{
		{"empty", nil},
		{"not json", []byte("not json")},
		{"truncated", []byte(`{"operation":"file.read"`)},
		{"unknown field", []byte(`{"operation":"file.read","scope":"project","extra":1}`)},
		{"second document", []byte(`{"operation":"file.read"}{"operation":"file.list"}`)},
	}

	for _, testCase := range cases {
		fixture := newSessionFixture(t, newDispatchFixture(t), protocol.Frame{
			Type:      protocol.FrameRequest,
			RequestID: "req_bad",
			Payload:   testCase.payload,
		})

		if err := fixture.session.Serve(context.Background()); err != nil {
			t.Fatalf("%s: Serve() = %v, want nil", testCase.name, err)
		}

		answers := fixture.conn.answers()
		if len(answers) != 1 {
			t.Fatalf("%s: wrote %d frames, want 1", testCase.name, len(answers))
		}
		if answers[0].Type != protocol.FrameResponse {
			t.Fatalf("%s: frame type = %q, want response", testCase.name, answers[0].Type)
		}
		if answers[0].RequestID != "req_bad" {
			t.Fatalf("%s: request id = %q, want req_bad", testCase.name, answers[0].RequestID)
		}

		response := decodeResponse(t, answers[0])
		if response.Code != protocol.CodeInvalidArgument {
			t.Fatalf("%s: code = %s, want invalid_argument", testCase.name, response.Code.Name())
		}
	}
}

// TestSessionContinuesAfterMalformedFrame checks that one malformed frame does
// not drop a working channel.
func TestSessionContinuesAfterMalformedFrame(t *testing.T) {
	dispatch := newDispatchFixture(t)
	good := dispatch.request(protocol.OperationFileList, "project", "")

	fixture := newSessionFixture(t, dispatch,
		protocol.Frame{Type: protocol.FrameRequest, RequestID: "req_bad", Payload: []byte("not json")},
		requestFrame(t, "req_good", good),
	)

	if err := fixture.session.Serve(context.Background()); err != nil {
		t.Fatalf("Serve() = %v, want nil", err)
	}

	answers := fixture.conn.answers()
	if len(answers) != 2 {
		t.Fatalf("wrote %d frames, want 2", len(answers))
	}
	if decodeResponse(t, answers[0]).Code != protocol.CodeInvalidArgument {
		t.Fatalf("first answer = %s, want invalid_argument", decodeResponse(t, answers[0]).Code.Name())
	}
	if decodeResponse(t, answers[1]).Code != protocol.CodeSuccess {
		t.Fatalf("second answer = %s, want success", decodeResponse(t, answers[1]).Code.Name())
	}
}

// TestSessionAnswersHeartbeat checks that a heartbeat is answered, so the peer
// learns the link is alive in both directions.
func TestSessionAnswersHeartbeat(t *testing.T) {
	fixture := newSessionFixture(t, newDispatchFixture(t),
		protocol.Frame{Type: protocol.FrameHeartbeat, RequestID: "req_hb"},
	)

	if err := fixture.session.Serve(context.Background()); err != nil {
		t.Fatalf("Serve() = %v, want nil", err)
	}

	answers := fixture.conn.answers()
	if len(answers) != 1 {
		t.Fatalf("wrote %d frames, want 1", len(answers))
	}
	if answers[0].Type != protocol.FrameHeartbeat {
		t.Fatalf("frame type = %q, want heartbeat", answers[0].Type)
	}
	if answers[0].RequestID != "req_hb" {
		t.Fatalf("request id = %q, want req_hb", answers[0].RequestID)
	}
}

// TestSessionAnswersUnknownFrameType checks that an unknown frame type is
// answered, so a peer speaking a newer protocol learns it was not understood.
func TestSessionAnswersUnknownFrameType(t *testing.T) {
	fixture := newSessionFixture(t, newDispatchFixture(t),
		protocol.Frame{Type: protocol.FrameType("future"), RequestID: "req_new"},
	)

	if err := fixture.session.Serve(context.Background()); err != nil {
		t.Fatalf("Serve() = %v, want nil", err)
	}

	answers := fixture.conn.answers()
	if len(answers) != 1 {
		t.Fatalf("wrote %d frames, want 1", len(answers))
	}
	if answers[0].Type != protocol.FrameError {
		t.Fatalf("frame type = %q, want error", answers[0].Type)
	}
	if answers[0].RequestID != "req_new" {
		t.Fatalf("request id = %q, want req_new", answers[0].RequestID)
	}

	response := decodeResponse(t, answers[0])
	if response.Code != protocol.CodeUnsupportedOperation {
		t.Fatalf("code = %s, want unsupported_operation", response.Code.Name())
	}
}

// TestSessionStopsOnSecondHandshake checks that a handshake frame after the
// handshake stops the loop.
//
// A second hello is a renegotiation this version does not support, and continuing
// would mean guessing which hello is authoritative.
func TestSessionStopsOnSecondHandshake(t *testing.T) {
	for _, frameType := range []protocol.FrameType{protocol.FrameHello, protocol.FrameHelloConfirm} {
		fixture := newSessionFixture(t, newDispatchFixture(t),
			protocol.Frame{Type: frameType, RequestID: "req_hello"},
		)

		if err := fixture.session.Serve(context.Background()); err != nil {
			t.Fatalf("%q: Serve() = %v, want nil", frameType, err)
		}
		if len(fixture.conn.answers()) != 0 {
			t.Fatalf("%q: wrote %d frames, want 0", frameType, len(fixture.conn.answers()))
		}
	}
}

// TestSessionStopsOnResponseFrame checks that a response frame from the Server
// stops the loop, because the Node is the side that answers.
func TestSessionStopsOnResponseFrame(t *testing.T) {
	fixture := newSessionFixture(t, newDispatchFixture(t),
		protocol.Frame{Type: protocol.FrameResponse, RequestID: "req_r"},
	)

	if err := fixture.session.Serve(context.Background()); err != nil {
		t.Fatalf("Serve() = %v, want nil", err)
	}
	if len(fixture.conn.answers()) != 0 {
		t.Fatalf("wrote %d frames, want 0", len(fixture.conn.answers()))
	}
}

// TestSessionContinuesAfterErrorFrame checks that an error frame from the peer is
// logged and the loop continues.
func TestSessionContinuesAfterErrorFrame(t *testing.T) {
	dispatch := newDispatchFixture(t)
	good := dispatch.request(protocol.OperationFileStat, "project", "inside.txt")

	fixture := newSessionFixture(t, dispatch,
		protocol.Frame{Type: protocol.FrameError, RequestID: "req_err"},
		requestFrame(t, "req_good", good),
	)

	if err := fixture.session.Serve(context.Background()); err != nil {
		t.Fatalf("Serve() = %v, want nil", err)
	}

	answers := fixture.conn.answers()
	if len(answers) != 1 {
		t.Fatalf("wrote %d frames, want 1", len(answers))
	}
	if decodeResponse(t, answers[0]).Code != protocol.CodeSuccess {
		t.Fatalf("code = %s, want success", decodeResponse(t, answers[0]).Code.Name())
	}
}

// TestSessionReturnsReadError checks that a broken connection is reported rather
// than swallowed, because a closed connection and a broken one are different
// events and the caller decides which it was.
func TestSessionReturnsReadError(t *testing.T) {
	fixture := newSessionFixture(t, newDispatchFixture(t))
	fixture.conn.readErr = errors.New("connection reset")

	err := fixture.session.Serve(context.Background())
	if err == nil {
		t.Fatal("Serve() = nil, want the read error")
	}
	if !strings.Contains(err.Error(), "connection reset") {
		t.Fatalf("Serve() = %v, want the read error", err)
	}
}

// TestSessionReturnsNilOnEOF checks that a clean close is not an error.
func TestSessionReturnsNilOnEOF(t *testing.T) {
	fixture := newSessionFixture(t, newDispatchFixture(t))

	if err := fixture.session.Serve(context.Background()); err != nil {
		t.Fatalf("Serve() = %v, want nil", err)
	}
}

// TestSessionReturnsWriteError checks that a failed write stops the loop, because
// a Node that cannot answer must not keep reading requests it cannot serve.
func TestSessionReturnsWriteError(t *testing.T) {
	dispatch := newDispatchFixture(t)
	request := dispatch.request(protocol.OperationFileRead, "project", "inside.txt")

	fixture := newSessionFixture(t, dispatch, requestFrame(t, "req_1", request))
	fixture.conn.writeErr = errors.New("broken pipe")

	err := fixture.session.Serve(context.Background())
	if err == nil {
		t.Fatal("Serve() = nil, want the write error")
	}
	if !strings.Contains(err.Error(), "broken pipe") {
		t.Fatalf("Serve() = %v, want the write error", err)
	}
}

// TestSessionStopsOnCancelledContext checks that cancellation is observed between
// frames.
func TestSessionStopsOnCancelledContext(t *testing.T) {
	fixture := newSessionFixture(t, newDispatchFixture(t))

	ctx, cancel := context.WithCancel(context.Background())
	cancel()

	err := fixture.session.Serve(ctx)
	if !errors.Is(err, context.Canceled) {
		t.Fatalf("Serve() = %v, want context.Canceled", err)
	}
}

// TestSessionRefusesUnwiredSession checks that a session without a connection or
// a dispatcher refuses instead of panicking.
func TestSessionRefusesUnwiredSession(t *testing.T) {
	dispatch := newDispatchFixture(t)

	cases := []struct {
		name    string
		session *Session
	}{
		{"nil session", nil},
		{"nil connection", NewSession(dispatch.dispatcher, nil, nil)},
		{"nil dispatcher", NewSession(nil, &scriptedConn{}, nil)},
	}

	for _, testCase := range cases {
		err := testCase.session.Serve(context.Background())
		if err == nil {
			t.Fatalf("%s: Serve() = nil, want an error", testCase.name)
		}
	}
}

// TestJSONFrameConnRoundTrip checks that a frame survives the JSON stream.
func TestJSONFrameConnRoundTrip(t *testing.T) {
	original := protocol.Frame{
		Type:      protocol.FrameRequest,
		RequestID: "req_round",
		Payload:   []byte{0x00, 0xff, 0x10},
	}

	buffer := &bytes.Buffer{}
	if err := NewJSONFrameConn(nil, buffer).WriteFrame(original); err != nil {
		t.Fatalf("WriteFrame() = %v, want nil", err)
	}

	decoded, err := NewJSONFrameConn(buffer, nil).ReadFrame()
	if err != nil {
		t.Fatalf("ReadFrame() = %v, want nil", err)
	}
	if decoded.Type != original.Type {
		t.Fatalf("type = %q, want %q", decoded.Type, original.Type)
	}
	if decoded.RequestID != original.RequestID {
		t.Fatalf("request id = %q, want %q", decoded.RequestID, original.RequestID)
	}
	if !bytes.Equal(decoded.Payload, original.Payload) {
		t.Fatalf("payload = %v, want %v", decoded.Payload, original.Payload)
	}
}

// TestJSONFrameConnReadsSeveralFrames checks that the stream recovers frame
// boundaries without a length prefix.
func TestJSONFrameConnReadsSeveralFrames(t *testing.T) {
	buffer := &bytes.Buffer{}
	writer := NewJSONFrameConn(nil, buffer)
	for index := 0; index < 3; index++ {
		if err := writer.WriteFrame(protocol.Frame{Type: protocol.FrameHeartbeat, RequestID: "req"}); err != nil {
			t.Fatalf("WriteFrame() = %v, want nil", err)
		}
	}

	reader := NewJSONFrameConn(buffer, nil)
	for index := 0; index < 3; index++ {
		if _, err := reader.ReadFrame(); err != nil {
			t.Fatalf("frame %d: ReadFrame() = %v, want nil", index, err)
		}
	}
	if _, err := reader.ReadFrame(); !errors.Is(err, io.EOF) {
		t.Fatalf("ReadFrame() = %v, want io.EOF", err)
	}
}

// TestJSONFrameConnRejectsOversizedPayload checks that a declared payload over the
// cap is refused, so a peer cannot make the Node allocate an unbounded buffer.
func TestJSONFrameConnRejectsOversizedPayload(t *testing.T) {
	oversized := protocol.Frame{
		Type:    protocol.FrameRequest,
		Payload: make([]byte, MaxFramePayloadBytes+1),
	}

	buffer := &bytes.Buffer{}
	if err := NewJSONFrameConn(nil, buffer).WriteFrame(oversized); err != nil {
		t.Fatalf("WriteFrame() = %v, want nil", err)
	}

	if _, err := NewJSONFrameConn(buffer, nil).ReadFrame(); err == nil {
		t.Fatal("ReadFrame() = nil, want an error")
	}
}

// TestJSONFrameConnRefusesUnwiredConn checks that a connection without a reader or
// a writer refuses instead of panicking.
//
// A nil stream is the case that matters: json.NewDecoder(nil) returns a decoder
// that looks usable and panics on the first read, so the guard must test the
// stream rather than the decoder.
func TestJSONFrameConnRefusesUnwiredConn(t *testing.T) {
	if _, err := NewJSONFrameConn(nil, nil).ReadFrame(); err == nil {
		t.Fatal("ReadFrame() = nil, want an error")
	}
	if err := NewJSONFrameConn(nil, nil).WriteFrame(protocol.Frame{}); err == nil {
		t.Fatal("WriteFrame() = nil, want an error")
	}

	var nilConn *JSONFrameConn
	if _, err := nilConn.ReadFrame(); err == nil {
		t.Fatal("ReadFrame() on a nil connection = nil, want an error")
	}
	if err := nilConn.WriteFrame(protocol.Frame{}); err == nil {
		t.Fatal("WriteFrame() on a nil connection = nil, want an error")
	}
}

// TestJSONFrameConnRefusesNilReaderOnly checks that a write-only connection can
// still write, because a one-way stream is a legitimate use of the type.
func TestJSONFrameConnRefusesNilReaderOnly(t *testing.T) {
	buffer := &bytes.Buffer{}
	conn := NewJSONFrameConn(nil, buffer)

	if err := conn.WriteFrame(protocol.Frame{Type: protocol.FrameHeartbeat}); err != nil {
		t.Fatalf("WriteFrame() = %v, want nil", err)
	}
	if _, err := conn.ReadFrame(); err == nil {
		t.Fatal("ReadFrame() = nil, want an error")
	}
}
