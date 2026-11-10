package server

import (
	"bytes"
	"context"
	"crypto/rand"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"log/slog"
	"net/http"
	"strings"
	"time"

	"topsailai_connector/internal/protocol"
	"topsailai_connector/internal/security"
)

// MaxRequestBodyBytes bounds the request body the CLI API accepts.
//
// The bound exists because the body is read before it is parsed, so an unbounded
// read is a caller deciding how much memory the Server spends. A request larger
// than this is refused with too_large rather than truncated, because a truncated
// JSON document is a parse error that hides the real cause.
const MaxRequestBodyBytes = 1 << 20

// OperationPathPrefix is the path the CLI API is served under.
//
// The prefix is part of the contract, not an implementation detail: a reverse
// proxy that forwards /v1/ and /channel differently depends on it, so changing it
// is a breaking change to the deployment.
const OperationPathPrefix = "/v1/nodes/"

// OperationPathSuffix completes the operation path.
const OperationPathSuffix = "/operations"

// Forwarder sends one request to one Node and returns its answer.
//
// The interface exists so the HTTP surface does not depend on the channel
// transport. The HTTP layer decides who may call and which Node to reach; the
// transport decides how a frame travels. Keeping them apart means the routing and
// authentication rules can be tested without a socket.
//
// The node token is a parameter, not a field of any struct that outlives the
// call. That is the shape the "never stores a Node token" rule requires: the value
// exists only for the duration of the forward.
type Forwarder interface {
	Forward(ctx context.Context, nodeID string, request protocol.Request) (protocol.Response, error)
}

// Handler serves the CLI API.
//
// It authenticates the caller with the Server's own client token, finds the live
// connection for the requested node id and forwards the request unchanged. It
// never decides whether an operation is allowed, because the policy that answers
// that question lives on the Node and the Server never sees it.
type Handler struct {
	config    Config
	registry  *Registry
	forwarder Forwarder
	logger    *slog.Logger
}

// NewHandler builds the CLI API handler.
//
// A nil logger falls back to the default logger. A nil registry or a nil
// forwarder is not substituted, because a handler that cannot route has no answer
// to give and inventing one would be inventing a routing decision.
func NewHandler(config Config, registry *Registry, forwarder Forwarder, logger *slog.Logger) *Handler {
	if logger == nil {
		logger = slog.Default()
	}
	return &Handler{config: config, registry: registry, forwarder: forwarder, logger: logger}
}

// envelope is the project-wide response format.
//
// Every answer uses it, including a refusal, so a caller parses one shape. The
// code is authoritative: the HTTP status is a courtesy for a proxy or a browser
// and never carries information the envelope does not.
type envelope struct {
	Code      protocol.Code   `json:"code"`
	Message   string          `json:"message"`
	Data      json.RawMessage `json:"data,omitempty"`
	RequestID string          `json:"request_id"`
	Timestamp int64           `json:"timestamp"`
}

