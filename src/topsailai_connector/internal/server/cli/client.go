// Package cli implements the operator-facing client that reaches a Node through
// the Server's HTTP API.
//
// The CLI is a subcommand of the Server binary rather than a separate program, so
// an operator installs one binary and gets both the Server and the client. It is a
// separate package so the request it builds can be tested without starting a
// process or opening a socket.
//
// Two rules shape everything here:
//
//   - The CLI never prints a secret. The `client_token` and the `node-token` are
//     never written to stdout, stderr, an error message or a verbose dump. The
//     `node-id` is printed in full, because it is not a secret.
//   - The CLI refuses a malformed pair before it sends anything. A copy-paste
//     error surfaces locally instead of as a confusing authentication failure
//     reported by the Node.
package cli

import (
	"bytes"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"strings"
	"time"

	"topsailai_connector/internal/protocol"
	"topsailai_connector/internal/security"
)

// DefaultTimeout bounds one CLI request.
//
// It is longer than the Server's own forward timeout on purpose: the Server
// reports node_timeout when the Node is slow, and the CLI must be able to receive
// that answer instead of giving up first and reporting a network error that hides
// the real cause.
const DefaultTimeout = 45 * time.Second

// MaxResponseBytes bounds the response body the CLI will read.
//
// A CLI that read an unbounded body would be a CLI that can be made to exhaust its
// own memory by a Server that is compromised or merely broken.
const MaxResponseBytes = 8 << 20

// ErrUsage reports a request the CLI refuses to build.
var ErrUsage = errors.New("usage")

// Options is everything one CLI invocation needs.
type Options struct {
	// ServerURL is the base URL of the Server, for example
	// "https://connector.example.com:8443". A trailing slash is tolerated.
	ServerURL string
	// ClientToken is the Server-wide secret the CLI presents.
	ClientToken security.Secret
	// Pair is the whole `node-id.node-token` value the operator copied from
	// `connector-node id`.
	Pair string
	// Operation is one of the three enabled operations.
	Operation protocol.Operation
	// Scope is the scope name the Node's policy defines.
	Scope security.Scope
	// Path is the relative path inside the scope.
	Path string
	// Offset is the byte offset for file.read.
	Offset int64
	// Length is the byte count for file.read; zero means up to the cap.
	Length int64
	// RequestID is an optional correlation id. An empty value lets the Server
	// generate one.
	RequestID string
}

// Envelope is the response shape the Server returns.
//
// It is declared here rather than imported from the Server package so the CLI
// depends on the wire contract and not on the Server's internals. A CLI that
// imported the Server's own type would compile against a change that breaks the
// contract, which is exactly the change a separate declaration catches.
type Envelope struct {
	Code      protocol.Code   `json:"code"`
	Message   string          `json:"message"`
	Data      json.RawMessage `json:"data"`
	RequestID string          `json:"request_id"`
	Timestamp int64           `json:"timestamp"`
}

// Succeeded reports whether the envelope carries a success code.
func (e Envelope) Succeeded() bool {
	return e.Code.IsSuccess()
}

// requestBody is the body the CLI sends.
//
// It deliberately has no node id and no node token: the node id travels in the URL
// and the node token in a header, so the Server never receives the pair as one
// value. The Server refuses unknown fields, so a body carrying either would be
// refused rather than silently ignored.
type requestBody struct {
	Operation string `json:"operation"`
	Scope     string `json:"scope"`
	Path      string `json:"path,omitempty"`
	Offset    int64  `json:"offset,omitempty"`
	Length    int64  `json:"length,omitempty"`
}

// Client sends one operation and returns the Server's envelope.
type Client struct {
	// HTTP is the transport. A nil value uses a client with DefaultTimeout, so a
	// caller that has not configured a transport still gets a bounded request.
	HTTP *http.Client
	// MaxResponseBytes bounds the body. Zero uses MaxResponseBytes.
	MaxResponseBytes int64
}

