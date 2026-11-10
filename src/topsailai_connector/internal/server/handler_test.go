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
	testNodeID = "node_abc123"
	// testClientToken is the Server's own gate.
	testClientToken = "client-token-0123456789"
	// testNodeToken is the Node's gate. The Server never validates it, so the
	// value only has to be non-empty for the handler to relay it.
	testNodeToken = "nodetoken0123456789"
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
func testConfig() Config {
	return Config{
		Listen:         DefaultListenAddress,
		TunnelToken:    security.Secret("tunnel-token-0123456789"),
		ClientToken:    security.Secret(testClientToken),
		RequestTimeout: 5 * time.Second,
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
	return &fixture{
		handler:   NewHandler(testConfig(), registry, forwarder, logger),
		registry:  registry,
		forwarder: forwarder,
		logs:      logs,
	}
}

// operationRequest builds a well formed POST for one node id.
func operationRequest(nodeID, body string) *http.Request {
	request := httptest.NewRequest(http.MethodPost, OperationPathPrefix+nodeID+OperationPathSuffix, strings.NewReader(body))
	request.Header.Set("Content-Type", "application/json")
	request.Header.Set("Authorization", "Bearer "+testClientToken)
	request.Header.Set("X-Connector-Node-Token", testNodeToken)
	return request
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
		request := operationRequest(testNodeID, validBody)
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
// refused before any secret is compared.
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
		request := operationRequest(testNodeID, validBody)
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
	for _, nodeID := range []string{"node_ABC123", "abc123", "node_", "node_ab-c", "node_ab.c"} {
		fixture := newFixture(t, true)
		request := operationRequest(nodeID, validBody)

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

// TestHandlerRejectsClientToken checks that the Server's own gate answers first.
func TestHandlerRejectsClientToken(t *testing.T) {
	cases := []struct {
		name   string
		header string
	}{
		{"missing", ""},
		{"wrong", "Bearer wrong-token-0123456789"},
		{"bare token", testClientToken},
		{"wrong scheme", "Basic " + testClientToken},
		{"prefix only", "Bearer "},
		{"token with suffix", "Bearer " + testClientToken + "x"},
		{"token with prefix", "Bearer x" + testClientToken},
	}

	for _, testCase := range cases {
		fixture := newFixture(t, true)
		request := operationRequest(testNodeID, validBody)
		if testCase.header == "" {
			request.Header.Del("Authorization")
		} else {
			request.Header.Set("Authorization", testCase.header)
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

// TestHandlerRejectsContentType checks that a missing or non-JSON content type is
// refused rather than assumed.
func TestHandlerRejectsContentType(t *testing.T) {
	for _, value := range []string{"", "text/plain", "application/x-www-form-urlencoded", "application/jsonx"} {
		fixture := newFixture(t, true)
		request := operationRequest(testNodeID, validBody)
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
	request := operationRequest(testNodeID, validBody)
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
	request := operationRequest(testNodeID, oversized)

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

	recorder := serve(fixture.handler, operationRequest(testNodeID, exact))
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
		{"unknown nested field", `{"operation":"file.read","scope":"project","node_token":"x"}`},
		{"second document", `{"operation":"file.read","scope":"project"}{"operation":"file.list"}`},
		{"array", `[]`},
		{"null", `null`},
	}

	for _, testCase := range cases {
		fixture := newFixture(t, true)

		recorder := serve(fixture.handler, operationRequest(testNodeID, testCase.body))
		body := decodeEnvelope(t, recorder)

		if body.Code != protocol.CodeInvalidArgument {
			t.Fatalf("%s: code = %v, want invalid_argument", testCase.name, body.Code)
		}
		if fixture.forwarder.count() != 0 {
			t.Fatalf("%s: forwarded %d requests, want 0", testCase.name, fixture.forwarder.count())
		}
	}
}

// TestHandlerRejectsMissingNodeToken checks that the node token header is
// required, because the Server cannot forward a credential it never received.
func TestHandlerRejectsMissingNodeToken(t *testing.T) {
	fixture := newFixture(t, true)
	request := operationRequest(testNodeID, validBody)
	request.Header.Del("X-Connector-Node-Token")

	recorder := serve(fixture.handler, request)
	body := decodeEnvelope(t, recorder)

	if body.Code != protocol.CodeUnauthenticated {
		t.Fatalf("code = %v, want unauthenticated", body.Code)
	}
	if fixture.forwarder.count() != 0 {
		t.Fatalf("forwarded %d requests, want 0", fixture.forwarder.count())
	}
}

// TestHandlerRejectsOfflineNode checks that a request for a node with no live
// connection is refused without reaching the forwarder.
func TestHandlerRejectsOfflineNode(t *testing.T) {
	fixture := newFixture(t, false)

	recorder := serve(fixture.handler, operationRequest(testNodeID, validBody))
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
		handler := NewHandler(testConfig(), testCase.registry, testCase.forwarder, nil)

		recorder := serve(handler, operationRequest(testNodeID, validBody))
		body := decodeEnvelope(t, recorder)

		if body.Code != protocol.CodeInternal {
			t.Fatalf("%s: code = %v, want internal", testCase.name, body.Code)
		}
	}
}