// ServeHTTP routes one CLI request.
//
// The check order is fixed and each step is a refusal:
//
//  0. The handler must be able to route. A handler built without a registry or a
//     forwarder refuses everything instead of panicking, because a crash on the
//     request path is a denial of service caused by a wiring mistake.
//  1. The method must be POST. A read is a POST because the request carries a
//     secret in a header and a body, and a GET would put the operation in a URL
//     that proxies and shell histories record.
//  2. The path must name a node id, and the id must be well formed. A malformed
//     id is refused before any secret is compared, so a typo does not become a
//     credential test.
//  3. The client token must match. This runs before the node token is read,
//     because the Server's own gate answers first and a caller that fails it
//     learns nothing about the Node.
//  4. The body must be JSON within the size cap and must decode strictly.
//  5. The node token must be present. It is not validated here: the Server does
//     not know the value, and claiming to have checked it would be a lie about
//     the one thing the caller relies on.
//  6. A live connection must exist for the node id.
//  7. The request is forwarded and the Node's answer is relayed unchanged.
func (h *Handler) ServeHTTP(writer http.ResponseWriter, request *http.Request) {
	requestID := requestIDOf(request)

	if h.registry == nil || h.forwarder == nil {
		h.refuse(writer, requestID, protocol.CodeInternal, "handler is not wired to a registry and a forwarder")
		return
	}

	if request.Method != http.MethodPost {
		h.refuse(writer, requestID, protocol.CodeInvalidArgument, "method must be POST")
		return
	}

	nodeID, ok := nodeIDFromPath(request.URL.Path)
	if !ok {
		h.refuse(writer, requestID, protocol.CodeInvalidArgument, "path must be "+OperationPathPrefix+"{node_id}"+OperationPathSuffix)
		return
	}
	if err := security.ValidateNodeID(nodeID); err != nil {
		h.refuse(writer, requestID, protocol.CodeInvalidArgument, "node id is malformed")
		return
	}

	if !h.clientTokenMatches(request) {
		h.refuse(writer, requestID, protocol.CodeUnauthenticated, "client token is missing or does not match")
		return
	}

	if !isJSONContentType(request.Header.Get("Content-Type")) {
		h.refuse(writer, requestID, protocol.CodeInvalidArgument, "content type must be application/json")
		return
	}

	payload, err := readBody(request)
	if err != nil {
		h.refuse(writer, requestID, CodeOfForwardError(err), "request body was refused")
		return
	}

	forwarded, err := decodeRequest(payload)
	if err != nil {
		h.refuse(writer, requestID, protocol.CodeInvalidArgument, "request body is malformed")
		return
	}

	nodeToken := security.Secret(request.Header.Get("X-Connector-Node-Token"))
	if nodeToken == "" {
		h.refuse(writer, requestID, protocol.CodeUnauthenticated, "node token header is missing")
		return
	}

	if _, live := h.registry.Lookup(nodeID); !live {
		h.refuse(writer, requestID, protocol.CodeNodeOffline, "no live connection for that node id")
		return
	}

	forwarded.NodeID = nodeID
	forwarded.NodeToken = nodeToken

	response, err := h.forward(request.Context(), nodeID, forwarded)
	if err != nil {
		h.refuse(writer, requestID, CodeOfForwardError(err), "forwarding failed")
		return
	}

	h.write(writer, requestID, response)
}

// forward sends the request with the configured timeout.
//
// The timeout bounds one forwarded request, not the channel: a channel that has
// been open for a month says nothing about whether the Node is answering now. A
// request that exceeds it is answered with node_timeout and the Node's eventual
// answer is discarded, because the caller has already been told the request
// failed.
func (h *Handler) forward(parent context.Context, nodeID string, request protocol.Request) (protocol.Response, error) {
	timeout := h.config.RequestTimeout
	if timeout <= 0 {
		timeout = DefaultRequestTimeout
	}
	ctx, cancel := context.WithTimeout(parent, timeout)
	defer cancel()

	response, err := h.forwarder.Forward(ctx, nodeID, request)
	if err != nil {
		return protocol.Response{}, err
	}
	return response, nil
}

// clientTokenMatches reports whether the Authorization header carries the
// configured client token.
//
// The comparison is the constant time one from the security package, and a
// missing header is a mismatch rather than a skip. The header is parsed for the
// Bearer scheme only: accepting a bare token would make the scheme optional and
// two spellings of one credential is one spelling too many.
func (h *Handler) clientTokenMatches(request *http.Request) bool {
	header := request.Header.Get("Authorization")
	const scheme = "Bearer "
	if !strings.HasPrefix(header, scheme) {
		return false
	}
	presented := security.Secret(strings.TrimPrefix(header, scheme))
	return h.config.ClientToken.Equal(presented)
}

// nodeIDFromPath extracts the node id from the operation path.
//
// The path is matched exactly rather than by prefix, so a request to
// /v1/nodes/{id}/operations/extra is refused instead of being treated as the
// operation path with a suffix nobody defined.
func nodeIDFromPath(path string) (string, bool) {
	if !strings.HasPrefix(path, OperationPathPrefix) {
		return "", false
	}
	remainder := strings.TrimPrefix(path, OperationPathPrefix)
	if !strings.HasSuffix(remainder, OperationPathSuffix) {
		return "", false
	}
	nodeID := strings.TrimSuffix(remainder, OperationPathSuffix)
	if nodeID == "" || strings.Contains(nodeID, "/") {
		return "", false
	}
	return nodeID, true
}

