package server

import (
	"bytes"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strconv"
	"testing"

	"topsailai_connector/internal/protocol"
	"topsailai_connector/internal/security"
)

// contentResponse builds the answer a Node sends on the content transport: the
// metadata in Data and the raw bytes in Content.
func contentResponse(t *testing.T, content []byte, truncated bool) protocol.Response {
	t.Helper()
	metadata, err := json.Marshal(readMetadata{Size: int64(len(content)), Truncated: truncated})
	if err != nil {
		t.Fatalf("marshal metadata: %v", err)
	}
	return protocol.Response{Code: protocol.CodeSuccess, Data: metadata, Content: content}
}

// serveWithAccept runs one signed request with an Accept header.
func serveWithAccept(t *testing.T, fixture *fixture, accept string) *httptest.ResponseRecorder {
	t.Helper()
	request := signedRequest(t, testNodeID, validBody)
	if accept != "" {
		request.Header.Set("Accept", accept)
	}
	return serve(fixture.handler, request)
}

// TestHandlerKeepsTheLegacyShapeWithoutTheOptIn proves a caller that does not ask
// for bytes still receives the documented JSON envelope.
//
// The CLI sends no Accept header today, so this is the path every existing caller
// takes. If the opt-in leaked into it, the CLI would try to parse a file as JSON.
//
// The assertion is on the base64 form of the content, because that is what the
// legacy contract promises: one object with a base64 content field. A test that
// only checked the code would pass even if the shape had changed.
func TestHandlerKeepsTheLegacyShapeWithoutTheOptIn(t *testing.T) {
	fixture := newFixture(t, true)
	content := []byte("hello, connector")
	fixture.forwarder.response = contentResponse(t, content, false)

	recorder := serveWithAccept(t, fixture, "")

	if recorder.Code != http.StatusOK {
		t.Fatalf("status = %d, want 200", recorder.Code)
	}
	if contentType := recorder.Header().Get("Content-Type"); contentType != "application/json" {
		t.Fatalf("content type = %q, want application/json", contentType)
	}

	body := decodeEnvelope(t, recorder)
	if body.Code != protocol.CodeSuccess {
		t.Fatalf("code = %v, want success", body.Code)
	}

	// The data field must be the merged document, byte for byte. mergeReadContent is
	// the function that defines the legacy shape, so comparing against its output is
	// comparing against the contract rather than against a copy of it.
	expected, err := mergeReadContent(fixture.forwarder.response.Data, content)
	if err != nil {
		t.Fatalf("mergeReadContent: %v", err)
	}
	if !bytes.Equal(body.Data, expected) {
		t.Fatalf("data = %s, want %s", body.Data, expected)
	}
	if !bytes.Contains(recorder.Body.Bytes(), []byte("aGVsbG8sIGNvbm5lY3Rvcg==")) {
		t.Fatalf("legacy body does not carry the base64 content: %s", recorder.Body.String())
	}
}

// TestHandlerStreamsRawContentOnTheOptIn proves the opt-in path carries the exact
// bytes and no encoding.
//
// This is the property that removes the 1.3371 ratio: the body is the file, so the
// Server never base64-encodes it. The test asserts the body byte for byte and also
// asserts the base64 form is absent, because a body that happened to equal the file
// while also containing an encoded copy would still be paying the cost.
func TestHandlerStreamsRawContentOnTheOptIn(t *testing.T) {
	fixture := newFixture(t, true)
	content := []byte("hello, connector")
	fixture.forwarder.response = contentResponse(t, content, false)

	recorder := serveWithAccept(t, fixture, rawContentMediaType)

	if recorder.Code != http.StatusOK {
		t.Fatalf("status = %d, want 200", recorder.Code)
	}
	if contentType := recorder.Header().Get("Content-Type"); contentType != rawContentMediaType {
		t.Fatalf("content type = %q, want %q", contentType, rawContentMediaType)
	}
	if !bytes.Equal(recorder.Body.Bytes(), content) {
		t.Fatalf("body = %q, want %q", recorder.Body.Bytes(), content)
	}
	if bytes.Contains(recorder.Body.Bytes(), []byte("aGVsbG8sIGNvbm5lY3Rvcg==")) {
		t.Fatalf("body carries base64 content: %q", recorder.Body.Bytes())
	}
	if bytes.Contains(recorder.Body.Bytes(), []byte(`"content"`)) {
		t.Fatalf("body carries a JSON envelope: %q", recorder.Body.Bytes())
	}
}

