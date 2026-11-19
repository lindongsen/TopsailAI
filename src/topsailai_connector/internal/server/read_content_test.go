package server

import (
	"bytes"
	"encoding/json"
	"log/slog"
	"testing"

	"topsailai_connector/internal/protocol"
)

// newContentTestChannel builds a channel with no connection.
//
// The content plumbing is exercised without a socket on purpose: the buffering,
// the merge and the drop-on-timeout behaviour are decisions about maps and bytes,
// and a socket would add timing without adding coverage. The socket path is
// covered by the listener tests.
func newContentTestChannel() *channel {
	return newChannel("node_test", nil, slog.New(slog.DiscardHandler))
}

// TestStashAndTakeContentRoundTrips proves the bytes survive the buffer.
func TestStashAndTakeContentRoundTrips(t *testing.T) {
	c := newContentTestChannel()
	if _, err := c.addPending("req_1"); err != nil {
		t.Fatalf("addPending: %v", err)
	}
	payload := []byte("raw file bytes, not base64")

	c.stashContent("req_1", payload)

	got, ok := c.takeContent("req_1")
	if !ok {
		t.Fatal("takeContent reported no content for a request that stashed some")
	}
	if string(got) != string(payload) {
		t.Fatalf("content = %q, want %q", got, payload)
	}
}

// TestTakeContentForgetsTheBytes proves a second take finds nothing.
//
// The buffer must not be readable twice: a retry re-reads the bytes from the Node
// rather than replaying a stored copy, which is the same rule the proofs follow.
func TestTakeContentForgetsTheBytes(t *testing.T) {
	c := newContentTestChannel()
	if _, err := c.addPending("req_1"); err != nil {
		t.Fatalf("addPending: %v", err)
	}
	c.stashContent("req_1", []byte("once"))

	if _, ok := c.takeContent("req_1"); !ok {
		t.Fatal("first take reported no content")
	}
	if _, ok := c.takeContent("req_1"); ok {
		t.Fatal("second take returned content, so the buffer was not released")
	}
}

// TestStashContentWithoutAWaiterIsDropped proves unsolicited bytes are refused.
//
// A content frame for a request nobody is waiting on is either a late answer to a
// timed-out request or a peer allocating on the Server's behalf. Both are dropped,
// and the drop is what keeps the buffer bounded by the number of live requests.
func TestStashContentWithoutAWaiterIsDropped(t *testing.T) {
	c := newContentTestChannel()

	c.stashContent("req_absent", []byte("unsolicited"))

	if _, ok := c.takeContent("req_absent"); ok {
		t.Fatal("content was buffered for a request with no waiter")
	}
}

// TestRemovePendingDropsBufferedContent proves a timeout leaves nothing behind.
//
// The waiter is removed when the request ends, whether it was answered or
// abandoned. If the content outlived the waiter, a timed-out read would hold its
// bytes until the channel closed.
func TestRemovePendingDropsBufferedContent(t *testing.T) {
	c := newContentTestChannel()
	if _, err := c.addPending("req_1"); err != nil {
		t.Fatalf("addPending: %v", err)
	}
	c.stashContent("req_1", []byte("abandoned"))

	c.removePending("req_1")

	if _, ok := c.takeContent("req_1"); ok {
		t.Fatal("content survived the waiter it belonged to")
	}
}

