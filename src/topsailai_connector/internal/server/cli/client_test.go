package cli

import (
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"topsailai_connector/internal/protocol"
	"topsailai_connector/internal/security"
)

// recordedRequest is one request the test server received.
type recordedRequest struct {
	method string
	path   string
	header http.Header
	body   []byte
}

// testNodeID returns a freshly generated node id, so a test never hardcodes a value
// the generator could change.
func testNodeID(t *testing.T) string {
	t.Helper()
	nodeID, err := security.NewNodeID()
	if err != nil {
		t.Fatalf("NewNodeID: %v", err)
	}
	return nodeID
}

// testClientCredential returns a client credential long enough to pass validation.
func testClientCredential() security.Credential {
	return security.Credential{
		KeyID:  "operator",
		Secret: security.Secret("client-secret-0123456789abcdefghij"),
	}
}

// testNodeCredential returns a node credential long enough to pass validation.
func testNodeCredential() security.Credential {
	return security.Credential{
		KeyID:  "node-operator",
		Secret: security.Secret("node-secret-0123456789abcdefghij"),
	}
}

// newRecordingServer starts a server that records every request and answers with a
// fixed status and body.
func newRecordingServer(t *testing.T, status int, response string) (*httptest.Server, *[]recordedRequest) {
	t.Helper()
	recorded := make([]recordedRequest, 0, 1)
	server := httptest.NewServer(http.HandlerFunc(func(writer http.ResponseWriter, request *http.Request) {
		body, err := io.ReadAll(request.Body)
		if err != nil {
			t.Errorf("read request body: %v", err)
		}
		recorded = append(recorded, recordedRequest{
			method: request.Method,
			path:   request.URL.Path,
			header: request.Header.Clone(),
			body:   body,
		})
		writer.Header().Set("Content-Type", "application/json")
		writer.WriteHeader(status)
		if _, err := io.WriteString(writer, response); err != nil {
			t.Errorf("write response: %v", err)
		}
	}))
	t.Cleanup(server.Close)
	return server, &recorded
}

// successEnvelope is a well-formed success answer.
const successEnvelope = `{"code":0,"message":"success","data":{"content":"aGk=","size":2,"truncated":false},"request_id":"req_1","timestamp":1700000000000}`

// validOptions returns options that pass every local check.
func validOptions(t *testing.T, serverURL string) Options {
	t.Helper()
	return Options{
		ServerURL:        serverURL,
		ClientCredential: testClientCredential(),
		NodeCredential:   testNodeCredential(),
		NodeID:           testNodeID(t),
		Operation:        protocol.OperationFileRead,
		Scope:            security.Scope("project"),
		Path:             "a.txt",
	}
}

// TestSendRefusesMalformedCredentialsBeforeSending proves a copy-paste error is
// reported locally instead of as an authentication failure from the Server or the
// Node.
func TestSendRefusesMalformedCredentialsBeforeSending(t *testing.T) {
	server, recorded := newRecordingServer(t, http.StatusOK, successEnvelope)

	cases := map[string]func(*Options){
		"empty client key id": func(o *Options) {
			o.ClientCredential.KeyID = ""
		},
		"client key id with a dot": func(o *Options) {
			o.ClientCredential.KeyID = "a.b"
		},
		"client key id with uppercase": func(o *Options) {
			o.ClientCredential.KeyID = "Operator"
		},
		"client key id starting with a dash": func(o *Options) {
			o.ClientCredential.KeyID = "-operator"
		},
		"short client secret": func(o *Options) {
			o.ClientCredential.Secret = security.Secret("short")
		},
		"empty client secret": func(o *Options) {
			o.ClientCredential.Secret = ""
		},
		"client secret with whitespace": func(o *Options) {
			o.ClientCredential.Secret = security.Secret("client-secret-0123456789abcdefghij\n")
		},
		"empty node key id": func(o *Options) {
			o.NodeCredential.KeyID = ""
		},
		"short node secret": func(o *Options) {
			o.NodeCredential.Secret = security.Secret("short")
		},
		"empty node secret": func(o *Options) {
			o.NodeCredential.Secret = ""
		},
	}

	for name, mutate := range cases {
		t.Run(name, func(t *testing.T) {
			options := validOptions(t, server.URL)
			mutate(&options)

			client := &Client{HTTP: server.Client()}
			if _, err := client.Send(options); err == nil {
				t.Fatal("Send accepted a malformed credential")
			}
		})
	}

	if len(*recorded) != 0 {
		t.Fatalf("server received %d requests, want 0", len(*recorded))
	}
}

