package node

import (
	"bytes"
	"encoding/json"
	"testing"

	"topsailai_connector/internal/protocol"
)

// TestDispatchWithContentReturnsRawBytes checks that the content path returns the
// file bytes unchanged and never base64-encodes them.
//
// The property under test is the reason the entry point exists: a byte slice in a
// JSON document is base64, so a content path that returned a JSON payload would
// have re-introduced the expansion this transport removes.
func TestDispatchWithContentReturnsRawBytes(t *testing.T) {
	fixture := newDispatchFixture(t)

	response, content, header, err := fixture.dispatcher.DispatchWithContent(
		fixture.request(protocol.OperationFileRead, "project", "inside.txt"))
	if err != nil {
		t.Fatalf("DispatchWithContent() error = %v, want nil", err)
	}
	if !response.Succeeded() {
		t.Fatalf("DispatchWithContent() code = %s, want success", response.Code.Name())
	}
	if string(content) != "inside content" {
		t.Fatalf("content = %q, want %q", content, "inside content")
	}
	if bytes.Contains(content, []byte("aW5zaWRlIGNvbnRlbnQ=")) {
		t.Fatalf("content = %q, want raw bytes rather than base64", content)
	}
	if header.ContentLength != int64(len(content)) {
		t.Fatalf("header content length = %d, want %d", header.ContentLength, len(content))
	}
	if header.Size != int64(len(content)) {
		t.Fatalf("header size = %d, want %d", header.Size, len(content))
	}
	if header.Truncated {
		t.Fatalf("header truncated = true, want false")
	}
}

// TestDispatchWithContentMetadataOmitsContent checks that the metadata document
// carries the size and the truncation flag and no content field.
//
// A caller that receives content must read the metadata for the counters, so a
// metadata document that still carried a content field would be a second, empty
// copy of the bytes and a caller could not tell which one to trust.
func TestDispatchWithContentMetadataOmitsContent(t *testing.T) {
	fixture := newDispatchFixture(t)

	response, _, _, err := fixture.dispatcher.DispatchWithContent(
		fixture.request(protocol.OperationFileRead, "project", "inside.txt"))
	if err != nil {
		t.Fatalf("DispatchWithContent() error = %v, want nil", err)
	}

	var metadata map[string]any
	if err := json.Unmarshal(response.Data, &metadata); err != nil {
		t.Fatalf("unmarshal metadata: %v", err)
	}
	if _, present := metadata["content"]; present {
		t.Fatalf("metadata = %s, want no content field", response.Data)
	}
	if metadata["size"] != float64(len("inside content")) {
		t.Fatalf("metadata size = %v, want %d", metadata["size"], len("inside content"))
	}
	if metadata["truncated"] != false {
		t.Fatalf("metadata truncated = %v, want false", metadata["truncated"])
	}
}

// TestDispatchWithContentLeavesTheCorrelationIDToTheSession checks that the
// dispatcher does not stamp a correlation id on the content header.
//
// The receiver buffers content under the wire request id it generated for the
// forwarded frame, which is a different namespace from the caller's request id.
// Only the session knows the wire id, so the dispatcher must leave the field empty
// and let the session fill it. The earlier version stamped the caller's id here,
// and the receiver dropped every content frame as "content for a request with no
// waiter" while still answering success, so the caller received an empty file.
func TestDispatchWithContentLeavesTheCorrelationIDToTheSession(t *testing.T) {
	fixture := newDispatchFixture(t)

	request := fixture.request(protocol.OperationFileRead, "project", "inside.txt")
	_, content, header, err := fixture.dispatcher.DispatchWithContent(request)
	if err != nil {
		t.Fatalf("DispatchWithContent() error = %v, want nil", err)
	}
	if len(content) == 0 {
		t.Fatal("DispatchWithContent() returned no content, want the file bytes")
	}
	if header.RequestID != "" {
		t.Fatalf("header request id = %q, want empty so the session can stamp the wire id", header.RequestID)
	}
}

// TestDispatchWithContentAgreesWithDispatch checks that both entry points return
// the same bytes for the same request.
//
// The two paths share one authorization preamble, and this test is what proves the
// sharing holds for the payload as well: a content path that read a different range
// would answer a different question than the documented one.
func TestDispatchWithContentAgreesWithDispatch(t *testing.T) {
	fixture := newDispatchFixture(t)

	jsonResponse := fixture.dispatcher.Dispatch(
		fixture.request(protocol.OperationFileRead, "project", "inside.txt"))
	if !jsonResponse.Succeeded() {
		t.Fatalf("Dispatch() code = %s, want success", jsonResponse.Code.Name())
	}
	var documented struct {
		Content   []byte `json:"content"`
		Size      int64  `json:"size"`
		Truncated bool   `json:"truncated"`
	}
	if err := json.Unmarshal(jsonResponse.Data, &documented); err != nil {
		t.Fatalf("unmarshal documented payload: %v", err)
	}

	contentResponse, content, header, err := fixture.dispatcher.DispatchWithContent(
		fixture.request(protocol.OperationFileRead, "project", "inside.txt"))
	if err != nil {
		t.Fatalf("DispatchWithContent() error = %v, want nil", err)
	}
	if !contentResponse.Succeeded() {
		t.Fatalf("DispatchWithContent() code = %s, want success", contentResponse.Code.Name())
	}

	if !bytes.Equal(content, documented.Content) {
		t.Fatalf("content = %q, want %q", content, documented.Content)
	}
	if header.Size != documented.Size {
		t.Fatalf("header size = %d, want %d", header.Size, documented.Size)
	}
	if header.Truncated != documented.Truncated {
		t.Fatalf("header truncated = %v, want %v", header.Truncated, documented.Truncated)
	}
}