// TestAttachContentKeepsTheBytesRaw proves the Server no longer base64-encodes the
// content on the way to the caller.
//
// This is the property the unit exists for. The earlier version merged the bytes
// into a JSON object here, which base64-encoded them and made the Server-to-caller
// hop 1.3371 bytes per content byte. The bytes must now stay raw in Content, and the
// metadata must stay in Data, so the HTTP layer can choose the shape.
//
// The assertion is on the raw bytes rather than on a decoded field, because a test
// that decoded a JSON object would pass whether or not the encoding happened.
func TestAttachContentKeepsTheBytesRaw(t *testing.T) {
	c := newContentTestChannel()
	if _, err := c.addPending("req_1"); err != nil {
		t.Fatalf("addPending: %v", err)
	}
	content := []byte("hello, connector")
	metadata, err := json.Marshal(readMetadata{Size: int64(len(content)), Truncated: true})
	if err != nil {
		t.Fatalf("marshal metadata: %v", err)
	}
	c.stashContent("req_1", content)

	got := c.attachContent("req_1", protocol.Response{Code: protocol.CodeSuccess, Data: metadata})

	if got.Code != protocol.CodeSuccess {
		t.Fatalf("code = %v, want success", got.Code)
	}
	if !bytes.Equal(got.Content, content) {
		t.Fatalf("content = %q, want %q", got.Content, content)
	}
	if !bytes.Equal(got.Data, metadata) {
		t.Fatalf("data = %s, want the metadata unchanged %s", got.Data, metadata)
	}
	// The metadata must not have been replaced by a merged document. A merged
	// document would contain the base64 of the content, so its presence is the
	// defect stated positively.
	if bytes.Contains(got.Data, []byte("aGVsbG8sIGNvbm5lY3Rvcg==")) {
		t.Fatalf("data carries base64 content: %s", got.Data)
	}
}

// TestResponseContentIsNotSerialised proves the raw bytes cannot leak into JSON.
//
// Response.Content is excluded from the JSON representation, so no code path can
// accidentally base64 it into a frame or an envelope. Without the exclusion, a
// response carrying content would be encoded twice: once by the field's own
// encoding and once by whatever wraps it.
func TestResponseContentIsNotSerialised(t *testing.T) {
	encoded, err := json.Marshal(protocol.Response{
		Code:    protocol.CodeSuccess,
		Data:    []byte(`{"size":2}`),
		Content: []byte("raw bytes"),
	})
	if err != nil {
		t.Fatalf("marshal response: %v", err)
	}
	if bytes.Contains(encoded, []byte("raw bytes")) {
		t.Fatalf("encoded response carries the raw content: %s", encoded)
	}
	if bytes.Contains(encoded, []byte("cmF3IGJ5dGVz")) {
		t.Fatalf("encoded response carries the base64 content: %s", encoded)
	}
	if !bytes.Contains(encoded, []byte(`"data"`)) {
		t.Fatalf("encoded response lost its data field: %s", encoded)
	}
}

// TestAttachContentLeavesARefusalUntouched proves a refusal gains no content.
//
// A refusal that acquired an empty content field would read as a success with an
// empty file, which is the one confusion a caller cannot detect.
func TestAttachContentLeavesARefusalUntouched(t *testing.T) {
	c := newContentTestChannel()
	c.stashContent("req_1", []byte("should not appear"))

	response := protocol.Response{Code: protocol.CodeDenied}
	got := c.attachContent("req_1", response)

	if got.Code != protocol.CodeDenied {
		t.Fatalf("code = %v, want denied", got.Code)
	}
	if len(got.Data) != 0 {
		t.Fatalf("data = %q, want empty", got.Data)
	}
}

// TestAttachContentRefusesASizeMismatch proves a short file is not published.
//
// A caller that receives fewer bytes than the metadata promised has no way to
// notice, so the disagreement is refused here where both halves are still known.
func TestAttachContentRefusesASizeMismatch(t *testing.T) {
	c := newContentTestChannel()
	if _, err := c.addPending("req_1"); err != nil {
		t.Fatalf("addPending: %v", err)
	}
	metadata, err := json.Marshal(readMetadata{Size: 100})
	if err != nil {
		t.Fatalf("marshal metadata: %v", err)
	}
	c.stashContent("req_1", []byte("short"))

	got := c.attachContent("req_1", protocol.Response{Code: protocol.CodeSuccess, Data: metadata})

	if got.Code != protocol.CodeInternal {
		t.Fatalf("code = %v, want internal", got.Code)
	}
	if len(got.Data) != 0 {
		t.Fatalf("data = %q, want empty", got.Data)
	}
}