// TestSendRefusesInvalidOptions proves every local check runs before a request is
// built.
func TestSendRefusesInvalidOptions(t *testing.T) {
	server, recorded := newRecordingServer(t, http.StatusOK, successEnvelope)

	cases := map[string]func(*Options){
		"empty node id": func(o *Options) { o.NodeID = "" },
		"node id without prefix": func(o *Options) {
			o.NodeID = strings.TrimPrefix(o.NodeID, security.NodeIDPrefix)
		},
		"node id with a slash": func(o *Options) { o.NodeID = "node_a/b" },
		"unknown operation":    func(o *Options) { o.Operation = protocol.Operation("file.delete") },
		"empty operation":      func(o *Options) { o.Operation = "" },
		"disabled operation": func(o *Options) {
			o.Operation = protocol.OperationFileWrite
		},
		"disabled exec": func(o *Options) { o.Operation = protocol.OperationCommandExec },
		"empty scope":   func(o *Options) { o.Scope = "" },
		"scope with space": func(o *Options) {
			o.Scope = security.Scope("a b")
		},
		"scope with slash": func(o *Options) { o.Scope = security.Scope("a/b") },
		"scope with dot":   func(o *Options) { o.Scope = security.Scope("..") },
		"empty server URL": func(o *Options) { o.ServerURL = "" },
		"server URL without scheme": func(o *Options) {
			o.ServerURL = "connector.example.com"
		},
		"server URL with wrong scheme": func(o *Options) {
			o.ServerURL = "ftp://connector.example.com"
		},
		"request id with a space": func(o *Options) { o.RequestID = "req a" },
	}

	for name, mutate := range cases {
		t.Run(name, func(t *testing.T) {
			options := validOptions(t, server.URL)
			mutate(&options)

			client := &Client{HTTP: server.Client()}
			if _, err := client.Send(options); err == nil {
				t.Fatal("Send accepted invalid options")
			}
		})
	}

	if len(*recorded) != 0 {
		t.Fatalf("server received %d requests, want 0", len(*recorded))
	}
}

// TestSendPlacesTheProofsInTheDocumentedPlaces proves the node id travels in the URL,
// the client proof in Authorization and the Node proof in its own header, so the
// Server never receives a reusable secret.
func TestSendPlacesTheProofsInTheDocumentedPlaces(t *testing.T) {
	server, recorded := newRecordingServer(t, http.StatusOK, successEnvelope)

	options := validOptions(t, server.URL)

	client := &Client{HTTP: server.Client()}
	if _, err := client.Send(options); err != nil {
		t.Fatalf("Send: %v", err)
	}

	if len(*recorded) != 1 {
		t.Fatalf("server received %d requests, want 1", len(*recorded))
	}
	request := (*recorded)[0]

	if request.method != http.MethodPost {
		t.Errorf("method = %q, want POST", request.method)
	}
	wantPath := "/v1/nodes/" + options.NodeID + "/operations"
	if request.path != wantPath {
		t.Errorf("path = %q, want %q", request.path, wantPath)
	}

	clientProof, err := security.ParseProof(request.header.Get(security.ClientAuthHeader), security.SchemeClient)
	if err != nil {
		t.Fatalf("Authorization is not a client proof: %v", err)
	}
	if clientProof.KeyID != options.ClientCredential.KeyID {
		t.Errorf("client proof key id = %q, want %q", clientProof.KeyID, options.ClientCredential.KeyID)
	}

	nodeProof, err := security.ParseProof(request.header.Get(security.NodeAuthHeader), security.SchemeNode)
	if err != nil {
		t.Fatalf("%s is not a node proof: %v", security.NodeAuthHeader, err)
	}
	if nodeProof.KeyID != options.NodeCredential.KeyID {
		t.Errorf("node proof key id = %q, want %q", nodeProof.KeyID, options.NodeCredential.KeyID)
	}
	if nodeProof.Nonce == clientProof.Nonce {
		t.Error("the two proofs share a nonce, want independent nonces")
	}

	if got := request.header.Get("Content-Type"); got != "application/json" {
		t.Errorf("Content-Type = %q, want application/json", got)
	}
	if got := request.header.Get(security.RequestIDHeader); got == "" {
		t.Error("X-Request-Id is empty, want a generated id")
	}
}