// Send performs one operation.
//
// The pair is parsed before the request is built, so a malformed pair is reported
// as a usage error and nothing is sent. The two halves then go to the two places
// the Server expects them: the node id into the URL path, the node token into
// X-Connector-Node-Token.
func (c *Client) Send(options Options) (Envelope, error) {
	identity, err := security.ParseNodeIdentity(options.Pair)
	if err != nil {
		return Envelope{}, fmt.Errorf("%w: --node %v", ErrUsage, err)
	}
	if err := options.ClientToken.Validate("client token"); err != nil {
		return Envelope{}, fmt.Errorf("%w: %v", ErrUsage, err)
	}
	if err := options.Operation.Validate(); err != nil {
		return Envelope{}, fmt.Errorf("%w: %v", ErrUsage, err)
	}
	if !options.Operation.Enabled() {
		return Envelope{}, fmt.Errorf("%w: operation %q is not enabled in this version", ErrUsage, options.Operation)
	}
	if err := security.ValidateScopeName(options.Scope); err != nil {
		return Envelope{}, fmt.Errorf("%w: %v", ErrUsage, err)
	}

	url, err := operationURL(options.ServerURL, identity.ID)
	if err != nil {
		return Envelope{}, fmt.Errorf("%w: %v", ErrUsage, err)
	}

	body, err := json.Marshal(requestBody{
		Operation: string(options.Operation),
		Scope:     string(options.Scope),
		Path:      options.Path,
		Offset:    options.Offset,
		Length:    options.Length,
	})
	if err != nil {
		return Envelope{}, fmt.Errorf("encode request: %w", err)
	}

	request, err := http.NewRequest(http.MethodPost, url, bytes.NewReader(body))
	if err != nil {
		return Envelope{}, fmt.Errorf("build request: %w", err)
	}
	request.Header.Set("Content-Type", "application/json")
	request.Header.Set("Authorization", "Bearer "+string(options.ClientToken))
	request.Header.Set("X-Connector-Node-Token", string(identity.Token))
	if options.RequestID != "" {
		request.Header.Set("X-Request-Id", options.RequestID)
	}

	response, err := c.transport().Do(request)
	if err != nil {
		return Envelope{}, fmt.Errorf("call server: %w", err)
	}
	defer response.Body.Close()

	return decodeEnvelope(response.Body, c.limit())
}

// transport returns the HTTP client to use.
func (c *Client) transport() *http.Client {
	if c != nil && c.HTTP != nil {
		return c.HTTP
	}
	return &http.Client{Timeout: DefaultTimeout}
}

// limit returns the response body cap.
func (c *Client) limit() int64 {
	if c != nil && c.MaxResponseBytes > 0 {
		return c.MaxResponseBytes
	}
	return MaxResponseBytes
}

// operationURL builds the operation URL for one node id.
//
// The node id is validated before it is placed in the path, so a value containing
// a slash or a dot segment cannot address a different endpoint. The Server
// validates it again; this check exists so a malformed value is reported locally
// rather than as a routing failure.
func operationURL(serverURL, nodeID string) (string, error) {
	if serverURL == "" {
		return "", errors.New("server URL is empty")
	}
	if err := security.ValidateNodeID(nodeID); err != nil {
		return "", err
	}
	trimmed := strings.TrimRight(serverURL, "/")
	if !strings.HasPrefix(trimmed, "http://") && !strings.HasPrefix(trimmed, "https://") {
		return "", fmt.Errorf("server URL %q must start with http:// or https://", serverURL)
	}
	return trimmed + "/v1/nodes/" + nodeID + "/operations", nil
}

// decodeEnvelope reads and decodes one envelope.
//
// The body is bounded before it is decoded, and a body that is not an envelope is
// reported as a protocol error rather than as an empty success: a caller that
// treated an unreadable answer as success would act on a result nobody produced.
func decodeEnvelope(body io.Reader, limit int64) (Envelope, error) {
	payload, err := io.ReadAll(io.LimitReader(body, limit+1))
	if err != nil {
		return Envelope{}, fmt.Errorf("read response: %w", err)
	}
	if int64(len(payload)) > limit {
		return Envelope{}, fmt.Errorf("response body exceeds %d bytes", limit)
	}

	decoder := json.NewDecoder(bytes.NewReader(payload))
	decoder.DisallowUnknownFields()

	// The envelope is decoded into a pointer so a JSON `null` body is refused.
	// Decoding `null` into a struct value succeeds and leaves every field zero,
	// and a zero code is CodeSuccess: a body that is not an envelope would become
	// a successful empty result, which is the one answer a caller must never
	// receive by accident.
	var envelope *Envelope
	if err := decoder.Decode(&envelope); err != nil {
		return Envelope{}, fmt.Errorf("decode response: %w", err)
	}
	if envelope == nil {
		return Envelope{}, errors.New("response body is not an envelope")
	}
	if err := decoder.Decode(new(json.RawMessage)); !errors.Is(err, io.EOF) {
		return Envelope{}, errors.New("response body carries more than one JSON document")
	}
	return *envelope, nil
}
