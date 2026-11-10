package server

import (
	"bytes"
	"context"
	"errors"
	"net/http"
	"net/http/httptest"
	"reflect"
	"strings"
	"testing"
	"time"

	"topsailai_connector/internal/protocol"
	"topsailai_connector/internal/security"
)

// TestHandlerForwardsRequestUnchanged checks that the Server relays the caller's
// request and adds only the identity it took from the path and the header.
func TestHandlerForwardsRequestUnchanged(t *testing.T) {
	fixture := newFixture(t, true)
	body := `{"operation":"file.read","scope":"project","path":"a.txt","offset":10,"length":20}`

	recorder := serve(fixture.handler, operationRequest(testNodeID, body))
	envelopeBody := decodeEnvelope(t, recorder)

	if envelopeBody.Code != protocol.CodeSuccess {
		t.Fatalf("code = %v, want success", envelopeBody.Code)
	}

	forwarded, ok := fixture.forwarder.last()
	if !ok {
		t.Fatal("no request was forwarded")
	}
	if forwarded.NodeID != testNodeID {
		t.Fatalf("node id = %q, want %q", forwarded.NodeID, testNodeID)
	}
	if forwarded.NodeToken != security.Secret(testNodeToken) {
		t.Fatalf("node token was not relayed")
	}
	if forwarded.Operation != protocol.OperationFileRead {
		t.Fatalf("operation = %q, want file.read", forwarded.Operation)
	}
	if forwarded.Scope != security.Scope("project") {
		t.Fatalf("scope = %q, want project", forwarded.Scope)
	}
	if forwarded.Path != "a.txt" {
		t.Fatalf("path = %q, want a.txt", forwarded.Path)
	}
	if forwarded.Offset != 10 || forwarded.Length != 20 {
		t.Fatalf("offset/length = %d/%d, want 10/20", forwarded.Offset, forwarded.Length)
	}
}

// TestHandlerRelaysNodeAnswerUnchanged checks that the Node's code and data reach
// the caller without the Server rewriting either.
//
// The Server does not know why the Node refused, so a rewritten code would be a
// guess presented as an answer.
func TestHandlerRelaysNodeAnswerUnchanged(t *testing.T) {
	cases := []struct {
		name     string
		response protocol.Response
		status   int
	}{
		{"success with data", protocol.Success([]byte(`{"content":"aGk=","size":2}`)), http.StatusOK},
		{"denied", protocol.Failure(protocol.CodeDenied), http.StatusForbidden},
		{"not found", protocol.Failure(protocol.CodeNotFound), http.StatusNotFound},
		{"unsupported", protocol.Failure(protocol.CodeUnsupportedOperation), http.StatusBadRequest},
		{"too large", protocol.Failure(protocol.CodeTooLarge), http.StatusRequestEntityTooLarge},
		{"internal", protocol.Failure(protocol.CodeInternal), http.StatusInternalServerError},
	}

	for _, testCase := range cases {
		fixture := newFixture(t, true)
		fixture.forwarder.response = testCase.response

		recorder := serve(fixture.handler, operationRequest(testNodeID, validBody))
		body := decodeEnvelope(t, recorder)

		if body.Code != testCase.response.Code {
			t.Fatalf("%s: code = %v, want %v", testCase.name, body.Code, testCase.response.Code)
		}
		if recorder.Code != testCase.status {
			t.Fatalf("%s: status = %d, want %d", testCase.name, recorder.Code, testCase.status)
		}
		if len(testCase.response.Data) > 0 {
			if !bytes.Equal(body.Data, testCase.response.Data) {
				t.Fatalf("%s: data = %s, want %s", testCase.name, body.Data, testCase.response.Data)
			}
		} else if len(body.Data) > 0 {
			t.Fatalf("%s: refusal carried data %s", testCase.name, body.Data)
		}
	}
}

