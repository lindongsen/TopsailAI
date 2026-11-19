// Package cli implements the operator-facing client that reaches a Node through the
// Server's HTTP API.
//
// The CLI is a subcommand of the Server binary rather than a separate program, so an
// operator installs one binary and gets both the Server and the client. It is a
// separate package so the request it builds can be tested without starting a process
// or opening a socket.
//
// Two rules shape everything here:
//
//   - The CLI never prints a secret. The client secret and the node secret are never
//     written to stdout, stderr, an error message or a verbose dump. The node id is
//     printed in full, because it is not a secret.
//   - The CLI refuses a malformed credential before it sends anything. A copy-paste
//     error surfaces locally instead of as a confusing authentication failure reported
//     by the Node.
package cli

import (
	"bytes"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"strconv"
	"strings"
	"time"

	"topsailai_connector/internal/protocol"
	"topsailai_connector/internal/security"
)

// DefaultTimeout bounds one CLI request.
//
// It is longer than the Server's own forward timeout on purpose: the Server reports
// node_timeout when the Node is slow, and the CLI must be able to receive that answer
// instead of giving up first and reporting a network error that hides the real cause.
const DefaultTimeout = 45 * time.Second

// MaxResponseBytes bounds the response body the CLI will read.
//
// A CLI that read an unbounded body would be a CLI that can be made to exhaust its own
// memory by a Server that is compromised or merely broken.
const MaxResponseBytes = 8 << 20

// ErrUsage reports a request the CLI refuses to build.
var ErrUsage = errors.New("usage")

// Options is everything one CLI invocation needs.
type Options struct {
	// ServerURL is the base URL of the Server, for example
	// "https://connector.example.com:8443". A trailing slash is tolerated.
	ServerURL string
	// ClientCredential is the credential the Server verifies. Its key identifier is
	// public and its secret never leaves this process.
	ClientCredential security.Credential
	// NodeCredential is the credential the Node verifies. Its key identifier is public
	// and its secret never leaves this process.
	NodeCredential security.Credential
	// NodeID is the address of the Node the request is for.
	NodeID string
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
	// RequestID is an optional correlation id. An empty value lets the CLI generate
	// one, which is the ordinary case: the id is signed by both proofs, so it must be
	// known before the proofs are built.
	RequestID string
	// Output is the local destination for the result. An empty value keeps the
	// historical behaviour: the payload goes to stdout and a `file.read` fetches one
	// chunk. "-" means stdout with a whole-file read, and any other value is a local
	// file path.
	//
	// It is a local path, not a remote one. It is not subject to the Node's path
	// grammar, so an absolute path and a `..` component are both legal here while
	// Path refuses them.
	Output string
	// Force permits Output to replace an existing file. Without it a destination that
	// already exists is refused, because a read tool that silently overwrites a local
	// file destroys work the caller did not ask it to touch.
	Force bool
}

// Envelope is the response shape the Server returns.
//
// It is declared here rather than imported from the Server package so the CLI depends
// on the wire contract and not on the Server's internals. A CLI that imported the
// Server's own type would compile against a change that breaks the contract, which is
// exactly the change a separate declaration catches.
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
// It deliberately has no node id and no proof: the node id travels in the URL and the
// proofs travel in headers, so the Server never receives the node id as part of a
// credential. The Server refuses unknown fields, so a body carrying either would be
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
	// HTTP is the transport. A nil value uses a client with DefaultTimeout, so a caller
	// that has not configured a transport still gets a bounded request.
	HTTP *http.Client
	// MaxResponseBytes bounds the body. Zero uses MaxResponseBytes.
	MaxResponseBytes int64
	// Now returns the current time. A nil value uses time.Now, so a test can pin the
	// clock the proofs are built from.
	Now func() time.Time
}

// RawResponse is the answer to a request that asked for the file bytes directly.
//
// It exists because the raw shape carries no JSON body: the bytes are the body and
// the metadata travels in headers. A caller that decoded this as an envelope would
// read the first bytes of a file as a status code.
type RawResponse struct {
	// Content is the file bytes, exactly as the Server sent them.
	Content []byte
	// Truncated reports whether content was left behind, which is the same meaning
	// the envelope's `truncated` field carries.
	Truncated bool
	// RequestID is the correlation id the Server echoed back.
	RequestID string
}