// TestDispatchWithContentReturnsNoContentForOtherOperations checks that a
// non-read operation keeps its documented JSON payload and reports no content.
//
// A caller routes on the content being empty, so a list or a stat that returned
// bytes here would be indistinguishable from a read of a file that happened to
// contain that JSON.
func TestDispatchWithContentReturnsNoContentForOtherOperations(t *testing.T) {
	fixture := newDispatchFixture(t)

	response, content, header, err := fixture.dispatcher.DispatchWithContent(
		fixture.request(protocol.OperationFileList, "project", ""))
	if err != nil {
		t.Fatalf("DispatchWithContent() error = %v, want nil", err)
	}
	if !response.Succeeded() {
		t.Fatalf("DispatchWithContent() code = %s, want success", response.Code.Name())
	}
	if len(content) != 0 {
		t.Fatalf("content = %q, want no content for file.list", content)
	}
	if header != (protocol.ContentHeader{}) {
		t.Fatalf("header = %+v, want the zero header for file.list", header)
	}

	var payload struct {
		Entries []Entry `json:"entries"`
	}
	if err := json.Unmarshal(response.Data, &payload); err != nil {
		t.Fatalf("unmarshal list payload: %v", err)
	}
	if len(payload.Entries) == 0 {
		t.Fatalf("entries = 0, want the documented list payload")
	}
}

// TestDispatchWithContentRefusalCarriesNoContent checks that a refused request
// returns the refusal and no bytes.
//
// A refusal that carried content would publish file bytes for a request the Node
// decided not to serve, which is the one outcome the fence exists to prevent.
func TestDispatchWithContentRefusalCarriesNoContent(t *testing.T) {
	fixture := newDispatchFixture(t)

	response, content, header, err := fixture.dispatcher.DispatchWithContent(
		fixture.request(protocol.OperationFileRead, "scratch", "inside.txt"))
	if err != nil {
		t.Fatalf("DispatchWithContent() error = %v, want nil", err)
	}
	if response.Succeeded() {
		t.Fatalf("DispatchWithContent() code = %s, want a refusal", response.Code.Name())
	}
	if response.Code != protocol.CodeDenied {
		t.Fatalf("DispatchWithContent() code = %s, want %s", response.Code.Name(), protocol.CodeDenied.Name())
	}
	if len(content) != 0 {
		t.Fatalf("content = %q, want no content on a refusal", content)
	}
	if header != (protocol.ContentHeader{}) {
		t.Fatalf("header = %+v, want the zero header on a refusal", header)
	}
}

// TestDispatchWithContentRefusesAForgedProof checks that the content path runs the
// same proof verification as the JSON path.
//
// The two entry points share one preamble, and this test is what proves the sharing
// is real rather than a copy that happens to agree today.
func TestDispatchWithContentRefusesAForgedProof(t *testing.T) {
	fixture := newDispatchFixture(t)

	request := fixture.request(protocol.OperationFileRead, "project", "inside.txt")
	request.NodeAuth.Signature = "AAAA"

	response, content, _, err := fixture.dispatcher.DispatchWithContent(request)
	if err != nil {
		t.Fatalf("DispatchWithContent() error = %v, want nil", err)
	}
	if response.Code != protocol.CodeUnauthenticated {
		t.Fatalf("DispatchWithContent() code = %s, want %s", response.Code.Name(), protocol.CodeUnauthenticated.Name())
	}
	if len(content) != 0 {
		t.Fatalf("content = %q, want no content for a forged proof", content)
	}
}

// TestDispatchWithContentNilDispatcher checks that a nil dispatcher is refused
// rather than panicking.
//
// A request arrives from the network, so a panic here would be a remote crash.
func TestDispatchWithContentNilDispatcher(t *testing.T) {
	var dispatcher *Dispatcher

	response, content, _, err := dispatcher.DispatchWithContent(protocol.Request{})
	if err != nil {
		t.Fatalf("DispatchWithContent() error = %v, want nil", err)
	}
	if response.Code != protocol.CodeInternal {
		t.Fatalf("DispatchWithContent() code = %s, want %s", response.Code.Name(), protocol.CodeInternal.Name())
	}
	if len(content) != 0 {
		t.Fatalf("content = %q, want no content", content)
	}
}