// TestSendNeverTransmitsASecret proves neither secret reaches the wire.
//
// The whole point of the proof is that a captured request cannot be replayed into a
// new one, and a request that carried the secret would make the proof decorative.
func TestSendNeverTransmitsASecret(t *testing.T) {
	server, recorded := newRecordingServer(t, http.StatusOK, successEnvelope)

	options := validOptions(t, server.URL)

	client := &Client{HTTP: server.Client()}
	if _, err := client.Send(options); err != nil {
		t.Fatalf("Send: %v", err)
	}

	request := (*recorded)[0]
	transmitted := request.path + "\n" + request.bodyString() + "\n"
	for name, values := range request.header {
		transmitted += name + ": " + strings.Join(values, ",") + "\n"
	}

	for name, secret := range map[string]security.Secret{
		"client secret": options.ClientCredential.Secret,
		"node secret":   options.NodeCredential.Secret,
	} {
		if strings.Contains(transmitted, string(secret)) {
			t.Errorf("the request carries the %s", name)
		}
	}
}

// bodyString renders the recorded body for a substring search.
func (r recordedRequest) bodyString() string {
	return string(r.body)
}

// TestSendOmitsIdentityFromTheBody proves the body carries no identity, because the
// Server refuses unknown fields and a body carrying one would be refused rather than
// silently ignored.
func TestSendOmitsIdentityFromTheBody(t *testing.T) {
	server, recorded := newRecordingServer(t, http.StatusOK, successEnvelope)

	options := validOptions(t, server.URL)

	client := &Client{HTTP: server.Client()}
	if _, err := client.Send(options); err != nil {
		t.Fatalf("Send: %v", err)
	}

	body := string((*recorded)[0].body)
	if strings.Contains(body, options.NodeID) {
		t.Errorf("body contains the node id: %s", body)
	}

	var decoded map[string]any
	if err := json.Unmarshal((*recorded)[0].body, &decoded); err != nil {
		t.Fatalf("decode body: %v", err)
	}
	for _, forbidden := range []string{"node_id", "node_token", "node_auth", "token"} {
		if _, present := decoded[forbidden]; present {
			t.Errorf("body carries %q", forbidden)
		}
	}
	if decoded["operation"] != string(protocol.OperationFileRead) {
		t.Errorf("operation = %v, want file.read", decoded["operation"])
	}
	if decoded["scope"] != "project" {
		t.Errorf("scope = %v, want project", decoded["scope"])
	}
	if decoded["path"] != "a.txt" {
		t.Errorf("path = %v, want a.txt", decoded["path"])
	}
}

// TestSendUsesTheSuppliedRequestID proves a caller supplied id is the one both proofs
// sign and the one the request carries.
func TestSendUsesTheSuppliedRequestID(t *testing.T) {
	server, recorded := newRecordingServer(t, http.StatusOK, successEnvelope)

	options := validOptions(t, server.URL)
	options.RequestID = "req_abc"

	client := &Client{HTTP: server.Client()}
	if _, err := client.Send(options); err != nil {
		t.Fatalf("Send: %v", err)
	}

	if got := (*recorded)[0].header.Get(security.RequestIDHeader); got != "req_abc" {
		t.Errorf("X-Request-Id = %q, want req_abc", got)
	}
}

