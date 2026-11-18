package server

import (
	"bytes"
	"context"
	"encoding/json"
	"log/slog"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync"
	"testing"
	"time"

	"topsailai_connector/internal/protocol"
	"topsailai_connector/internal/security"
)

const (
	// testNodeID is a well formed node id.
	testNodeID = "node_0123456789abcdefghijklmnop"
)

// fakeForwarder records every request it receives and returns a configured
// answer, so a test can assert both what the Server relayed and what it answered.
type fakeForwarder struct {
	mutex    sync.Mutex
	requests []protocol.Request
	response protocol.Response
	err      error
	delay    time.Duration
}

// Forward records the request and returns the configured answer.
func (f *fakeForwarder) Forward(ctx context.Context, nodeID string, request protocol.Request) (protocol.Response, error) {
	f.mutex.Lock()
	f.requests = append(f.requests, request)
	f.mutex.Unlock()

	if f.delay > 0 {
		select {
		case <-time.After(f.delay):
		case <-ctx.Done():
			return protocol.Response{}, ctx.Err()
		}
	}
	if f.err != nil {
		return protocol.Response{}, f.err
	}
	return f.response, nil
}

// last returns the most recent request and whether one was recorded.
func (f *fakeForwarder) last() (protocol.Request, bool) {
	f.mutex.Lock()
	defer f.mutex.Unlock()
	if len(f.requests) == 0 {
		return protocol.Request{}, false
	}
	return f.requests[len(f.requests)-1], true
}

// count reports how many requests were forwarded.
func (f *fakeForwarder) count() int {
	f.mutex.Lock()
	defer f.mutex.Unlock()
	return len(f.requests)
}

// fixture is one wired handler plus the parts a test inspects.
type fixture struct {
	handler   *Handler
	registry  *Registry
	forwarder *fakeForwarder
	logs      *bytes.Buffer
}

// testConfig is a valid configuration with a short timeout.
func testConfig(t *testing.T) Config {
	t.Helper()
	return Config{
		Listen:            DefaultListenAddress,
		TunnelToken:       security.Secret("tunnel-token-0123456789"),
		ClientCredentials: testCredentialSet(t),
		ReplayWindow:      security.DefaultReplayWindow,
		ReplayCapacity:    security.DefaultReplayCapacity,
		RequestTimeout:    5 * time.Second,
	}
}

// newFixture builds a handler whose log output is captured in memory.
func newFixture(t *testing.T, register bool) *fixture {
	t.Helper()

	logs := &bytes.Buffer{}
	logger := slog.New(slog.NewJSONHandler(logs, &slog.HandlerOptions{Level: slog.LevelDebug}))

	registry := NewRegistry()
	if register {
		if _, _, err := registry.Register(&fakeChannel{nodeID: testNodeID}); err != nil {
			t.Fatalf("Register: %v", err)
		}
	}

	forwarder := &fakeForwarder{response: protocol.Success([]byte(`{"ok":true}`))}
	handler, err := NewHandler(testConfig(t), registry, forwarder, logger)
	if err != nil {
		t.Fatalf("NewHandler() = %v", err)
	}
	return &fixture{
		handler:   handler,
		registry:  registry,
		forwarder: forwarder,
		logs:      logs,
	}
}

// validBody is the smallest body the API accepts.
const validBody = `{"operation":"file.read","scope":"project","path":"a.txt"}`

// serve runs one request and returns the recorder.
func serve(handler *Handler, request *http.Request) *httptest.ResponseRecorder {
	recorder := httptest.NewRecorder()
	handler.ServeHTTP(recorder, request)
	return recorder
}

// decodeEnvelope decodes the recorded body into an envelope.
func decodeEnvelope(t *testing.T, recorder *httptest.ResponseRecorder) envelope {
	t.Helper()
	var body envelope
	if err := json.Unmarshal(recorder.Body.Bytes(), &body); err != nil {
		t.Fatalf("decode envelope %q: %v", recorder.Body.String(), err)
	}
	return body
}

// TestHandlerRejectsNonPost checks that a read is refused.
//
// The operation is a POST even for a read, because a GET would put the operation
// in a URL that proxies and shell histories record.
func TestHandlerRejectsNonPost(t *testing.T) {
	for _, method := range []string{http.MethodGet, http.MethodPut, http.MethodDelete, http.MethodHead} {
		fixture := newFixture(t, true)
		request := signedRequest(t, testNodeID, validBody)
		request.Method = method

		recorder := serve(fixture.handler, request)
		body := decodeEnvelope(t, recorder)

		if body.Code != protocol.CodeInvalidArgument {
			t.Fatalf("%s: code = %v, want invalid_argument", method, body.Code)
		}
		if recorder.Code != http.StatusBadRequest {
			t.Fatalf("%s: status = %d, want 400", method, recorder.Code)
		}
		if fixture.forwarder.count() != 0 {
			t.Fatalf("%s: forwarded %d requests, want 0", method, fixture.forwarder.count())
		}
	}
}