// TestHandlerSetsContentLengthOnTheOptIn proves a truncated write is detectable.
//
// Without an explicit length the client cannot tell a short body from a complete
// one, and a short body is exactly the failure the size check exists to prevent.
func TestHandlerSetsContentLengthOnTheOptIn(t *testing.T) {
	fixture := newFixture(t, true)
	content := []byte("0123456789")
	fixture.forwarder.response = contentResponse(t, content, false)

	recorder := serveWithAccept(t, fixture, rawContentMediaType)

	declared := recorder.Header().Get("Content-Length")
	if declared != strconv.Itoa(len(content)) {
		t.Fatalf("content length = %q, want %d", declared, len(content))
	}
	if recorder.Body.Len() != len(content) {
		t.Fatalf("body is %d bytes, want %d", recorder.Body.Len(), len(content))
	}
}

// TestHandlerReportsTruncationOnTheOptIn proves the flag survives the raw shape.
//
// A truncated read is a successful read of a prefix, so the caller must be able to
// tell it from a complete file. The body cannot carry the flag, so it travels in a
// header.
func TestHandlerReportsTruncationOnTheOptIn(t *testing.T) {
	fixture := newFixture(t, true)
	fixture.forwarder.response = contentResponse(t, []byte("prefix"), true)

	recorder := serveWithAccept(t, fixture, rawContentMediaType)

	if got := recorder.Header().Get("X-Connector-Truncated"); got != "true" {
		t.Fatalf("truncated header = %q, want true", got)
	}
}

// TestHandlerRefusesToStreamARefusal proves a refusal never becomes an empty body.
//
// An empty octet stream with status 200 reads as a successful read of an empty
// file, which is the one confusion a caller cannot detect. A refusal therefore keeps
// the envelope, where the code is visible.
func TestHandlerRefusesToStreamARefusal(t *testing.T) {
	cases := []struct {
		name string
		code protocol.Code
	}{
		{"denied", protocol.CodeDenied},
		{"not found", protocol.CodeNotFound},
		{"internal", protocol.CodeInternal},
		{"too large", protocol.CodeTooLarge},
	}

	for _, testCase := range cases {
		fixture := newFixture(t, true)
		// The content is present on purpose: a refusal that arrives with bytes must
		// still not publish them.
		fixture.forwarder.response = protocol.Response{
			Code:    testCase.code,
			Content: []byte("must not appear"),
		}

		recorder := serveWithAccept(t, fixture, rawContentMediaType)

		if contentType := recorder.Header().Get("Content-Type"); contentType != "application/json" {
			t.Fatalf("%s: content type = %q, want application/json", testCase.name, contentType)
		}
		body := decodeEnvelope(t, recorder)
		if body.Code != testCase.code {
			t.Fatalf("%s: code = %v, want %v", testCase.name, body.Code, testCase.code)
		}
		if bytes.Contains(recorder.Body.Bytes(), []byte("must not appear")) {
			t.Fatalf("%s: refusal published the content: %s", testCase.name, recorder.Body.String())
		}
	}
}

// TestHandlerKeepsTheEnvelopeWhenTheJSONTransportAnswered proves the opt-in does
// not break a Node that negotiated no content transport.
//
// Such a Node sends the whole read result as JSON, so there are no raw bytes to
// stream. The envelope is the only correct answer, and it must still be the
// documented shape.
func TestHandlerKeepsTheEnvelopeWhenTheJSONTransportAnswered(t *testing.T) {
	fixture := newFixture(t, true)
	fixture.forwarder.response = protocol.Success([]byte(`{"content":"aGk=","size":2,"truncated":false}`))

	recorder := serveWithAccept(t, fixture, rawContentMediaType)

	if contentType := recorder.Header().Get("Content-Type"); contentType != "application/json" {
		t.Fatalf("content type = %q, want application/json", contentType)
	}
	body := decodeEnvelope(t, recorder)
	if body.Code != protocol.CodeSuccess {
		t.Fatalf("code = %v, want success", body.Code)
	}
	if !bytes.Equal(body.Data, fixture.forwarder.response.Data) {
		t.Fatalf("data = %s, want %s", body.Data, fixture.forwarder.response.Data)
	}
}