// isJSONContentType reports whether the content type is JSON.
//
// A missing content type is refused rather than assumed, because assuming JSON
// would accept a form post that happens to parse.
func isJSONContentType(value string) bool {
	mediaType := strings.TrimSpace(strings.Split(value, ";")[0])
	return strings.EqualFold(mediaType, "application/json")
}

// readBody reads the body within the size cap.
//
// One byte beyond the cap is read on purpose, so a body of exactly the cap is
// accepted and a body over it is detected rather than silently truncated.
//
// An absent body yields an empty payload rather than an error, so it fails at
// decoding as a malformed request. Reporting it as too_large would tell the
// caller its body was oversized when it sent none.
func readBody(request *http.Request) ([]byte, error) {
	if request.Body == nil {
		return nil, nil
	}
	limited := io.LimitReader(request.Body, MaxRequestBodyBytes+1)
	payload, err := io.ReadAll(limited)
	if err != nil {
		return nil, fmt.Errorf("%w: %v", errBodyUnreadable, err)
	}
	if len(payload) > MaxRequestBodyBytes {
		return nil, errBodyTooLarge
	}
	return payload, nil
}

// requestBody is the body the CLI API accepts.
//
// It deliberately omits the node id and the node token. Those arrive in the path
// and in a header, and a body that could also carry them would be a second place
// an identity can be claimed. Because the decoder refuses unknown fields, a body
// containing `node_id` or `node_token` is refused rather than silently ignored,
// so a caller cannot believe it set an identity the Server took from elsewhere.
type requestBody struct {
	Operation protocol.Operation `json:"operation"`
	Scope     security.Scope     `json:"scope"`
	Path      string             `json:"path,omitempty"`
	Offset    int64              `json:"offset,omitempty"`
	Length    int64              `json:"length,omitempty"`
	Data      []byte             `json:"data,omitempty"`
	Argv      []string           `json:"argv,omitempty"`
}

// decodeRequest decodes the body into a wire request.
//
// Unknown fields are refused rather than ignored, so a caller that misspells a
// field learns about it instead of sending a request that silently does less than
// it says. A second JSON document in the same body is refused for the same reason:
// accepting the first and ignoring the rest hides a caller's mistake.
func decodeRequest(payload []byte) (protocol.Request, error) {
	decoder := json.NewDecoder(bytes.NewReader(payload))
	decoder.DisallowUnknownFields()

	// The body is decoded into a pointer so a JSON null is refused. Decoding null
	// into a struct value succeeds and leaves every field empty, which would turn
	// a body that is not an object into a request with no operation and let it
	// travel to the Node as a malformed request the Server had already accepted.
	var body *requestBody
	if err := decoder.Decode(&body); err != nil {
		return protocol.Request{}, err
	}
	if body == nil {
		return protocol.Request{}, errors.New("body must be a JSON object")
	}
	if err := decoder.Decode(new(json.RawMessage)); !errors.Is(err, io.EOF) {
		return protocol.Request{}, errors.New("body carries more than one JSON document")
	}

	return protocol.Request{
		Operation: body.Operation,
		Scope:     body.Scope,
		Path:      body.Path,
		Offset:    body.Offset,
		Length:    body.Length,
		Data:      body.Data,
		Argv:      body.Argv,
	}, nil
}

// write relays a Node answer in the envelope.
func (h *Handler) write(writer http.ResponseWriter, requestID string, response protocol.Response) {
	body := envelope{
		Code:      response.Code,
		Message:   messageOf(response.Code),
		RequestID: requestID,
		Timestamp: time.Now().UnixMilli(),
	}
	if len(response.Data) > 0 {
		body.Data = json.RawMessage(response.Data)
	}
	writeJSON(writer, statusOf(response.Code), body)
}

// refuse logs the reason and answers with the code and no data.
//
// The log line names the request id, the code and the reason, and never a secret.
// The reason is written for an operator and may name a header or a path; it never
// carries a value from either secret header.
func (h *Handler) refuse(writer http.ResponseWriter, requestID string, code protocol.Code, reason string) {
	h.logger.Warn("connector-server refused a request",
		"request_id", requestID,
		"code", code.Name(),
		"reason", reason,
	)
	writeJSON(writer, statusOf(code), envelope{
		Code:      code,
		Message:   messageOf(code),
		RequestID: requestID,
		Timestamp: time.Now().UnixMilli(),
	})
}

