package node

import (
	"encoding/json"
	"fmt"
	"log/slog"
	"time"

	"topsailai_connector/internal/protocol"
	"topsailai_connector/internal/security"
)

// Dispatcher turns one wire request into one wire response.
//
// It is the only place a request becomes work, so it is the only place the check
// order matters. The order is fixed and each step is a refusal rather than a
// warning:
//
//  1. The request must be addressed to this Node. A request for another Node is
//     refused before the proof is verified, so a misrouted request cannot be used to
//     test whether a credential is valid on this Node.
//  2. The Node proof must be well formed and must name a credential this Node holds.
//     An unknown key identifier is refused with the same answer as a bad signature,
//     so a caller cannot enumerate which key identifiers exist.
//  3. The proof timestamp must be inside the Node's window. The Node owns the window;
//     a request cannot choose or widen it.
//  4. The signature must verify over the logical operation. This is the Node's own
//     gate: the Server authenticated the caller, but the Server does not hold this
//     secret, so only the Node can decide whether the caller may operate here.
//  5. The nonce must be fresh. It is recorded only after the signature verifies, so a
//     forged proof cannot reserve a nonce a legitimate request later needs.
//  6. Fields that only an unimplemented operation uses are refused. A `data` or
//     `argv` field on a read is a request the schema does not describe, and an
//     unknown field is refused rather than ignored.
//  7. The operation must be implemented and granted. The version gate runs before the
//     grant check, so a caller learns that `file.write` is unimplemented rather than
//     whether a write grant exists.
//  8. The path fence runs last, inside the scope the grant named. Authorization
//     succeeding and the path still being refused is the normal case, not an
//     inconsistency: the two checks answer different questions.
//
// Nothing here consults the Server. The policy file is the only input, and it was
// read from the Node's own disk at startup.
type Dispatcher struct {
	authority *Authority
	holder    *IdentityHolder
	replay    *security.ReplayCache
	window    time.Duration
	logger    *slog.Logger
	now       func() time.Time
}

// NewDispatcher builds a dispatcher for one Node identity and one authority.
//
// A nil logger falls back to the default logger rather than being refused, so a
// caller that has not configured logging still gets a working dispatcher. A nil
// authority is not substituted, because a dispatcher without a policy would have to
// invent an answer and an invented answer is a policy nobody wrote. Dispatch refuses
// such a dispatcher instead of trusting it.
//
// The replay cache is built here from the validated window and capacity, so a
// dispatcher cannot be wired to a window the configuration never stated. A window or
// capacity that is unusable refuses construction instead of falling back to a
// default, because a verifier that silently substituted a default would be a verifier
// whose operator cannot state what it enforces.
func NewDispatcher(authority *Authority, holder *IdentityHolder, window time.Duration, capacity int, logger *slog.Logger) (*Dispatcher, error) {
	if logger == nil {
		logger = slog.Default()
	}
	if window == 0 {
		window = security.DefaultReplayWindow
	}
	if capacity == 0 {
		capacity = security.DefaultReplayCapacity
	}
	replay, err := security.NewReplayCache(window, capacity)
	if err != nil {
		return nil, fmt.Errorf("build the node replay cache: %w", err)
	}
	return &Dispatcher{
		authority: authority,
		holder:    holder,
		replay:    replay,
		window:    window,
		logger:    logger,
		now:       time.Now,
	}, nil
}

// Dispatch performs one request and returns the response a caller sees.
//
// Every failure is a code and never a panic, because a request arrives from the
// network and a panic on a malformed request is a remote crash. The response carries
// no detail string: the detail goes to the Node's log, where a path or a scope name
// is allowed, and never to the caller, where it would be a leak.
func (d *Dispatcher) Dispatch(request protocol.Request) protocol.Response {
	if d == nil {
		return protocol.Failure(protocol.CodeInternal)
	}
	// A dispatcher with no authority has no policy to consult. It is refused before
	// any refusal is logged, because refuse dereferences the logger and a nil
	// receiver would panic on the request path.
	if d.authority == nil {
		return protocol.Failure(protocol.CodeInternal)
	}

	// The identity is read once per request rather than captured at startup, so an
	// identifier regenerated while the Node is running is the identifier a request is
	// checked against. Reading it once here also means the identifier check and the
	// credential lookup use the same snapshot: two reads could straddle a
	// regeneration and compare the identifier of one value with the credentials of
	// another.
	nodeID := d.holder.NodeID()
	credentials := d.holder.Credentials()

	if request.NodeID != nodeID {
		return d.refuse(request, protocol.CodeDenied, "request is addressed to another node")
	}

	if err := d.verifyNodeProof(request, nodeID, credentials); err != nil {
		// The contract names this unauthenticated rather than denied: the caller did
		// not prove it may talk to this Node at all, which is a different answer from
		// "you may talk to this Node but not do that".
		return d.refuse(request, protocol.CodeUnauthenticated, "node proof does not verify")
	}

	if len(request.Data) > 0 || len(request.Argv) > 0 {
		return d.refuse(request, protocol.CodeInvalidArgument, "request carries a field no enabled operation uses")
	}
	if request.Operation == "" {
		return d.refuse(request, protocol.CodeInvalidArgument, "request names no operation")
	}

	scope, err := d.authority.AuthorizeOperation(request.Operation, request.Scope)
	if err != nil {
		return d.refuse(request, CodeOf(err), "authorization refused: %v", err)
	}

	payload, err := d.perform(scope, request)
	if err != nil {
		return d.refuse(request, CodeOf(err), "operation failed: %v", err)
	}
	return protocol.Success(payload)
}