// TestHandlerRejectsBadPath checks that a path which does not name a node id is
// refused before any proof is verified.
func TestHandlerRejectsBadPath(t *testing.T) {
	paths := []string{
		"/",
		"/v1/nodes/",
		"/v1/nodes//operations",
		"/v1/nodes/" + testNodeID,
		"/v1/nodes/" + testNodeID + "/operations/extra",
		"/v1/nodes/" + testNodeID + "/operation",
		"/v2/nodes/" + testNodeID + "/operations",
		"/v1/nodes/node_abc/def/operations",
	}

	for _, path := range paths {
		fixture := newFixture(t, true)
		request := signedRequest(t, testNodeID, validBody)
		request.URL.Path = path

		recorder := serve(fixture.handler, request)
		body := decodeEnvelope(t, recorder)

		if body.Code != protocol.CodeInvalidArgument {
			t.Fatalf("%q: code = %v, want invalid_argument", path, body.Code)
		}
		if fixture.forwarder.count() != 0 {
			t.Fatalf("%q: forwarded %d requests, want 0", path, fixture.forwarder.count())
		}
	}
}

// TestHandlerRejectsMalformedNodeID checks that a syntactically invalid node id
// is refused, so a typo does not become a credential test.
func TestHandlerRejectsMalformedNodeID(t *testing.T) {
	for _, nodeID := range []string{
		"node_0123456789ABCDEFGHIJKLMNOP",
		"0123456789abcdefghijklmnop",
		"node_",
		"node_0123456789abcdefghijklmno-",
		"node_0123456789abcdefghijklmno.",
		"node_0123456789abcdefghijklmno",
		"node_0123456789abcdefghijklmnopq",
	} {
		fixture := newFixture(t, true)
		request := signedRequest(t, nodeID, validBody)

		recorder := serve(fixture.handler, request)
		body := decodeEnvelope(t, recorder)

		if body.Code != protocol.CodeInvalidArgument {
			t.Fatalf("%q: code = %v, want invalid_argument", nodeID, body.Code)
		}
		if fixture.forwarder.count() != 0 {
			t.Fatalf("%q: forwarded %d requests, want 0", nodeID, fixture.forwarder.count())
		}
	}
}

// TestHandlerRejectsClientProof checks that the Server's own gate answers first.
//
// Every case is a proof the Server must refuse: a missing header, a bearer value
// left over from the previous protocol, a proof for the wrong scheme, a truncated
// proof, and a proof whose signature was altered. A bearer value is included
// deliberately, because a Server that still accepted one would be a Server where the
// HMAC check can be bypassed by sending the old format.
func TestHandlerRejectsClientProof(t *testing.T) {
	valid := signedRequest(t, testNodeID, validBody)
	validProof := valid.Header.Get(security.ClientAuthHeader)

	cases := []struct {
		name   string
		header string
	}{
		{"missing", ""},
		{"bearer value", "Bearer " + string(testClientCredential.Secret)},
		{"bare secret", string(testClientCredential.Secret)},
		{"wrong scheme", strings.Replace(validProof, security.SchemeClient, security.SchemeNode, 1)},
		{"truncated", validProof[:len(validProof)-1]},
		{"signature altered", validProof[:len(validProof)-1] + flipLastHexDigit(validProof)},
		{"unknown key id", strings.Replace(validProof, "key_id="+testClientCredential.KeyID, "key_id=someone-else", 1)},
	}

	for _, testCase := range cases {
		fixture := newFixture(t, true)
		request := signedRequest(t, testNodeID, validBody)
		if testCase.header == "" {
			request.Header.Del(security.ClientAuthHeader)
		} else {
			request.Header.Set(security.ClientAuthHeader, testCase.header)
		}

		recorder := serve(fixture.handler, request)
		body := decodeEnvelope(t, recorder)

		if body.Code != protocol.CodeUnauthenticated {
			t.Fatalf("%s: code = %v, want unauthenticated", testCase.name, body.Code)
		}
		if recorder.Code != http.StatusUnauthorized {
			t.Fatalf("%s: status = %d, want 401", testCase.name, recorder.Code)
		}
		if fixture.forwarder.count() != 0 {
			t.Fatalf("%s: forwarded %d requests, want 0", testCase.name, fixture.forwarder.count())
		}
	}
}