// TestAttachContentWithoutContentLeavesTheResponseAlone proves the JSON transport
// still works.
//
// A Node that negotiated no content transport sends the whole read result in JSON,
// so there is nothing to merge and the response must pass through unchanged.
func TestAttachContentWithoutContentLeavesTheResponseAlone(t *testing.T) {
	c := newContentTestChannel()
	original := []byte(`{"content":"aGk=","size":2,"truncated":false}`)

	got := c.attachContent("req_1", protocol.Response{Code: protocol.CodeSuccess, Data: original})

	if string(got.Data) != string(original) {
		t.Fatalf("data = %q, want %q", got.Data, original)
	}
}

// TestHandleContentFrameBuffersTheBytes proves a binary frame reaches the buffer.
func TestHandleContentFrameBuffersTheBytes(t *testing.T) {
	c := newContentTestChannel()
	if _, err := c.addPending("req_1"); err != nil {
		t.Fatalf("addPending: %v", err)
	}
	content := []byte("frame bytes")
	frame, err := protocol.EncodeContentFrame(protocol.ContentHeader{
		RequestID:     "req_1",
		Size:          int64(len(content)),
		ContentLength: int64(len(content)),
	}, content)
	if err != nil {
		t.Fatalf("encode content frame: %v", err)
	}

	if !c.handleContentFrame(frame) {
		t.Fatal("handleContentFrame closed the channel for a valid frame")
	}

	got, ok := c.takeContent("req_1")
	if !ok {
		t.Fatal("content was not buffered")
	}
	if string(got) != string(content) {
		t.Fatalf("content = %q, want %q", got, content)
	}
}

// TestHandleContentFrameRefusesAMalformedFrame proves a bad frame closes the
// channel instead of being skipped.
//
// Skipping would leave the request waiting for content that will never arrive, so
// the caller would see a timeout instead of the protocol violation that caused it.
func TestHandleContentFrameRefusesAMalformedFrame(t *testing.T) {
	c := newContentTestChannel()

	if c.handleContentFrame([]byte("not a content frame")) {
		t.Fatal("handleContentFrame accepted a malformed frame")
	}
}

// TestNegotiateChannelTransportKeepsLegacyNodesWorking proves an absent capability
// list means the JSON transport.
//
// An older Node sends no list at all. Refusing it would break every deployment that
// upgrades the Server first, which is the normal order.
func TestNegotiateChannelTransportKeepsLegacyNodesWorking(t *testing.T) {
	transport, err := negotiateChannelTransport(nil)
	if err != nil {
		t.Fatalf("negotiateChannelTransport: %v", err)
	}
	if transport != "" {
		t.Fatalf("transport = %q, want the empty JSON transport", transport)
	}
}

// TestNegotiateChannelTransportSelectsBinaryV1 proves a capable Node gets the
// content transport.
func TestNegotiateChannelTransportSelectsBinaryV1(t *testing.T) {
	transport, err := negotiateChannelTransport([]protocol.FileTransportVersion{protocol.FileTransportBinaryV1})
	if err != nil {
		t.Fatalf("negotiateChannelTransport: %v", err)
	}
	if transport != protocol.FileTransportBinaryV1 {
		t.Fatalf("transport = %q, want %q", transport, protocol.FileTransportBinaryV1)
	}
}

// TestNegotiateChannelTransportRefusesNoCommonVersion proves a Node that offers
// only an unknown version is refused rather than silently downgraded.
//
// A downgrade would hide an upgrade mistake behind a channel that works but is
// slow, and the operator would never learn that the new transport is unused.
func TestNegotiateChannelTransportRefusesNoCommonVersion(t *testing.T) {
	_, err := negotiateChannelTransport([]protocol.FileTransportVersion{"binary-v99"})
	if err == nil {
		t.Fatal("negotiateChannelTransport accepted a version the Server does not support")
	}
}

// TestTransportNameNamesTheLegacyTransport proves the log line is readable.
func TestTransportNameNamesTheLegacyTransport(t *testing.T) {
	if got := transportName(""); got != "json" {
		t.Fatalf("transportName(\"\") = %q, want json", got)
	}
	if got := transportName(protocol.FileTransportBinaryV1); got != "binary-v1" {
		t.Fatalf("transportName(binary-v1) = %q, want binary-v1", got)
	}
}