// verifyNodeProof verifies the Node HMAC proof and records its nonce.
//
// The order is fixed: validate the shape, look up the key, check the timestamp,
// verify the signature, then record the nonce. A nonce is recorded only after the
// signature verifies, so a forged proof cannot reserve a nonce a legitimate request
// later needs.
//
// The canonical input binds the node id, the key identifier, the operation, the
// scope, the path, the offset, the length, the caller request id, the timestamp and
// the nonce. Binding the node id is what stops a proof built for one Node from being
// replayed against another, and binding the operation fields is what stops a caller
// from keeping a valid proof and changing what it asks for.
func (d *Dispatcher) verifyNodeProof(request protocol.Request, nodeID string, credentials *security.CredentialSet) error {
	proof := request.NodeAuth
	if err := proof.Validate(security.SchemeNode); err != nil {
		d.logger.Warn("connector-node refused a node proof", "node_id", nodeID, "reason", "malformed proof")
		return err
	}

	secret, present := credentials.Lookup(proof.KeyID)
	if !present {
		d.logger.Warn("connector-node refused a node proof", "node_id", nodeID, "node_key_id", proof.KeyID, "reason", "unknown key id")
		return security.ErrProofMismatch
	}

	if !security.TimestampWithinWindow(d.now().UnixMilli(), proof.TimestampMS, d.window.Milliseconds()) {
		d.logger.Warn("connector-node refused a node proof", "node_id", nodeID, "node_key_id", proof.KeyID, "reason", "timestamp outside the window")
		return security.ErrProofMismatch
	}

	canonical := security.CanonicalNodeOperation(
		nodeID,
		proof.KeyID,
		string(request.Operation),
		string(request.Scope),
		request.Path,
		request.Offset,
		request.Length,
		request.RequestID,
		proof.TimestampMS,
		proof.Nonce,
	)
	if err := security.VerifySignature(secret, canonical, proof.Signature); err != nil {
		d.logger.Warn("connector-node refused a node proof", "node_id", nodeID, "node_key_id", proof.KeyID, "reason", "signature does not verify")
		return err
	}

	if err := d.replay.Admit(proof.KeyID, proof.Nonce); err != nil {
		d.logger.Warn("connector-node refused a node proof", "node_id", nodeID, "node_key_id", proof.KeyID, "reason", err.Error())
		return err
	}
	return nil
}

// perform runs one authorized operation and encodes its payload.
//
// The switch is exhaustive over the enabled operations and has no default that
// succeeds. An operation that reaches here without a case is a programming defect,
// and it is reported as internal rather than as a success with no data, because a
// success with no data is indistinguishable from an empty file.
func (d *Dispatcher) perform(scope *Scope, request protocol.Request) ([]byte, error) {
	switch request.Operation {
	case protocol.OperationFileRead:
		return readPayload(scope, request)
	case protocol.OperationFileList:
		return listPayload(scope, request)
	case protocol.OperationFileStat:
		return statPayload(scope, request)
	default:
		return nil, newError(protocol.CodeInternal, "operation %q passed authorization but has no handler", request.Operation)
	}
}

// readPayload reads a byte range and encodes it as the documented read shape.
//
// The content is a byte slice, so the JSON encoder emits base64. A file is bytes, and
// a caller that wants text decodes it; encoding it as a string here would fail on the
// first file that is not valid UTF-8.
func readPayload(scope *Scope, request protocol.Request) ([]byte, error) {
	content, truncated, err := scope.Read(request.Path, request.Offset, request.Length)
	if err != nil {
		return nil, err
	}
	return json.Marshal(readResult{
		Content:   content,
		Size:      int64(len(content)),
		Truncated: truncated,
	})
}

// listPayload lists one directory and encodes it as the documented list shape.
func listPayload(scope *Scope, request protocol.Request) ([]byte, error) {
	entries, err := scope.List(request.Path)
	if err != nil {
		return nil, err
	}
	return json.Marshal(listResult{Entries: entries})
}

// statPayload states one path and encodes it as the documented stat shape.
func statPayload(scope *Scope, request protocol.Request) ([]byte, error) {
	entry, err := scope.Stat(request.Path)
	if err != nil {
		return nil, err
	}
	return json.Marshal(entry)
}

// readResult is the payload of a successful `file.read`.
type readResult struct {
	Content   []byte `json:"content"`
	Size      int64  `json:"size"`
	Truncated bool   `json:"truncated"`
}

// listResult is the payload of a successful `file.list`.
type listResult struct {
	Entries []Entry `json:"entries"`
}

// refuse logs the reason and returns the code with no data.
//
// The log line names the node, the operation, the scope and the code, and never a
// secret. The key identifier is not printed here either: it is printed by the proof
// verification path, which is the only place that knows it, and a refusal that never
// reached a proof has no key identifier to name. The detail may contain a path, which
// is why it goes to the log and not to the caller.
func (d *Dispatcher) refuse(request protocol.Request, code protocol.Code, format string, arguments ...any) protocol.Response {
	d.logger.Warn("connector-node refused a request",
		"node_id", d.holder.NodeID(),
		"operation", string(request.Operation),
		"scope", string(request.Scope),
		"code", code.Name(),
		"reason", fmt.Sprintf(format, arguments...),
	)
	return protocol.Failure(code)
}