// TestHandlerMapsForwardErrors checks that a transport failure becomes a code the
// caller can act on.
func TestHandlerMapsForwardErrors(t *testing.T) {
	cases := []struct {
		name   string
		err    error
		code   protocol.Code
		status int
	}{
		{"offline", ErrNodeOffline, protocol.CodeNodeOffline, http.StatusServiceUnavailable},
		{"deadline", context.DeadlineExceeded, protocol.CodeNodeTimeout, http.StatusGatewayTimeout},
		{"unclassified", errors.New("socket closed"), protocol.CodeInternal, http.StatusInternalServerError},
	}

	for _, testCase := range cases {
		fixture := newFixture(t, true)
		fixture.forwarder.err = testCase.err

		recorder := serve(fixture.handler, operationRequest(testNodeID, validBody))
		body := decodeEnvelope(t, recorder)

		if body.Code != testCase.code {
			t.Fatalf("%s: code = %v, want %v", testCase.name, body.Code, testCase.code)
		}
		if recorder.Code != testCase.status {
			t.Fatalf("%s: status = %d, want %d", testCase.name, recorder.Code, testCase.status)
		}
		if len(body.Data) > 0 {
			t.Fatalf("%s: failure carried data %s", testCase.name, body.Data)
		}
	}
}

// TestHandlerTimesOutSlowForward checks that the configured timeout bounds one
// forwarded request.
//
// The timeout bounds the request, not the channel: a channel open for a month says
// nothing about whether the Node is answering now.
func TestHandlerTimesOutSlowForward(t *testing.T) {
	fixture := newFixture(t, true)
	fixture.forwarder.delay = 2 * time.Second

	config := testConfig()
	config.RequestTimeout = 20 * time.Millisecond
	fixture.handler.config = config

	start := time.Now()
	recorder := serve(fixture.handler, operationRequest(testNodeID, validBody))
	elapsed := time.Since(start)

	body := decodeEnvelope(t, recorder)
	if body.Code != protocol.CodeNodeTimeout {
		t.Fatalf("code = %v, want node_timeout", body.Code)
	}
	if elapsed > time.Second {
		t.Fatalf("handler waited %v, want the timeout to bound it", elapsed)
	}
}

// TestHandlerUsesDefaultTimeoutWhenUnset checks that a zero timeout falls back to
// the default instead of meaning "no timeout".
func TestHandlerUsesDefaultTimeoutWhenUnset(t *testing.T) {
	fixture := newFixture(t, true)
	config := testConfig()
	config.RequestTimeout = 0
	fixture.handler.config = config

	recorder := serve(fixture.handler, operationRequest(testNodeID, validBody))
	body := decodeEnvelope(t, recorder)

	if body.Code != protocol.CodeSuccess {
		t.Fatalf("code = %v, want success", body.Code)
	}
}

// TestHandlerNeverLogsSecrets checks that neither secret reaches the log.
//
// The Server never stores a Node token, and a log line is a store. The client
// token is the Server's own credential and is equally absent.
func TestHandlerNeverLogsSecrets(t *testing.T) {
	cases := []struct {
		name    string
		prepare func(*fixture) *http.Request
	}{
		{"success", func(f *fixture) *http.Request {
			return operationRequest(testNodeID, validBody)
		}},
		{"wrong client token", func(f *fixture) *http.Request {
			request := operationRequest(testNodeID, validBody)
			request.Header.Set("Authorization", "Bearer wrong-token-0123456789")
			return request
		}},
		{"missing node token", func(f *fixture) *http.Request {
			request := operationRequest(testNodeID, validBody)
			request.Header.Del("X-Connector-Node-Token")
			return request
		}},
		{"offline node", func(f *fixture) *http.Request {
			f.registry.CloseAll()
			return operationRequest(testNodeID, validBody)
		}},
		{"malformed body", func(f *fixture) *http.Request {
			return operationRequest(testNodeID, "not json")
		}},
	}

	for _, testCase := range cases {
		fixture := newFixture(t, true)
		request := testCase.prepare(fixture)

		serve(fixture.handler, request)

		logged := fixture.logs.String()
		if strings.Contains(logged, testNodeToken) {
			t.Fatalf("%s: log contains the node token: %s", testCase.name, logged)
		}
		if strings.Contains(logged, testClientToken) {
			t.Fatalf("%s: log contains the client token: %s", testCase.name, logged)
		}
		if strings.Contains(logged, "wrong-token-0123456789") {
			t.Fatalf("%s: log contains the presented client token: %s", testCase.name, logged)
		}
	}
}

