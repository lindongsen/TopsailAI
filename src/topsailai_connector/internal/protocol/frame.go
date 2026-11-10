// Package protocol holds the wire contract shared by the Server and the Node.
//
// Everything in this package is pure data: constants, structs and validation
// helpers. It must never perform IO, open a network connection or import the
// server or node packages, because both sides compile it and a dependency in
// either direction would make the two binaries disagree about the contract.
package protocol

// Version is the wire protocol version. The Server and the Node exchange it
// during the handshake and refuse to continue when the major part differs, so a
// mismatched pair fails at connect time instead of at the first frame.
const Version = "1.0"

// FrameType names one kind of frame carried by the channel.
type FrameType string

const (
	// FrameHello is the first frame the Node sends after connecting.
	FrameHello FrameType = "hello"
	// FrameHelloConfirm is the Server's answer to FrameHello.
	FrameHelloConfirm FrameType = "hello_confirm"
	// FrameHeartbeat keeps the link observable while no request is in flight.
	FrameHeartbeat FrameType = "heartbeat"
	// FrameRequest carries one operation the Server asks the Node to perform.
	FrameRequest FrameType = "request"
	// FrameResponse carries the result of one FrameRequest.
	FrameResponse FrameType = "response"
	// FrameError reports a failure that is not tied to a single request.
	FrameError FrameType = "error"
)

// Frame is the envelope every message travels in. The payload stays opaque at
// this layer so a new operation does not change the envelope.
type Frame struct {
	Type      FrameType `json:"type"`
	RequestID string    `json:"request_id,omitempty"`
	Payload   []byte    `json:"payload,omitempty"`
}