// rawContentMediaType is the media type that asks for the file bytes directly.
//
// It is the same value the Server compares against, and it is declared here rather
// than imported from the Server package for the same reason Envelope is: the CLI
// depends on the wire contract, not on the Server's internals.
const rawContentMediaType = "application/octet-stream"

// truncatedHeader carries the truncation flag on the raw path.
const truncatedHeader = "X-Connector-Truncated"

// Send performs one operation and returns the Server's envelope.
//
// The credentials are validated before the request is built, so a malformed credential
// is reported as a usage error and nothing is sent. Two proofs are then built over the
// same request id: the client proof covers the HTTP request and the exact Node proof
// header, and the Node proof covers the logical operation. The Server verifies the
// first and forwards the second, so neither party can widen its own authority.
func (c *Client) Send(options Options) (Envelope, error) {
	request, err := c.buildRequest(options, false)
	if err != nil {
		return Envelope{}, err
	}

	response, err := c.transport().Do(request)
	if err != nil {
		return Envelope{}, fmt.Errorf("call server: %w", err)
	}
	defer response.Body.Close()

	return decodeEnvelope(response.Body, c.limit())
}

// SendRaw performs one operation and returns the file bytes without the envelope.
//
// The request is identical to Send's except for one header, so the proofs, the
// nonces and the replay protection are unchanged: only the encoding of the answer
// differs. That is why this is a second method rather than a second operation.
//
// A refusal still arrives as the envelope, because the Server keeps the JSON shape
// whenever the answer is not a success. The two are told apart by the response's
// media type, which is the only signal the Server sends: an octet-stream body is
// bytes, and anything else is the documented envelope.
func (c *Client) SendRaw(options Options) (RawResponse, error) {
	request, err := c.buildRequest(options, true)
	if err != nil {
		return RawResponse{}, err
	}

	response, err := c.transport().Do(request)
	if err != nil {
		return RawResponse{}, fmt.Errorf("call server: %w", err)
	}
	defer response.Body.Close()

	if !isRawResponse(response) {
		// The Server answers with the envelope in three cases: the request was
		// refused, the answer is a success with no bytes (the empty file), and the
		// Server predates the opt-in and ignored the Accept header. All three are
		// decoded here, and the payload is read from the envelope rather than
		// discarded, because discarding it would turn an older Server's answer into a
		// successful read of zero bytes.
		envelope, err := decodeEnvelope(response.Body, c.limit())
		if err != nil {
			return RawResponse{}, err
		}
		if !envelope.Succeeded() {
			return RawResponse{}, fmt.Errorf("%s: %s", envelope.Code.Name(), envelope.Message)
		}
		chunk, err := decodeReadChunk(envelope.Data)
		if err != nil {
			return RawResponse{}, err
		}
		return RawResponse{
			Content:   chunk.Content,
			Truncated: chunk.Truncated,
			RequestID: envelope.RequestID,
		}, nil
	}

	return readRawResponse(response, c.limit())
}

// decodeReadChunk decodes the documented `file.read` payload.
//
// It is used on the envelope path, which is reached when the Server refused the
// request, when the file is empty, or when the Server predates the opt-in. The third
// case is why the content is returned rather than dropped: an older Server sends the
// bytes inside the envelope, and a caller that ignored them would report a successful
// read of nothing.
func decodeReadChunk(data json.RawMessage) (readChunk, error) {
	if len(data) == 0 {
		return readChunk{}, nil
	}
	var chunk readChunk
	if err := json.Unmarshal(data, &chunk); err != nil {
		return readChunk{}, fmt.Errorf("decode read result: %w", err)
	}
	return chunk, nil
}