// TestHandlerDoesNotRetainNodeToken checks that the handler keeps no copy of the
// node token after the request is answered.
//
// The rule is "no retention after forwarding", so the check is that the handler's
// own fields hold no secret and that a second request without the header is
// refused rather than served from a remembered value.
func TestHandlerDoesNotRetainNodeToken(t *testing.T) {
	fixture := newFixture(t, true)

	serve(fixture.handler, operationRequest(testNodeID, validBody))
	if fixture.forwarder.count() != 1 {
		t.Fatalf("forwarded %d requests, want 1", fixture.forwarder.count())
	}

	second := operationRequest(testNodeID, validBody)
	second.Header.Del("X-Connector-Node-Token")
	recorder := serve(fixture.handler, second)
	body := decodeEnvelope(t, recorder)

	if body.Code != protocol.CodeUnauthenticated {
		t.Fatalf("code = %v, want unauthenticated: a remembered token was reused", body.Code)
	}
	if fixture.forwarder.count() != 1 {
		t.Fatalf("forwarded %d requests, want 1", fixture.forwarder.count())
	}

	// The handler struct must not carry the token in any field.
	value := reflect.ValueOf(*fixture.handler)
	for index := 0; index < value.NumField(); index++ {
		field := value.Field(index)
		if field.Kind() != reflect.String {
			continue
		}
		if strings.Contains(field.String(), testNodeToken) {
			t.Fatalf("handler field %q retains the node token", value.Type().Field(index).Name)
		}
	}
}

// TestHandlerEchoesRequestID checks that a caller supplied correlation id is
// echoed so a request can be followed across two systems.
func TestHandlerEchoesRequestID(t *testing.T) {
	fixture := newFixture(t, true)
	request := operationRequest(testNodeID, validBody)
	request.Header.Set("X-Request-Id", "req_caller_supplied")

	recorder := serve(fixture.handler, request)
	body := decodeEnvelope(t, recorder)

	if body.RequestID != "req_caller_supplied" {
		t.Fatalf("request id = %q, want the supplied value", body.RequestID)
	}
}

// TestHandlerGeneratesRequestID checks that a request without a correlation id
// gets a fresh one, and that an over-long one is replaced rather than logged.
func TestHandlerGeneratesRequestID(t *testing.T) {
	cases := []struct {
		name   string
		supply string
	}{
		{"absent", ""},
		{"over long", strings.Repeat("r", 200)},
	}

	for _, testCase := range cases {
		fixture := newFixture(t, true)
		request := operationRequest(testNodeID, validBody)
		if testCase.supply != "" {
			request.Header.Set("X-Request-Id", testCase.supply)
		}

		recorder := serve(fixture.handler, request)
		body := decodeEnvelope(t, recorder)

		if !strings.HasPrefix(body.RequestID, "req_") {
			t.Fatalf("%s: request id = %q, want a generated one", testCase.name, body.RequestID)
		}
		if body.RequestID == testCase.supply {
			t.Fatalf("%s: over-long request id was echoed", testCase.name)
		}
	}
}

// TestHandlerSetsTimestamp checks that every answer carries a timestamp, so a
// caller can order two answers without trusting its own clock.
func TestHandlerSetsTimestamp(t *testing.T) {
	fixture := newFixture(t, true)
	before := time.Now().UnixMilli()

	recorder := serve(fixture.handler, operationRequest(testNodeID, validBody))
	body := decodeEnvelope(t, recorder)

	if body.Timestamp < before {
		t.Fatalf("timestamp = %d, want at least %d", body.Timestamp, before)
	}
}

// TestHandlerRefusalCarriesNoData checks that a refusal never carries a payload,
// so a refusal cannot be mistaken for a partial success.
func TestHandlerRefusalCarriesNoData(t *testing.T) {
	fixture := newFixture(t, true)
	request := operationRequest(testNodeID, validBody)
	request.Header.Del("Authorization")

	recorder := serve(fixture.handler, request)
	body := decodeEnvelope(t, recorder)

	if len(body.Data) > 0 {
		t.Fatalf("refusal carried data %s", body.Data)
	}
	if body.Message == "" {
		t.Fatal("refusal carried no message")
	}
}