// flipLastHexDigit returns a single hexadecimal digit that differs from the last
// character of a proof header.
//
// It exists so a test can alter one character of a signature without building a
// second valid proof, which is what a forged signature looks like.
func flipLastHexDigit(value string) string {
	if strings.HasSuffix(value, "0") {
		return "1"
	}
	return "0"
}

// TestHandlerRejectsATamperedBody checks that the client proof binds the body.
//
// Without the binding, an attacker could keep a valid proof for a harmless request
// and change the operation, the scope or the path. The Node proof would also fail,
// but the Server boundary must not accept a request that was altered in transit.
func TestHandlerRejectsATamperedBody(t *testing.T) {
	fixture := newFixture(t, true)
	request := signedRequest(t, testNodeID, validBody)
	request.Body = httptest.NewRequest(http.MethodPost, "/", strings.NewReader(`{"operation":"file.read","scope":"project","path":"secret.txt"}`)).Body
	request.ContentLength = int64(len(`{"operation":"file.read","scope":"project","path":"secret.txt"}`))

	recorder := serve(fixture.handler, request)
	body := decodeEnvelope(t, recorder)

	if body.Code != protocol.CodeUnauthenticated {
		t.Fatalf("code = %v, want unauthenticated", body.Code)
	}
	if fixture.forwarder.count() != 0 {
		t.Fatalf("forwarded %d requests, want 0", fixture.forwarder.count())
	}
}

// TestHandlerRejectsAReplacedNodeProof checks that the client proof binds the Node
// proof header.
//
// This is the case the binding exists for: a caller keeps a valid client proof and
// swaps in a Node proof for a different operation. Without the binding the Server
// would forward the substituted proof, and the only remaining check would be the
// Node's.
func TestHandlerRejectsAReplacedNodeProof(t *testing.T) {
	fixture := newFixture(t, true)
	request := signedRequest(t, testNodeID, validBody)
	request.Header.Set(security.NodeAuthHeader, nodeProofFor(t, testNodeID, "req_other", validBody))

	recorder := serve(fixture.handler, request)
	body := decodeEnvelope(t, recorder)

	if body.Code != protocol.CodeUnauthenticated {
		t.Fatalf("code = %v, want unauthenticated", body.Code)
	}
	if fixture.forwarder.count() != 0 {
		t.Fatalf("forwarded %d requests, want 0", fixture.forwarder.count())
	}
}

// TestHandlerRejectsAReplayedClientProof checks that a proof is admitted once.
//
// The second submission is byte for byte the first one, which is what a captured
// request looks like. The Server must refuse it rather than forward it again.
func TestHandlerRejectsAReplayedClientProof(t *testing.T) {
	fixture := newFixture(t, true)
	first := signedRequest(t, testNodeID, validBody)

	firstRecorder := serve(fixture.handler, first)
	if body := decodeEnvelope(t, firstRecorder); body.Code != protocol.CodeSuccess {
		t.Fatalf("first request code = %v, want success", body.Code)
	}

	second := signedRequest(t, testNodeID, validBody)
	second.Header = first.Header.Clone()
	secondRecorder := serve(fixture.handler, second)
	body := decodeEnvelope(t, secondRecorder)

	if body.Code != protocol.CodeUnauthenticated {
		t.Fatalf("replayed request code = %v, want unauthenticated", body.Code)
	}
	if fixture.forwarder.count() != 1 {
		t.Fatalf("forwarded %d requests, want 1", fixture.forwarder.count())
	}
}

// TestHandlerRejectsAStaleClientProof checks that a proof outside the window is
// refused even when its signature is correct.
//
// The signature is built over the stale timestamp, so the only thing that can refuse
// it is the freshness check. A test that signed with the current time would pass with
// the check removed.
func TestHandlerRejectsAStaleClientProof(t *testing.T) {
	fixture := newFixture(t, true)
	request := signedRequest(t, testNodeID, validBody)

	staleTimestamp := time.Now().Add(-2 * security.DefaultReplayWindow).UnixMilli()
	nonce, err := security.NewNonce()
	if err != nil {
		t.Fatalf("NewNonce() = %v", err)
	}
	canonical := security.CanonicalClientRequest(
		request.Method,
		request.URL.RequestURI(),
		security.BodyDigest([]byte(validBody), true),
		security.BytesDigest([]byte(request.Header.Get(security.NodeAuthHeader))),
		request.Header.Get(security.RequestIDHeader),
		staleTimestamp,
		nonce,
	)
	request.Header.Set(security.ClientAuthHeader, security.FormatProof(security.Proof{
		Scheme:      security.SchemeClient,
		Version:     security.ProofVersion,
		KeyID:       testClientCredential.KeyID,
		TimestampMS: staleTimestamp,
		Nonce:       nonce,
		Signature:   security.Sign(testClientCredential.Secret, canonical),
	}))

	recorder := serve(fixture.handler, request)
	body := decodeEnvelope(t, recorder)

	if body.Code != protocol.CodeUnauthenticated {
		t.Fatalf("code = %v, want unauthenticated", body.Code)
	}
	if fixture.forwarder.count() != 0 {
		t.Fatalf("forwarded %d requests, want 0", fixture.forwarder.count())
	}
}

