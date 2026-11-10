package protocol

import (
	"encoding/json"
	"testing"
)

// TestFrameRoundTrip checks that a frame survives JSON encoding unchanged, so
// the envelope both sides exchange keeps its type, request id and payload.
func TestFrameRoundTrip(t *testing.T) {
	original := Frame{Type: FrameRequest, RequestID: "req-1", Payload: []byte("payload")}

	encoded, err := json.Marshal(original)
	if err != nil {
		t.Fatalf("marshal frame: %v", err)
	}

	var decoded Frame
	if err := json.Unmarshal(encoded, &decoded); err != nil {
		t.Fatalf("unmarshal frame: %v", err)
	}

	if decoded.Type != original.Type {
		t.Fatalf("type = %q, want %q", decoded.Type, original.Type)
	}
	if decoded.RequestID != original.RequestID {
		t.Fatalf("request id = %q, want %q", decoded.RequestID, original.RequestID)
	}
	if string(decoded.Payload) != string(original.Payload) {
		t.Fatalf("payload = %q, want %q", decoded.Payload, original.Payload)
	}
}

// TestVersionIsSet checks that the protocol version is declared, because the
// handshake compares it and an empty version would match anything.
func TestVersionIsSet(t *testing.T) {
	if Version == "" {
		t.Fatal("protocol version is empty")
	}
}

// TestHelloValidateAcceptsCompleteHello checks that a hello carrying every field
// the Server needs is accepted, so the handshake does not refuse a well formed
// first frame.
func TestHelloValidateAcceptsCompleteHello(t *testing.T) {
	hello := Hello{
		Version:     Version,
		NodeID:      "node_0123456789abcdefghijklmnop",
		TunnelToken: []byte("tunnel-token-value"),
		Operations:  []string{"file.read"},
		Scopes:      []string{"project"},
	}

	if err := hello.Validate(); err != nil {
		t.Fatalf("validate hello: %v", err)
	}
}

// TestHelloValidateRejectsEmptyVersion checks that a hello without a version is
// refused, because the handshake cannot decide compatibility without it.
func TestHelloValidateRejectsEmptyVersion(t *testing.T) {
	hello := Hello{
		NodeID:      "node_0123456789abcdefghijklmnop",
		TunnelToken: []byte("tunnel-token-value"),
	}

	if err := hello.Validate(); err == nil {
		t.Fatal("expected an error for an empty version")
	}
}

// TestHelloValidateRejectsEmptyNodeID checks that a hello without a node id is
// refused, because the Server has no connection to register it under.
func TestHelloValidateRejectsEmptyNodeID(t *testing.T) {
	hello := Hello{
		Version:     Version,
		TunnelToken: []byte("tunnel-token-value"),
	}

	if err := hello.Validate(); err == nil {
		t.Fatal("expected an error for an empty node id")
	}
}

// TestHelloValidateRejectsEmptyTunnelToken checks that a hello without a tunnel
// token is refused before the comparison runs. An empty configured token compared
// against an empty presented token would match, so a deployment that forgot to set
// the variable would accept every Node.
func TestHelloValidateRejectsEmptyTunnelToken(t *testing.T) {
	hello := Hello{
		Version: Version,
		NodeID:  "node_0123456789abcdefghijklmnop",
	}

	if err := hello.Validate(); err == nil {
		t.Fatal("expected an error for an empty tunnel token")
	}
}

// TestHelloRoundTripKeepsTunnelToken checks that the tunnel token survives JSON
// encoding, because it travels as a field of the hello frame and nowhere else.
func TestHelloRoundTripKeepsTunnelToken(t *testing.T) {
	original := Hello{
		Version:     Version,
		NodeID:      "node_0123456789abcdefghijklmnop",
		TunnelToken: []byte("tunnel-token-value"),
	}

	encoded, err := json.Marshal(original)
	if err != nil {
		t.Fatalf("marshal hello: %v", err)
	}

	var decoded Hello
	if err := json.Unmarshal(encoded, &decoded); err != nil {
		t.Fatalf("unmarshal hello: %v", err)
	}

	if string(decoded.TunnelToken) != string(original.TunnelToken) {
		t.Fatalf("tunnel token = %q, want %q", decoded.TunnelToken, original.TunnelToken)
	}
	if decoded.NodeID != original.NodeID {
		t.Fatalf("node id = %q, want %q", decoded.NodeID, original.NodeID)
	}
}

// TestHelloConfirmRoundTrip checks that the confirmation survives JSON encoding,
// so the Node can read the generation the Server assigned.
func TestHelloConfirmRoundTrip(t *testing.T) {
	original := HelloConfirm{Version: Version, Generation: 7}

	encoded, err := json.Marshal(original)
	if err != nil {
		t.Fatalf("marshal hello confirm: %v", err)
	}

	var decoded HelloConfirm
	if err := json.Unmarshal(encoded, &decoded); err != nil {
		t.Fatalf("unmarshal hello confirm: %v", err)
	}

	if decoded.Generation != original.Generation {
		t.Fatalf("generation = %d, want %d", decoded.Generation, original.Generation)
	}
	if decoded.Version != original.Version {
		t.Fatalf("version = %q, want %q", decoded.Version, original.Version)
	}
}