// TestSendGeneratesADistinctRequestIDPerCall proves two calls do not reuse an id,
// because a reused id with a fresh nonce would still be a different request and the
// correlation would be wrong.
func TestSendGeneratesADistinctRequestIDPerCall(t *testing.T) {
	server, recorded := newRecordingServer(t, http.StatusOK, successEnvelope)

	client := &Client{HTTP: server.Client()}
	for attempt := 0; attempt < 2; attempt++ {
		if _, err := client.Send(validOptions(t, server.URL)); err != nil {
			t.Fatalf("Send: %v", err)
		}
	}

	if len(*recorded) != 2 {
		t.Fatalf("server received %d requests, want 2", len(*recorded))
	}
	first := (*recorded)[0].header.Get(security.RequestIDHeader)
	second := (*recorded)[1].header.Get(security.RequestIDHeader)
	if first == second {
		t.Fatalf("both calls used request id %q, want distinct ids", first)
	}
}

// TestSendToleratesTrailingSlash proves a base URL copied with a trailing slash does
// not produce a doubled separator.
func TestSendToleratesTrailingSlash(t *testing.T) {
	server, recorded := newRecordingServer(t, http.StatusOK, successEnvelope)

	options := validOptions(t, server.URL+"/")

	client := &Client{HTTP: server.Client()}
	if _, err := client.Send(options); err != nil {
		t.Fatalf("Send: %v", err)
	}

	wantPath := "/v1/nodes/" + options.NodeID + "/operations"
	if got := (*recorded)[0].path; got != wantPath {
		t.Errorf("path = %q, want %q", got, wantPath)
	}
}

// TestSendReturnsTheEnvelope proves a success answer is decoded into the documented
// shape.
func TestSendReturnsTheEnvelope(t *testing.T) {
	server, _ := newRecordingServer(t, http.StatusOK, successEnvelope)

	client := &Client{HTTP: server.Client()}
	envelope, err := client.Send(validOptions(t, server.URL))
	if err != nil {
		t.Fatalf("Send: %v", err)
	}

	if !envelope.Succeeded() {
		t.Errorf("code = %d, want success", envelope.Code)
	}
	if envelope.Message != "success" {
		t.Errorf("message = %q, want success", envelope.Message)
	}
	if envelope.RequestID != "req_1" {
		t.Errorf("request_id = %q, want req_1", envelope.RequestID)
	}
	if envelope.Timestamp != 1700000000000 {
		t.Errorf("timestamp = %d, want 1700000000000", envelope.Timestamp)
	}
	if len(envelope.Data) == 0 {
		t.Error("data is empty")
	}
}

// TestSendReturnsARefusalEnvelope proves a refusal is returned as an envelope rather
// than as a transport error, so the caller can report the code.
func TestSendReturnsARefusalEnvelope(t *testing.T) {
	refusal := `{"code":1005,"message":"denied","data":null,"request_id":"req_2","timestamp":1700000000000}`
	server, _ := newRecordingServer(t, http.StatusForbidden, refusal)

	client := &Client{HTTP: server.Client()}
	envelope, err := client.Send(validOptions(t, server.URL))
	if err != nil {
		t.Fatalf("Send returned a transport error for a refusal: %v", err)
	}

	if envelope.Succeeded() {
		t.Error("a refusal envelope reported success")
	}
	if envelope.Code != protocol.CodeDenied {
		t.Errorf("code = %d, want denied", envelope.Code)
	}
}