// isRawResponse reports whether the answer is the byte stream rather than the envelope.
//
// The media type is the only discriminator the Server provides, so it is compared
// without parameters and case-insensitively, the same way the Server parses Accept.
func isRawResponse(response *http.Response) bool {
	mediaType := strings.TrimSpace(strings.Split(response.Header.Get("Content-Type"), ";")[0])
	return strings.EqualFold(mediaType, rawContentMediaType)
}

// readRawResponse reads the byte stream and its metadata headers.
//
// The body is bounded before it is read, so a broken or hostile Server cannot exhaust
// the CLI's memory. The declared length is compared with what arrived, because a short
// body that looks complete is the failure this check exists to catch: a caller that
// accepted it would publish a truncated file as a whole one.
//
// The truncation flag is required rather than defaulted. A missing header treated as
// `false` would stop a whole-file read after one chunk and report success, which is
// the silent truncation the flag exists to prevent.
func readRawResponse(response *http.Response, limit int64) (RawResponse, error) {
	payload, err := io.ReadAll(io.LimitReader(response.Body, limit+1))
	if err != nil {
		return RawResponse{}, fmt.Errorf("read response: %w", err)
	}
	if int64(len(payload)) > limit {
		return RawResponse{}, fmt.Errorf("response body exceeds %d bytes", limit)
	}

	if declared := response.ContentLength; declared >= 0 && int64(len(payload)) != declared {
		return RawResponse{}, fmt.Errorf("response body is %d bytes but declared %d", len(payload), declared)
	}

	flag := response.Header.Get(truncatedHeader)
	if flag == "" {
		return RawResponse{}, fmt.Errorf("response has no %s header", truncatedHeader)
	}
	truncated, err := strconv.ParseBool(flag)
	if err != nil {
		return RawResponse{}, fmt.Errorf("response has %s = %q, want true or false", truncatedHeader, flag)
	}

	return RawResponse{
		Content:   payload,
		Truncated: truncated,
		RequestID: response.Header.Get(security.RequestIDHeader),
	}, nil
}