// TestHandlerRefusalMessageIsFixedPerCode checks that the message never carries a
// detail string, because a detail string is where a path or a scope name leaks.
func TestHandlerRefusalMessageIsFixedPerCode(t *testing.T) {
	fixture := newFixture(t, true)
	request := operationRequest(testNodeID, validBody)
	request.Header.Set("Authorization", "Bearer wrong-token-0123456789")

	recorder := serve(fixture.handler, request)
	body := decodeEnvelope(t, recorder)

	if body.Message != messageOf(protocol.CodeUnauthenticated) {
		t.Fatalf("message = %q, want the fixed message", body.Message)
	}
	if strings.Contains(body.Message, "wrong-token") {
		t.Fatalf("message leaked the presented token: %q", body.Message)
	}
}

// TestHandlerRejectsNodeTokenOnAnotherNode checks that a token presented for one
// node id is forwarded only to that node.
//
// The Server cannot validate the token, so the check is that it does not silently
// retarget the request: the node id comes from the path and is never taken from
// the body or from a remembered value.
func TestHandlerRejectsNodeTokenOnAnotherNode(t *testing.T) {
	fixture := newFixture(t, true)
	const otherNodeID = "node_def456"
	if _, _, err := fixture.registry.Register(&fakeChannel{nodeID: otherNodeID}); err != nil {
		t.Fatalf("Register: %v", err)
	}

	recorder := serve(fixture.handler, operationRequest(otherNodeID, validBody))
	body := decodeEnvelope(t, recorder)

	if body.Code != protocol.CodeSuccess {
		t.Fatalf("code = %v, want success", body.Code)
	}

	forwarded, ok := fixture.forwarder.last()
	if !ok {
		t.Fatal("no request was forwarded")
	}
	if forwarded.NodeID != otherNodeID {
		t.Fatalf("node id = %q, want %q", forwarded.NodeID, otherNodeID)
	}
}

// TestHandlerChecksOrderOfRefusals checks that the checks run in the documented
// order, so an earlier failure hides a later one.
//
// The order matters because a caller that fails the Server's own gate must learn
// nothing about the Node, and a malformed path must not become a credential test.
func TestHandlerChecksOrderOfRefusals(t *testing.T) {
	cases := []struct {
		name    string
		prepare func(*http.Request)
		code    protocol.Code
	}{
		{
			name: "bad method beats bad path",
			prepare: func(r *http.Request) {
				r.Method = http.MethodGet
				r.URL.Path = "/nonsense"
			},
			code: protocol.CodeInvalidArgument,
		},
		{
			name: "bad path beats bad client token",
			prepare: func(r *http.Request) {
				r.URL.Path = "/nonsense"
				r.Header.Set("Authorization", "Bearer wrong-token-0123456789")
			},
			code: protocol.CodeInvalidArgument,
		},
		{
			name: "bad client token beats bad content type",
			prepare: func(r *http.Request) {
				r.Header.Set("Authorization", "Bearer wrong-token-0123456789")
				r.Header.Set("Content-Type", "text/plain")
			},
			code: protocol.CodeUnauthenticated,
		},
		{
			name: "bad content type beats bad body",
			prepare: func(r *http.Request) {
				r.Header.Set("Content-Type", "text/plain")
				r.Body = http.NoBody
			},
			code: protocol.CodeInvalidArgument,
		},
		{
			name: "bad body beats missing node token",
			prepare: func(r *http.Request) {
				r.Body = httptest.NewRequest(http.MethodPost, "/", strings.NewReader("not json")).Body
				r.Header.Del("X-Connector-Node-Token")
			},
			code: protocol.CodeInvalidArgument,
		},
		{
			name: "missing node token beats offline node",
			prepare: func(r *http.Request) {
				r.Header.Del("X-Connector-Node-Token")
			},
			code: protocol.CodeUnauthenticated,
		},
	}

	for _, testCase := range cases {
		fixture := newFixture(t, false)
		request := operationRequest(testNodeID, validBody)
		testCase.prepare(request)

		recorder := serve(fixture.handler, request)
		body := decodeEnvelope(t, recorder)

		if body.Code != testCase.code {
			t.Fatalf("%s: code = %v, want %v", testCase.name, body.Code, testCase.code)
		}
	}
}
