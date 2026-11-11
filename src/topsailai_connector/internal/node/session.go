package node

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"log/slog"

	"topsailai_connector/internal/protocol"
)

// MaxFramePayloadBytes bounds the payload one frame may carry.
//
// The bound exists because the payload is decoded before it is interpreted, so an
// unbounded payload is the peer deciding how much memory the Node spends. It
// matches the Server's request body cap, so a request the Server accepted is never
// refused here for size alone.
const MaxFramePayloadBytes = 1 << 20

// FrameConn carries frames to and from the Server.
//
// The interface exists so the frame loop can be tested without a socket. The loop
// decides what a frame means; the connection decides how a frame travels. Keeping
// them apart means the dispatch rules can be exercised by a fake that returns a
// scripted sequence, including sequences a real peer would rarely produce.
type FrameConn interface {
	// ReadFrame returns the next frame. It blocks until a frame arrives or the
	// connection fails.
	ReadFrame() (protocol.Frame, error)
	// WriteFrame sends one frame.
	WriteFrame(frame protocol.Frame) error
}

// JSONFrameConn carries frames as a stream of JSON values.
//
// One frame is one JSON value, so a decoder over the stream recovers the frame
// boundaries without a length prefix. The payload is a byte slice, which JSON
// encodes as base64, so a frame carrying binary data survives the trip unchanged.
type JSONFrameConn struct {
	reader  io.Reader
	writer  io.Writer
	decoder *json.Decoder
	encoder *json.Encoder
}

// NewJSONFrameConn builds a frame connection over a reader and a writer.
//
// The reader and the writer are separate because a channel is full duplex: a
// response must be writable while a request is still being read. Either may be
// nil, which makes that direction unusable rather than silently broken: a nil
// reader is refused by ReadFrame and a nil writer by WriteFrame.
//
// The streams are kept so the guards can test them. Testing the decoder instead
// would not work, because json.NewDecoder(nil) returns a usable-looking decoder
// that panics on the first read rather than reporting an error.
func NewJSONFrameConn(reader io.Reader, writer io.Writer) *JSONFrameConn {
	conn := &JSONFrameConn{reader: reader, writer: writer}
	if reader != nil {
		conn.decoder = json.NewDecoder(reader)
	}
	if writer != nil {
		conn.encoder = json.NewEncoder(writer)
		conn.encoder.SetEscapeHTML(false)
	}
	return conn
}

// ReadFrame decodes the next frame.
//
// The payload is bounded before it is handed on, so a peer cannot make the Node
// allocate an unbounded buffer by declaring a large payload.
func (c *JSONFrameConn) ReadFrame() (protocol.Frame, error) {
	if c == nil || c.reader == nil || c.decoder == nil {
		return protocol.Frame{}, errors.New("frame connection is not readable")
	}

	var frame protocol.Frame
	if err := c.decoder.Decode(&frame); err != nil {
		return protocol.Frame{}, err
	}
	if len(frame.Payload) > MaxFramePayloadBytes {
		return protocol.Frame{}, fmt.Errorf("frame payload is %d bytes, limit is %d", len(frame.Payload), MaxFramePayloadBytes)
	}
	return frame, nil
}

// WriteFrame encodes one frame.
func (c *JSONFrameConn) WriteFrame(frame protocol.Frame) error {
	if c == nil || c.writer == nil || c.encoder == nil {
		return errors.New("frame connection is not writable")
	}
	return c.encoder.Encode(frame)
}

// Session serves frames from one connection.
//
// A session owns no policy of its own: every request is handed to the dispatcher,
// which consults the Node's authority. The session decides what a frame means and
// in what order, and nothing about whether an operation is allowed.
type Session struct {
	dispatcher *Dispatcher
	conn       FrameConn
	logger     *slog.Logger
}

// NewSession builds a session over one connection.
//
// A nil logger falls back to the default logger. A nil dispatcher or a nil
// connection is not substituted, because a session that cannot dispatch or cannot
// read has no frame to answer; Serve refuses such a session instead of panicking.
func NewSession(dispatcher *Dispatcher, conn FrameConn, logger *slog.Logger) *Session {
	if logger == nil {
		logger = slog.Default()
	}
	return &Session{dispatcher: dispatcher, conn: conn, logger: logger}
}

// Serve reads frames until the connection fails or the context is cancelled.
//
// Cancellation is observed between frames, because a read blocks. The owner
// unblocks a read by closing the connection, which is why Serve returns the read
// error rather than swallowing it: a closed connection and a broken one are
// different events and the caller decides which it was.
//
// A frame the Node cannot interpret is answered with an error frame and the loop
// continues, because one malformed frame is not a reason to drop a working
// channel. A frame that breaks the handshake order stops the loop, because a
// second hello is a renegotiation this version does not support and continuing
// would mean guessing which hello is authoritative.
func (s *Session) Serve(ctx context.Context) error {
	if s == nil || s.conn == nil || s.dispatcher == nil {
		return errors.New("session is not wired to a connection and a dispatcher")
	}

	for {
		if err := ctx.Err(); err != nil {
			return err
		}

		frame, err := s.conn.ReadFrame()
		if err != nil {
			if errors.Is(err, io.EOF) {
				return nil
			}
			return err
		}

		answer, keepGoing, err := s.handleFrame(frame)
		if err != nil {
			return err
		}
		if answer != nil {
			if err := s.conn.WriteFrame(*answer); err != nil {
				return err
			}
		}
		if !keepGoing {
			return nil
		}
	}
}