// buildRequest validates the options and builds the signed request.
//
// It is shared by both response shapes so the two cannot drift: a second copy of the
// proof construction would be a second definition of what a valid request is, and the
// two would eventually disagree about a field. The only difference the raw flag makes
// is the Accept header, which is a request for an encoding and not a change to the
// request's meaning.
func (c *Client) buildRequest(options Options, raw bool) (*http.Request, error) {
	if err := security.ValidateKeyID(options.ClientCredential.KeyID); err != nil {
		return nil, fmt.Errorf("%w: client credential: %v", ErrUsage, err)
	}
	if err := security.ValidateCredentialSecret(options.ClientCredential.Secret); err != nil {
		return nil, fmt.Errorf("%w: client credential: %v", ErrUsage, err)
	}
	if err := security.ValidateKeyID(options.NodeCredential.KeyID); err != nil {
		return nil, fmt.Errorf("%w: node credential: %v", ErrUsage, err)
	}
	if err := security.ValidateCredentialSecret(options.NodeCredential.Secret); err != nil {
		return nil, fmt.Errorf("%w: node credential: %v", ErrUsage, err)
	}
	if err := security.ValidateNodeID(options.NodeID); err != nil {
		return nil, fmt.Errorf("%w: --node-id %v", ErrUsage, err)
	}
	if err := options.Operation.Validate(); err != nil {
		return nil, fmt.Errorf("%w: %v", ErrUsage, err)
	}
	if !options.Operation.Enabled() {
		return nil, fmt.Errorf("%w: operation %q is not enabled in this version", ErrUsage, options.Operation)
	}
	if err := security.ValidateScopeName(options.Scope); err != nil {
		return nil, fmt.Errorf("%w: %v", ErrUsage, err)
	}

	requestID := options.RequestID
	if requestID == "" {
		generated, err := security.NewRequestID()
		if err != nil {
			return nil, err
		}
		requestID = generated
	}
	if err := security.ValidateRequestID(requestID); err != nil {
		return nil, fmt.Errorf("%w: --request-id %v", ErrUsage, err)
	}

	url, err := operationURL(options.ServerURL, options.NodeID)
	if err != nil {
		return nil, fmt.Errorf("%w: %v", ErrUsage, err)
	}

	body, err := json.Marshal(requestBody{
		Operation: string(options.Operation),
		Scope:     string(options.Scope),
		Path:      options.Path,
		Offset:    options.Offset,
		Length:    options.Length,
	})
	if err != nil {
		return nil, fmt.Errorf("encode request: %w", err)
	}

	nowMS := c.now().UnixMilli()

	// The Node proof is built first, because the client proof binds its exact header
	// bytes. Building the client proof first would mean signing a header that does not
	// exist yet, and a placeholder would be a value the Server could not reproduce.
	nodeNonce, err := security.NewNonce()
	if err != nil {
		return nil, err
	}
	nodeProof := security.Proof{
		Scheme:      security.SchemeNode,
		Version:     security.ProofVersion,
		KeyID:       options.NodeCredential.KeyID,
		TimestampMS: nowMS,
		Nonce:       nodeNonce,
	}
	nodeCanonical := security.CanonicalNodeOperation(
		options.NodeID,
		nodeProof.KeyID,
		string(options.Operation),
		string(options.Scope),
		options.Path,
		options.Offset,
		options.Length,
		requestID,
		nodeProof.TimestampMS,
		nodeProof.Nonce,
	)
	nodeProof.Signature = security.Sign(options.NodeCredential.Secret, nodeCanonical)
	nodeAuthHeader := security.FormatProof(nodeProof)

	clientNonce, err := security.NewNonce()
	if err != nil {
		return nil, err
	}
	clientProof := security.Proof{
		Scheme:      security.SchemeClient,
		Version:     security.ProofVersion,
		KeyID:       options.ClientCredential.KeyID,
		TimestampMS: nowMS,
		Nonce:       clientNonce,
	}
	clientCanonical := security.CanonicalClientRequest(
		http.MethodPost,
		requestTarget(url),
		security.BodyDigest(body, true),
		security.BytesDigest([]byte(nodeAuthHeader)),
		requestID,
		clientProof.TimestampMS,
		clientProof.Nonce,
	)
	clientProof.Signature = security.Sign(options.ClientCredential.Secret, clientCanonical)

	request, err := http.NewRequest(http.MethodPost, url, bytes.NewReader(body))
	if err != nil {
		return nil, fmt.Errorf("build request: %w", err)
	}
	request.Header.Set("Content-Type", "application/json")
	request.Header.Set(security.ClientAuthHeader, security.FormatProof(clientProof))
	request.Header.Set(security.NodeAuthHeader, nodeAuthHeader)
	request.Header.Set(security.RequestIDHeader, requestID)
	if raw {
		request.Header.Set("Accept", rawContentMediaType)
	}
	return request, nil
}

// now returns the clock the proofs are built from.
func (c *Client) now() time.Time {
	if c != nil && c.Now != nil {
		return c.Now()
	}
	return time.Now()
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

// requestTarget returns the path and query the client proof signs.
//
// It is derived from the URL the request is actually sent to, so the signed value and
// the transmitted value cannot disagree. A caller that signed one path and sent
// another would produce a proof the Server refuses, and the failure would look like a
// credential problem rather than a URL problem.
func requestTarget(url string) string {
	index := strings.Index(url, "://")
	if index < 0 {
		return url
	}
	remainder := url[index+3:]
	slash := strings.IndexByte(remainder, '/')
	if slash < 0 {
		return "/"
	}
	return remainder[slash:]
}

// operationURL builds the operation URL for one node id.
//
// The node id is validated before it is placed in the path, so a value containing a
// slash or a dot segment cannot address a different endpoint. The Server validates it
// again; this check exists so a malformed value is reported locally rather than as a
// routing failure.
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
// reported as a protocol error rather than as an empty success: a caller that treated
// an unreadable answer as success would act on a result nobody produced.
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

	// The envelope is decoded into a pointer so a JSON `null` body is refused. Decoding
	// `null` into a struct value succeeds and leaves every field zero, and a zero code
	// is CodeSuccess: a body that is not an envelope would become a successful empty
	// result, which is the one answer a caller must never receive by accident.
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