// TestHandlerRejectsContentType checks that a missing or non-JSON content type is
// refused rather than assumed.
func TestHandlerRejectsContentType(t *testing.T) {
	for _, value := range []string{"", "text/plain", "application/x-www-form-urlencoded", "application/jsonx"} {
		fixture := newFixture(t, true)
		request := signedRequest(t, testNodeID, validBody)
		if value == "" {
			request.Header.Del("Content-Type")
		} else {
			request.Header.Set("Content-Type", value)
		}

		recorder := serve(fixture.handler, request)
		body := decodeEnvelope(t, recorder)

		if body.Code != protocol.CodeInvalidArgument {
			t.Fatalf("%q: code = %v, want invalid_argument", value, body.Code)
		}
		if fixture.forwarder.count() != 0 {
			t.Fatalf("%q: forwarded %d requests, want 0", value, fixture.forwarder.count())
		}
	}
}

// TestHandlerAcceptsContentTypeWithParameters checks that a charset parameter is
// tolerated, because a browser and a CLI both send one.
func TestHandlerAcceptsContentTypeWithParameters(t *testing.T) {
	fixture := newFixture(t, true)
	request := signedRequest(t, testNodeID, validBody)
	request.Header.Set("Content-Type", "application/json; charset=utf-8")

	recorder := serve(fixture.handler, request)
	body := decodeEnvelope(t, recorder)

	if body.Code != protocol.CodeSuccess {
		t.Fatalf("code = %v, want success", body.Code)
	}
}

// TestHandlerRejectsOversizedBody checks that a body over the cap is refused with
// too_large rather than truncated.
func TestHandlerRejectsOversizedBody(t *testing.T) {
	fixture := newFixture(t, true)
	oversized := `{"operation":"file.read","scope":"project","path":"` + strings.Repeat("a", MaxRequestBodyBytes) + `"}`
	request := signedRequest(t, testNodeID, oversized)

	recorder := serve(fixture.handler, request)
	body := decodeEnvelope(t, recorder)

	if body.Code != protocol.CodeTooLarge {
		t.Fatalf("code = %v, want too_large", body.Code)
	}
	if recorder.Code != http.StatusRequestEntityTooLarge {
		t.Fatalf("status = %d, want 413", recorder.Code)
	}
	if fixture.forwarder.count() != 0 {
		t.Fatalf("forwarded %d requests, want 0", fixture.forwarder.count())
	}
}

// TestHandlerAcceptsBodyAtCap checks that a body of exactly the cap is accepted,
// so the boundary is inclusive and the cap is not off by one.
func TestHandlerAcceptsBodyAtCap(t *testing.T) {
	fixture := newFixture(t, true)
	prefix := `{"operation":"file.read","scope":"project","path":"`
	suffix := `"}`
	padding := MaxRequestBodyBytes - len(prefix) - len(suffix)
	exact := prefix + strings.Repeat("a", padding) + suffix
	if len(exact) != MaxRequestBodyBytes {
		t.Fatalf("built body is %d bytes, want %d", len(exact), MaxRequestBodyBytes)
	}

	recorder := serve(fixture.handler, signedRequest(t, testNodeID, exact))
	body := decodeEnvelope(t, recorder)

	if body.Code != protocol.CodeSuccess {
		t.Fatalf("code = %v, want success", body.Code)
	}
}