// handleFrame interprets one frame and returns the answer to send.
//
// The second result reports whether the loop continues. A request always
// continues; a handshake frame after the handshake does not.
func (s *Session) handleFrame(frame protocol.Frame) (*protocol.Frame, bool, error) {
	switch frame.Type {
	case protocol.FrameRequest:
		return s.handleRequest(frame), true, nil

	case protocol.FrameHeartbeat:
		// A heartbeat is answered with a heartbeat so the peer learns the link is
		// alive in both directions, not only that its own write succeeded.
		return &protocol.Frame{Type: protocol.FrameHeartbeat, RequestID: frame.RequestID}, true, nil

	case protocol.FrameError:
		// The peer reported a failure that is not tied to a request. It is logged
		// and the loop continues, because a peer that can still send an error is a
		// peer that can still send a request.
		s.logger.Warn("connector-node received an error frame",
			"node_id", s.dispatcher.holder.Current().ID,
			"request_id", frame.RequestID,
		)
		return nil, true, nil

	case protocol.FrameHello, protocol.FrameHelloConfirm:
		s.logger.Warn("connector-node received a handshake frame after the handshake",
			"node_id", s.dispatcher.holder.Current().ID,
			"frame_type", string(frame.Type),
		)
		return nil, false, nil

	case protocol.FrameResponse:
		s.logger.Warn("connector-node received a response frame from the server",
			"node_id", s.dispatcher.holder.Current().ID,
			"request_id", frame.RequestID,
		)
		return nil, false, nil

	default:
		// An unknown frame type is answered rather than ignored, so a peer that
		// speaks a newer protocol learns that this Node did not understand it
		// instead of waiting for an answer that will never come.
		s.logger.Warn("connector-node received an unknown frame type",
			"node_id", s.dispatcher.holder.Current().ID,
			"frame_type", string(frame.Type),
		)
		return &protocol.Frame{
			Type:      protocol.FrameError,
			RequestID: frame.RequestID,
			Payload:   errorPayload(protocol.CodeUnsupportedOperation),
		}, true, nil
	}
}

// handleRequest decodes one request, dispatches it and encodes the answer.
//
// The request id is echoed on the response so the Server can match an answer to
// the request it forwarded. A payload that does not decode is answered with
// invalid_argument rather than dropped, because a dropped request leaves the
// caller waiting for an answer that will never arrive.
func (s *Session) handleRequest(frame protocol.Frame) *protocol.Frame {
	request, err := decodeRequestPayload(frame.Payload)
	if err != nil {
		s.logger.Warn("connector-node refused a malformed request frame",
			"node_id", s.dispatcher.holder.Current().ID,
			"request_id", frame.RequestID,
			"reason", err.Error(),
		)
		return &protocol.Frame{
			Type:      protocol.FrameResponse,
			RequestID: frame.RequestID,
			Payload:   responsePayload(protocol.Failure(protocol.CodeInvalidArgument)),
		}
	}

	response := s.dispatcher.Dispatch(request)
	return &protocol.Frame{
		Type:      protocol.FrameResponse,
		RequestID: frame.RequestID,
		Payload:   responsePayload(response),
	}
}

// decodeRequestPayload decodes a request from a frame payload.
//
// Unknown fields are refused rather than ignored, so a peer that sends a field
// this version does not know learns about it instead of sending a request that
// silently does less than it says.
func decodeRequestPayload(payload []byte) (protocol.Request, error) {
	if len(payload) == 0 {
		return protocol.Request{}, errors.New("request frame carries no payload")
	}
	if len(payload) > MaxFramePayloadBytes {
		return protocol.Request{}, fmt.Errorf("request payload is %d bytes, limit is %d", len(payload), MaxFramePayloadBytes)
	}

	decoder := json.NewDecoder(bytes.NewReader(payload))
	decoder.DisallowUnknownFields()

	var request protocol.Request
	if err := decoder.Decode(&request); err != nil {
		return protocol.Request{}, err
	}
	if err := decoder.Decode(new(json.RawMessage)); !errors.Is(err, io.EOF) {
		return protocol.Request{}, errors.New("request payload carries more than one JSON document")
	}
	return request, nil
}

// responsePayload encodes a response for a frame payload.
//
// A response that cannot be encoded becomes an internal failure rather than an
// empty payload, because an empty payload is a response the Server cannot read and
// would report as a malformed answer instead of a Node failure.
func responsePayload(response protocol.Response) []byte {
	payload, err := json.Marshal(response)
	if err != nil {
		return errorPayload(protocol.CodeInternal)
	}
	return payload
}

// errorPayload encodes a bare failure for a frame payload.
func errorPayload(code protocol.Code) []byte {
	payload, err := json.Marshal(protocol.Failure(code))
	if err != nil {
		return nil
	}
	return payload
}
