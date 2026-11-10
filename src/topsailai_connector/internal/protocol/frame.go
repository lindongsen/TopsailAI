// Package protocol holds the wire contract shared by the Server and the Node.
//
// Everything in this package is pure data: constants, structs and validation
// helpers. It must never perform IO, open a network connection or import the
// server or node packages, because both sides compile it and a dependency in
// either direction would make the two binaries disagree about the contract.
package protocol

import "fmt"

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

// Hello is the payload of FrameHello, sent by the Node as the first frame.
//
// The tunnel token travels in this payload and nowhere else. It is a credential
// for the channel, so it is a field of the frame being validated and never a
// field of a struct the Server keeps: the Server compares it and releases it with
// the frame.
//
// Operations and Scopes are what the Node advertises. They are informational: the
// Server does not use them to decide anything, because the Node is the only
// authority for permissions. They exist so an operator reading a log can see what
// a Node offers without asking it.
type Hello struct {
	Version     string   `json:"version"`
	NodeID      string   `json:"node_id"`
	TunnelToken []byte   `json:"tunnel_token"`
	Operations  []string `json:"operations,omitempty"`
	Scopes      []string `json:"scopes,omitempty"`
}

// HelloConfirm is the payload of FrameHelloConfirm, sent by the Server.
//
// Generation is a monotonic counter the Server assigns to each accepted
// connection. It lets a Node tell a fresh acceptance from a replayed one, and it
// lets an operator correlate a log line on both sides without either side storing
// a credential.
type HelloConfirm struct {
	Version    string `json:"version"`
	Generation uint64 `json:"generation"`
}

// Validate checks that a hello carries the fields the Server needs.
//
// It refuses an empty node id and an empty tunnel token rather than letting the
// comparison decide, because an empty configured token compared against an empty
// presented token would match, and a deployment that forgot to set the variable
// would then accept every Node.
func (h Hello) Validate() error {
	if h.Version == "" {
		return fmt.Errorf("hello carries no version")
	}
	if h.NodeID == "" {
		return fmt.Errorf("hello carries no node id")
	}
	if len(h.TunnelToken) == 0 {
		return fmt.Errorf("hello carries no tunnel token")
	}
	return nil
}