// writeJSON writes one envelope.
func writeJSON(writer http.ResponseWriter, status int, body envelope) {
	writer.Header().Set("Content-Type", "application/json")
	writer.WriteHeader(status)
	encoder := json.NewEncoder(writer)
	encoder.SetEscapeHTML(false)
	_ = encoder.Encode(body)
}

// statusOf maps a code to an HTTP status.
//
// The envelope code is authoritative and the status is a courtesy, so a proxy or
// a browser can react without parsing the body. The mapping is deliberately
// coarse: two codes that a caller must distinguish share a status, because the
// distinction lives in the envelope and a status that tried to carry it would be
// a second, weaker copy of the contract.
func statusOf(code protocol.Code) int {
	switch code {
	case protocol.CodeSuccess:
		return http.StatusOK
	case protocol.CodeInvalidArgument, protocol.CodeUnsupportedOperation:
		return http.StatusBadRequest
	case protocol.CodeUnauthenticated:
		return http.StatusUnauthorized
	case protocol.CodeDenied:
		return http.StatusForbidden
	case protocol.CodeNotFound:
		return http.StatusNotFound
	case protocol.CodeTooLarge:
		return http.StatusRequestEntityTooLarge
	case protocol.CodeNodeOffline:
		return http.StatusServiceUnavailable
	case protocol.CodeNodeTimeout:
		return http.StatusGatewayTimeout
	default:
		return http.StatusInternalServerError
	}
}

// messageOf renders the human readable message for a code.
//
// The message is fixed per code and never includes a detail string. A detail
// string is where an absolute path or a scope name leaks, and the caller does not
// need it: the code already says what happened.
func messageOf(code protocol.Code) string {
	switch code {
	case protocol.CodeSuccess:
		return "success"
	case protocol.CodeInvalidArgument:
		return "the request is malformed"
	case protocol.CodeUnauthenticated:
		return "the caller is not authenticated"
	case protocol.CodeNodeOffline:
		return "the node is not connected"
	case protocol.CodeNodeTimeout:
		return "the node did not answer in time"
	case protocol.CodeDenied:
		return "the node refused the operation"
	case protocol.CodeNotFound:
		return "the path does not exist inside the scope"
	case protocol.CodeUnsupportedOperation:
		return "the operation is not supported in this version"
	case protocol.CodeTooLarge:
		return "the request or response exceeds the limit"
	default:
		return "the server failed"
	}
}

// requestIDOf returns the caller's correlation id or a fresh one.
//
// A caller supplied id is echoed so a request can be followed across two systems.
// It is not trusted for anything else, and it is bounded so a caller cannot use it
// to fill a log line.
func requestIDOf(request *http.Request) string {
	if supplied := request.Header.Get("X-Request-Id"); supplied != "" && len(supplied) <= 128 {
		return supplied
	}
	return newRequestID()
}

// newRequestID returns a random correlation id.
func newRequestID() string {
	buffer := make([]byte, 8)
	if _, err := rand.Read(buffer); err != nil {
		return "req_unknown"
	}
	return "req_" + hex.EncodeToString(buffer)
}

// errBodyTooLarge reports a body over the cap.
var errBodyTooLarge = errors.New("request body exceeds the limit")

// errBodyUnreadable reports a body that could not be read.
var errBodyUnreadable = errors.New("request body could not be read")

// CodeOfForwardError maps a body or forwarding failure to a wire code.
//
// An unclassified failure is internal rather than a guess, because a guessed code
// tells the caller something the Server does not know.
func CodeOfForwardError(err error) protocol.Code {
	switch {
	case err == nil:
		return protocol.CodeSuccess
	case errors.Is(err, errBodyTooLarge):
		return protocol.CodeTooLarge
	case errors.Is(err, errBodyUnreadable):
		return protocol.CodeInvalidArgument
	case errors.Is(err, context.DeadlineExceeded):
		return protocol.CodeNodeTimeout
	case errors.Is(err, ErrNodeOffline):
		return protocol.CodeNodeOffline
	default:
		return protocol.CodeInternal
	}
}

// ErrNodeOffline reports that no live connection exists for a node id.
var ErrNodeOffline = errors.New("node is offline")
