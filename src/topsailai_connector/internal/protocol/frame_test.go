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