// TestSendRefusesAnUnreadableResponse proves a body that is not an envelope is
// reported as an error instead of as an empty success.
func TestSendRefusesAnUnreadableResponse(t *testing.T) {
	cases := map[string]string{
		"empty body":         "",
		"not JSON":           "not json",
		"JSON array":         `[1,2,3]`,
		"JSON null":          `null`,
		"unknown field":      `{"code":0,"message":"success","data":null,"request_id":"r","timestamp":1,"extra":true}`,
		"two documents":      `{"code":0,"message":"success","data":null,"request_id":"r","timestamp":1}{"code":0}`,
		"wrong field type":   `{"code":"zero","message":"success","data":null,"request_id":"r","timestamp":1}`,
		"truncated document": `{"code":0,"message":"succ`,
	}

	for name, body := range cases {
		t.Run(name, func(t *testing.T) {
			server, _ := newRecordingServer(t, http.StatusOK, body)

			client := &Client{HTTP: server.Client()}
			if _, err := client.Send(validOptions(t, server.URL)); err == nil {
				t.Fatal("Send accepted an unreadable response")
			}
		})
	}
}

// TestSendRefusesAnOversizedResponse proves a Server cannot exhaust the CLI's memory
// by answering with an unbounded body.
func TestSendRefusesAnOversizedResponse(t *testing.T) {
	server, _ := newRecordingServer(t, http.StatusOK, successEnvelope)

	client := &Client{HTTP: server.Client(), MaxResponseBytes: 8}
	if _, err := client.Send(validOptions(t, server.URL)); err == nil {
		t.Fatal("Send accepted a response over the cap")
	}
}

// TestSendAcceptsAResponseAtTheCap proves the cap is inclusive, so a body of exactly
// the limit is not refused by an off-by-one.
func TestSendAcceptsAResponseAtTheCap(t *testing.T) {
	server, _ := newRecordingServer(t, http.StatusOK, successEnvelope)

	client := &Client{HTTP: server.Client(), MaxResponseBytes: int64(len(successEnvelope))}
	if _, err := client.Send(validOptions(t, server.URL)); err != nil {
		t.Fatalf("Send refused a response of exactly the cap: %v", err)
	}
}

// TestSendReportsATransportFailure proves an unreachable Server is an error, not an
// empty success.
func TestSendReportsATransportFailure(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(http.ResponseWriter, *http.Request) {}))
	url := server.URL
	server.Close()

	client := &Client{HTTP: &http.Client{}}
	if _, err := client.Send(validOptions(t, url)); err == nil {
		t.Fatal("Send accepted an unreachable server")
	}
}

// TestClientDefaultsAreSafe proves a zero Client still gets a bounded transport and a
// bounded body.
func TestClientDefaultsAreSafe(t *testing.T) {
	var client *Client
	if got := client.limit(); got != MaxResponseBytes {
		t.Errorf("limit = %d, want %d", got, MaxResponseBytes)
	}
	if got := client.transport(); got == nil || got.Timeout != DefaultTimeout {
		t.Errorf("transport = %v, want a client with the default timeout", got)
	}

	configured := &Client{HTTP: &http.Client{}, MaxResponseBytes: 16}
	if got := configured.limit(); got != 16 {
		t.Errorf("limit = %d, want 16", got)
	}
}

// TestOperationURLValidatesTheNodeID proves a value that could address a different
// endpoint is refused before it reaches the path.
func TestOperationURLValidatesTheNodeID(t *testing.T) {
	cases := map[string]string{
		"empty":          "",
		"missing prefix": "abc",
		"slash":          "node_a/b",
		"dot segment":    "node_..",
		"uppercase":      "node_ABC",
		"space":          "node_a b",
	}

	for name, nodeID := range cases {
		t.Run(name, func(t *testing.T) {
			if _, err := operationURL("https://example.com", nodeID); err == nil {
				t.Fatalf("operationURL accepted node id %q", nodeID)
			}
		})
	}
}

// TestOperationURLBuildsTheDocumentedPath proves the path is the one docs/API.md
// documents.
func TestOperationURLBuildsTheDocumentedPath(t *testing.T) {
	nodeID := testNodeID(t)

	got, err := operationURL("https://example.com:8443/", nodeID)
	if err != nil {
		t.Fatalf("operationURL: %v", err)
	}
	want := "https://example.com:8443/v1/nodes/" + nodeID + "/operations"
	if got != want {
		t.Errorf("url = %q, want %q", got, want)
	}
}