// TestHandlerRejectsMalformedBody checks that a body which does not decode
// strictly is refused.
func TestHandlerRejectsMalformedBody(t *testing.T) {
	cases := []struct {
		name string
		body string
	}{
		{"empty", ""},
		{"not json", "not json"},
		{"truncated", `{"operation":"file.read"`},
		{"unknown field", `{"operation":"file.read","scope":"project","node_id":"node_x"}`},
		{"unknown nested field", `{"operation":"file.read","scope":"project","node_auth":{"key_id":"x"}}`},
		{"second document", `{"operation":"file.read","scope":"project"}{"operation":"file.list"}`},
		{"array", `[]`},
		{"null", `null`},
	}

	for _, testCase := range cases {
		fixture := newFixture(t, true)

		recorder := serve(fixture.handler, signedRequest(t, testNodeID, testCase.body))
		body := decodeEnvelope(t, recorder)

		if body.Code != protocol.CodeInvalidArgument {
			t.Fatalf("%s: code = %v, want invalid_argument", testCase.name, body.Code)
		}
		if fixture.forwarder.count() != 0 {
			t.Fatalf("%s: forwarded %d requests, want 0", testCase.name, fixture.forwarder.count())
		}
	}
}

// TestHandlerRejectsMissingNodeProof checks that the node proof header is required,
// because the Server cannot forward a proof it never received.
func TestHandlerRejectsMissingNodeProof(t *testing.T) {
	fixture := newFixture(t, true)
	request := signedRequest(t, testNodeID, validBody)
	request.Header.Del(security.NodeAuthHeader)

	recorder := serve(fixture.handler, request)
	body := decodeEnvelope(t, recorder)

	if body.Code != protocol.CodeUnauthenticated {
		t.Fatalf("code = %v, want unauthenticated", body.Code)
	}
	if fixture.forwarder.count() != 0 {
		t.Fatalf("forwarded %d requests, want 0", fixture.forwarder.count())
	}
}

// TestHandlerRejectsMalformedNodeProof checks that a node proof which does not match
// the accepted grammar is refused before it reaches a Node.
//
// The Server cannot verify the signature, so the shape check is the only thing it can
// do. A malformed envelope that reached a Node would be a Node-side refusal for a
// reason the Server could have reported itself.
func TestHandlerRejectsMalformedNodeProof(t *testing.T) {
	cases := []string{
		"not a proof",
		security.SchemeClient + " version=1,key_id=operator,timestamp_ms=1,nonce=" + strings.Repeat("a", 32) + ",signature=" + strings.Repeat("b", 64),
		security.SchemeNode + " version=1,key_id=operator",
		security.SchemeNode + " version=1,key_id=operator,timestamp_ms=1,nonce=short,signature=" + strings.Repeat("b", 64),
	}
	for _, value := range cases {
		fixture := newFixture(t, true)
		request := signedRequestWithNodeProofHeader(t, testNodeID, validBody, value)

		recorder := serve(fixture.handler, request)
		body := decodeEnvelope(t, recorder)

		if body.Code != protocol.CodeInvalidArgument {
			t.Fatalf("%q: code = %v, want invalid_argument", value, body.Code)
		}
		if fixture.forwarder.count() != 0 {
			t.Fatalf("%q: forwarded %d requests, want 0", value, fixture.forwarder.count())
		}
	}
}

// TestHandlerRejectsOfflineNode checks that a request for a node with no live
// connection is refused without reaching the forwarder.
func TestHandlerRejectsOfflineNode(t *testing.T) {
	fixture := newFixture(t, false)

	recorder := serve(fixture.handler, signedRequest(t, testNodeID, validBody))
	body := decodeEnvelope(t, recorder)

	if body.Code != protocol.CodeNodeOffline {
		t.Fatalf("code = %v, want node_offline", body.Code)
	}
	if recorder.Code != http.StatusServiceUnavailable {
		t.Fatalf("status = %d, want 503", recorder.Code)
	}
	if fixture.forwarder.count() != 0 {
		t.Fatalf("forwarded %d requests, want 0", fixture.forwarder.count())
	}
}

// TestHandlerRefusesUnwiredHandler checks that a handler built without a registry
// or a forwarder refuses instead of panicking.
//
// A panic on the request path is a denial of service caused by a wiring mistake,
// and the wiring mistake is exactly what a half built Server has.
func TestHandlerRefusesUnwiredHandler(t *testing.T) {
	cases := []struct {
		name      string
		registry  *Registry
		forwarder Forwarder
	}{
		{"nil registry", nil, &fakeForwarder{}},
		{"nil forwarder", NewRegistry(), nil},
		{"both nil", nil, nil},
	}

	for _, testCase := range cases {
		handler, err := NewHandler(testConfig(t), testCase.registry, testCase.forwarder, nil)
		if err != nil {
			t.Fatalf("%s: NewHandler() = %v", testCase.name, err)
		}

		recorder := serve(handler, signedRequest(t, testNodeID, validBody))
		body := decodeEnvelope(t, recorder)

		if body.Code != protocol.CodeInternal {
			t.Fatalf("%s: code = %v, want internal", testCase.name, body.Code)
		}
	}
}
