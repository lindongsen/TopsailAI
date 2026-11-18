package server

import (
	"bytes"
	"context"
	"errors"
	"net/http"
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

	recorder := serve(fixture.handler, signedRequest(t, testNodeID, body))
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
	if forwarded.NodeAuth.KeyID != testNodeCredential.KeyID {
		t.Fatalf("node proof key id = %q, want %q", forwarded.NodeAuth.KeyID, testNodeCredential.KeyID)
	}
	if forwarded.NodeAuth.Signature == "" {
		t.Fatal("node proof signature was not relayed")
	}
	if forwarded.RequestID == "" {
		t.Fatal("request id was not relayed")
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

// TestHandlerForwardsTheNodeProofByteForByte checks that the forwarded proof is the
// one the caller sent.
//
// The Server does not hold the Node credential, so it cannot verify the signature and
// must not alter it. A re-encoded or normalised proof would be a proof the Node
// refuses, and the refusal would look like a credential problem rather than a
// forwarding problem.
func TestHandlerForwardsTheNodeProofByteForByte(t *testing.T) {
	fixture := newFixture(t, true)
	request := signedRequest(t, testNodeID, validBody)
	sent, err := security.ParseProof(request.Header.Get(security.NodeAuthHeader), security.SchemeNode)
	if err != nil {
		t.Fatalf("ParseProof() = %v", err)
	}

	recorder := serve(fixture.handler, request)
	if body := decodeEnvelope(t, recorder); body.Code != protocol.CodeSuccess {
		t.Fatalf("code = %v, want success", body.Code)
	}

	forwarded, ok := fixture.forwarder.last()
	if !ok {
		t.Fatal("no request was forwarded")
	}
	if forwarded.NodeAuth != sent {
		t.Fatalf("forwarded proof = %+v, want %+v", forwarded.NodeAuth, sent)
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

		recorder := serve(fixture.handler, signedRequest(t, testNodeID, validBody))
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

		recorder := serve(fixture.handler, signedRequest(t, testNodeID, validBody))
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

	config := testConfig(t)
	config.RequestTimeout = 20 * time.Millisecond
	fixture.handler.config = config

	start := time.Now()
	recorder := serve(fixture.handler, signedRequest(t, testNodeID, validBody))
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
	config := testConfig(t)
	config.RequestTimeout = 0
	fixture.handler.config = config

	recorder := serve(fixture.handler, signedRequest(t, testNodeID, validBody))
	body := decodeEnvelope(t, recorder)

	if body.Code != protocol.CodeSuccess {
		t.Fatalf("code = %v, want success", body.Code)
	}
}

// TestHandlerNeverLogsSecrets checks that no secret reaches the log.
//
// The Server never stores a Node credential, and a log line is a store. The client
// secret is the Server's own credential and is equally absent. The presented values
// are checked too, because a log that echoes a rejected proof leaks the same secret
// the accepted one would.
func TestHandlerNeverLogsSecrets(t *testing.T) {
	cases := []struct {
		name    string
		prepare func(*fixture) *http.Request
	}{
		{"success", func(f *fixture) *http.Request {
			return signedRequest(t, testNodeID, validBody)
		}},
		{"wrong client secret", func(f *fixture) *http.Request {
			request := signedRequest(t, testNodeID, validBody)
			request.Header.Set(security.ClientAuthHeader, security.FormatProof(security.Proof{
				Scheme:      security.SchemeClient,
				Version:     security.ProofVersion,
				KeyID:       testClientCredential.KeyID,
				TimestampMS: time.Now().UnixMilli(),
				Nonce:       strings.Repeat("a", security.NonceHexLength),
				Signature:   strings.Repeat("b", security.SignatureHexLength),
			}))
			return request
		}},
		{"missing node proof", func(f *fixture) *http.Request {
			request := signedRequest(t, testNodeID, validBody)
			request.Header.Del(security.NodeAuthHeader)
			return request
		}},
		{"offline node", func(f *fixture) *http.Request {
			f.registry.CloseAll()
			return signedRequest(t, testNodeID, validBody)
		}},
		{"malformed body", func(f *fixture) *http.Request {
			return signedRequest(t, testNodeID, "not json")
		}},
	}

	for _, testCase := range cases {
		fixture := newFixture(t, true)
		request := testCase.prepare(fixture)

		serve(fixture.handler, request)

		logged := fixture.logs.String()
		for name, secret := range map[string]string{
			"client secret": string(testClientCredential.Secret),
			"node secret":   string(testNodeCredential.Secret),
		} {
			if strings.Contains(logged, secret) {
				t.Fatalf("%s: log contains the %s: %s", testCase.name, name, logged)
			}
		}
	}
}

// TestHandlerDoesNotRetainNodeProof checks that the handler keeps no copy of the
// node proof after the request is answered.
//
// The rule is "no retention after forwarding", so the check is that the handler's
// own fields hold no proof and that a second request without the header is refused
// rather than served from a remembered value.
func TestHandlerDoesNotRetainNodeProof(t *testing.T) {
	fixture := newFixture(t, true)

	first := signedRequest(t, testNodeID, validBody)
	signature, err := security.ParseProof(first.Header.Get(security.NodeAuthHeader), security.SchemeNode)
	if err != nil {
		t.Fatalf("ParseProof() = %v", err)
	}

	serve(fixture.handler, first)
	if fixture.forwarder.count() != 1 {
		t.Fatalf("forwarded %d requests, want 1", fixture.forwarder.count())
	}

	second := signedRequest(t, testNodeID, validBody)
	second.Header.Del(security.NodeAuthHeader)
	recorder := serve(fixture.handler, second)
	body := decodeEnvelope(t, recorder)

	if body.Code != protocol.CodeUnauthenticated {
		t.Fatalf("code = %v, want unauthenticated: a remembered proof was reused", body.Code)
	}
	if fixture.forwarder.count() != 1 {
		t.Fatalf("forwarded %d requests, want 1", fixture.forwarder.count())
	}

	// The handler struct must not carry the proof in any string field.
	value := reflect.ValueOf(*fixture.handler)
	for index := 0; index < value.NumField(); index++ {
		field := value.Field(index)
		if field.Kind() != reflect.String {
			continue
		}
		if strings.Contains(field.String(), signature.Signature) {
			t.Fatalf("handler field %q retains the node proof", value.Type().Field(index).Name)
		}
	}
}

// TestHandlerEchoesRequestID checks that a caller supplied correlation id is
// echoed so a request can be followed across two systems.
func TestHandlerEchoesRequestID(t *testing.T) {
	fixture := newFixture(t, true)
	const requestID = "req_caller_supplied"
	request := signedRequestWithID(t, testNodeID, validBody, requestID)

	recorder := serve(fixture.handler, request)
	body := decodeEnvelope(t, recorder)

	if body.RequestID != requestID {
		t.Fatalf("request id = %q, want the supplied value", body.RequestID)
	}
}

// TestHandlerRequiresASignedRequestID checks that a request whose correlation id was
// not signed is refused.
//
// The id occupies one line of both canonical inputs, so a Server that substituted a
// fresh id would make every proof fail. The refusal is the correct answer: the id is
// part of the signed request, not a decoration the Server may replace.
func TestHandlerRequiresASignedRequestID(t *testing.T) {
	cases := []struct {
		name   string
		supply string
	}{
		{"absent", ""},
		{"over long", strings.Repeat("r", 200)},
		{"contains a newline", "req_a\nreq_b"},
	}

	for _, testCase := range cases {
		fixture := newFixture(t, true)
		request := signedRequest(t, testNodeID, validBody)
		if testCase.supply == "" {
			request.Header.Del(security.RequestIDHeader)
		} else {
			request.Header.Set(security.RequestIDHeader, testCase.supply)
		}

		recorder := serve(fixture.handler, request)
		body := decodeEnvelope(t, recorder)

		if body.Code != protocol.CodeUnauthenticated {
			t.Fatalf("%s: code = %v, want unauthenticated", testCase.name, body.Code)
		}
		if fixture.forwarder.count() != 0 {
			t.Fatalf("%s: forwarded %d requests, want 0", testCase.name, fixture.forwarder.count())
		}
	}
}

// TestHandlerSetsTimestamp checks that every answer carries a timestamp, so a
// caller can order two answers without trusting its own clock.
func TestHandlerSetsTimestamp(t *testing.T) {
	fixture := newFixture(t, true)
	before := time.Now().UnixMilli()

	recorder := serve(fixture.handler, signedRequest(t, testNodeID, validBody))
	body := decodeEnvelope(t, recorder)

	if body.Timestamp < before {
		t.Fatalf("timestamp = %d, want at least %d", body.Timestamp, before)
	}
}

// TestHandlerRefusalCarriesNoData checks that a refusal never carries a payload,
// so a refusal cannot be mistaken for a partial success.
func TestHandlerRefusalCarriesNoData(t *testing.T) {
	fixture := newFixture(t, true)
	request := signedRequest(t, testNodeID, validBody)
	request.Header.Del(security.ClientAuthHeader)

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
	request := signedRequest(t, testNodeID, validBody)
	request.Header.Set(security.ClientAuthHeader, "Bearer "+string(testClientCredential.Secret))

	recorder := serve(fixture.handler, request)
	body := decodeEnvelope(t, recorder)

	if body.Message != messageOf(protocol.CodeUnauthenticated) {
		t.Fatalf("message = %q, want the fixed message", body.Message)
	}
	if strings.Contains(body.Message, string(testClientCredential.Secret)) {
		t.Fatalf("message leaked the presented secret: %q", body.Message)
	}
}

// TestHandlerRoutesByThePathNodeID checks that the node id comes from the path and is
// never taken from the body or from a remembered value.
//
// The Server cannot verify the Node proof, so the check is that it does not silently
// retarget the request: a proof built for one node id is forwarded only to the node id
// the path names.
func TestHandlerRoutesByThePathNodeID(t *testing.T) {
	fixture := newFixture(t, true)
	const otherNodeID = "node_zyxwvutsrqponmlkjihgfedcba"
	if _, _, err := fixture.registry.Register(&fakeChannel{nodeID: otherNodeID}); err != nil {
		t.Fatalf("Register: %v", err)
	}

	recorder := serve(fixture.handler, signedRequest(t, otherNodeID, validBody))
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
//
// Each case builds its own request instead of mutating a signed one, because the client
// proof binds the method, the path, the body and the Node proof header. A case that
// mutated a signed request would fail the client check first and would then be measuring
// that check rather than the one it names.
func TestHandlerChecksOrderOfRefusals(t *testing.T) {
	cases := []struct {
		name  string
		build func(t *testing.T) *http.Request
		code  protocol.Code
	}{
		{
			name: "bad method beats bad path",
			build: func(t *testing.T) *http.Request {
				request := signedRequest(t, testNodeID, validBody)
				request.Method = http.MethodGet
				request.URL.Path = "/nonsense"
				return request
			},
			code: protocol.CodeInvalidArgument,
		},
		{
			name: "bad path beats a bad client proof",
			build: func(t *testing.T) *http.Request {
				request := signedRequest(t, testNodeID, validBody)
				request.URL.Path = "/nonsense"
				request.Header.Set(security.ClientAuthHeader, "Bearer "+string(testClientCredential.Secret))
				return request
			},
			code: protocol.CodeInvalidArgument,
		},
		{
			name: "missing node proof beats a bad client proof",
			build: func(t *testing.T) *http.Request {
				request := signedRequest(t, testNodeID, validBody)
				request.Header.Del(security.NodeAuthHeader)
				request.Header.Set(security.ClientAuthHeader, "Bearer "+string(testClientCredential.Secret))
				return request
			},
			code: protocol.CodeUnauthenticated,
		},
		{
			name: "bad client proof beats a bad content type",
			build: func(t *testing.T) *http.Request {
				request := signedRequest(t, testNodeID, validBody)
				request.Header.Set(security.ClientAuthHeader, "Bearer "+string(testClientCredential.Secret))
				request.Header.Set("Content-Type", "text/plain")
				return request
			},
			code: protocol.CodeUnauthenticated,
		},
		{
			name: "bad content type beats a bad body",
			build: func(t *testing.T) *http.Request {
				request := signedRequestWithNodeProofHeader(t, testNodeID, "", nodeProofFor(t, testNodeID, "req_order", ""))
				request.Header.Set("Content-Type", "text/plain")
				return request
			},
			code: protocol.CodeInvalidArgument,
		},
		{
			name: "bad body beats a malformed node proof",
			build: func(t *testing.T) *http.Request {
				return signedRequestWithNodeProofHeader(t, testNodeID, "not json", "not a proof")
			},
			code: protocol.CodeInvalidArgument,
		},
		{
			name: "malformed node proof beats an offline node",
			build: func(t *testing.T) *http.Request {
				return signedRequestWithNodeProofHeader(t, testNodeID, validBody, "not a proof")
			},
			code: protocol.CodeInvalidArgument,
		},
	}

	for _, testCase := range cases {
		fixture := newFixture(t, false)
		request := testCase.build(t)

		recorder := serve(fixture.handler, request)
		body := decodeEnvelope(t, recorder)

		if body.Code != testCase.code {
			t.Fatalf("%s: code = %v, want %v", testCase.name, body.Code, testCase.code)
		}
	}
}