// TestWantsRawContentParsesTheHeader proves the opt-in is recognised in the forms a
// real client sends.
//
// A whole-string comparison would refuse a header carrying several types or a
// quality parameter, which is the same request written differently.
func TestWantsRawContentParsesTheHeader(t *testing.T) {
	cases := []struct {
		name   string
		header []string
		want   bool
	}{
		{"absent", nil, false},
		{"exact", []string{rawContentMediaType}, true},
		{"with a parameter", []string{rawContentMediaType + "; q=1"}, true},
		{"second in a list", []string{"application/json, " + rawContentMediaType}, true},
		{"separate header lines", []string{"application/json", rawContentMediaType}, true},
		{"upper case", []string{"Application/Octet-Stream"}, true},
		{"json only", []string{"application/json"}, false},
		{"wildcard only", []string{"*/*"}, false},
		{"empty", []string{""}, false},
	}

	for _, testCase := range cases {
		request, err := http.NewRequest(http.MethodPost, "/", nil)
		if err != nil {
			t.Fatalf("%s: NewRequest: %v", testCase.name, err)
		}
		for _, value := range testCase.header {
			request.Header.Add("Accept", value)
		}
		if got := wantsRawContent(request); got != testCase.want {
			t.Fatalf("%s: wantsRawContent = %v, want %v", testCase.name, got, testCase.want)
		}
	}
}

// TestHandlerEchoesTheRequestIDOnTheOptIn proves the raw response is traceable.
//
// The envelope carries the request id, so the raw shape must carry it too, or a
// caller that logs one and not the other cannot correlate the two.
func TestHandlerEchoesTheRequestIDOnTheOptIn(t *testing.T) {
	fixture := newFixture(t, true)
	fixture.forwarder.response = contentResponse(t, []byte("bytes"), false)

	request := signedRequest(t, testNodeID, validBody)
	request.Header.Set("Accept", rawContentMediaType)
	requestID := request.Header.Get(security.RequestIDHeader)

	recorder := serve(fixture.handler, request)

	if got := recorder.Header().Get(security.RequestIDHeader); got != requestID {
		t.Fatalf("request id header = %q, want %q", got, requestID)
	}
}

// TestOptInBodyCarriesNoEncodingOverhead measures the encoding cost of each shape.
//
// This is the deterministic half of the wire-ratio evidence. `make measure` drives
// the CLI, and the CLI sends no Accept header, so that harness can only observe the
// legacy shape until Unit 4b moves the CLI. A measurement that depends on which
// client happens to be installed is not a measurement of this unit.
//
// The quantity measured here is the encoding overhead alone: the number of response
// body bytes per content byte. It is independent of host load, of the transport, and
// of the number of round trips, so it answers exactly one question — did the Server
// stop base64-encoding the file on the caller-facing hop.
//
// The expected values are arithmetic rather than empirical. Base64 expands by 4/3,
// so a legacy body carrying N content bytes cannot be smaller than 1.3333 N. The
// opt-in body is the file, so it is exactly N. A tolerance is applied to the legacy
// lower bound only, because the envelope adds a fixed number of bytes on top.
func TestOptInBodyCarriesNoEncodingOverhead(t *testing.T) {
	// 64 KiB is large enough that the fixed envelope overhead is negligible against
	// the content, so the ratio reflects the encoding rather than the JSON keys.
	content := bytes.Repeat([]byte("connector"), 64*1024/len("connector"))

	fixture := newFixture(t, true)
	fixture.forwarder.response = contentResponse(t, content, false)

	rawRecorder := serveWithAccept(t, fixture, rawContentMediaType)
	legacyRecorder := serveWithAccept(t, fixture, "")

	rawBytes := rawRecorder.Body.Len()
	legacyBytes := legacyRecorder.Body.Len()

	// The opt-in body is the file and nothing else, so the ratio is exactly 1.
	if rawBytes != len(content) {
		t.Fatalf("opt-in body = %d bytes for %d content bytes, want exactly %d",
			rawBytes, len(content), len(content))
	}
	rawRatio := float64(rawBytes) / float64(len(content))
	if rawRatio != 1.0 {
		t.Fatalf("opt-in ratio = %.4f, want 1.0000", rawRatio)
	}

	// The legacy body must still pay base64, which is the cost this unit removed from
	// the opt-in path. Asserting the lower bound proves the two shapes really differ;
	// a test that only checked the opt-in path would pass even if the legacy path had
	// silently stopped encoding, which would be a contract break rather than a win.
	legacyRatio := float64(legacyBytes) / float64(len(content))
	if legacyRatio < 4.0/3.0 {
		t.Fatalf("legacy ratio = %.4f, want at least %.4f (base64)", legacyRatio, 4.0/3.0)
	}

	t.Logf("content=%d opt-in_body=%d opt-in_ratio=%.4f legacy_body=%d legacy_ratio=%.4f",
		len(content), rawBytes, rawRatio, legacyBytes, legacyRatio)
}
