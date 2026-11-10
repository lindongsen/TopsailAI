package protocol

import (
	"fmt"

	"topsailai_connector/internal/security"
)

// Operation names one capability the Node exposes. The Node decides which
// operations it offers; the Server may only call an operation the Node
// advertised, so an unadvertised call is rejected instead of attempted.
type Operation string

const (
	// OperationFileRead reads a byte range of one file inside a scope.
	OperationFileRead Operation = "file.read"
	// OperationFileWrite writes a byte range of one file inside a scope.
	OperationFileWrite Operation = "file.write"
	// OperationFileList lists one directory inside a scope.
	OperationFileList Operation = "file.list"
	// OperationFileStat reports metadata of one path inside a scope.
	OperationFileStat Operation = "file.stat"
	// OperationCommandExec runs one allowlisted argv array inside a scope.
	OperationCommandExec Operation = "command.exec"
)

// Permission maps an operation to the permission it needs. The mapping lives
// here so both sides agree on which permission an operation consumes, and an
// operation added without a mapping is refused instead of running unchecked.
func (o Operation) Permission() (security.Permission, bool) {
	switch o {
	case OperationFileRead:
		return security.PermissionRead, true
	case OperationFileWrite:
		return security.PermissionWrite, true
	case OperationFileList:
		return security.PermissionList, true
	case OperationFileStat:
		return security.PermissionStat, true
	case OperationCommandExec:
		return security.PermissionExec, true
	default:
		return "", false
	}
}

// Enabled reports whether this version implements the operation.
//
// A declared operation and an implemented operation are different things. The
// wire contract declares `file.write` and `command.exec` so a second-version
// policy parses and a second-version client can be written against a stable
// vocabulary, but this version refuses them. The refusal is at dispatch rather
// than at advertisement, so it does not depend on the Server honouring what the
// Node advertised.
func (o Operation) Enabled() bool {
	switch o {
	case OperationFileRead, OperationFileList, OperationFileStat:
		return true
	default:
		return false
	}
}

// Validate checks that an operation is a known name. It does not check whether
// the operation is enabled, because "unknown" and "not implemented yet" are
// different answers and a caller needs to tell them apart.
func (o Operation) Validate() error {
	if _, ok := o.Permission(); !ok {
		return fmt.Errorf("operation %q is not in the vocabulary", o)
	}
	return nil
}

// Request is one operation invocation.
//
// NodeID is the address the request is for and NodeToken is the secret that
// authorizes it. They are separate fields because they are different kinds of
// value: the identifier may be logged, audited and routed on, and the token may
// never be. The CLI receives them as one dot-separated pair and splits the pair
// before sending, so the Server never holds a value that is half public and half
// secret.
//
// Scope names the area the Node resolves locally and Path is always relative to
// it; the Node rejects anything that escapes the scope. The Node authorizes the
// call itself instead of trusting the Server's claim, because the Server's
// authentication proves only that the caller may use the Server.
type Request struct {
	NodeID    string          `json:"node_id"`
	NodeToken security.Secret `json:"node_token"`
	Operation Operation       `json:"operation"`
	Scope     security.Scope  `json:"scope"`
	Path      string          `json:"path,omitempty"`
	Offset    int64           `json:"offset,omitempty"`
	Length    int64           `json:"length,omitempty"`
	Data      []byte          `json:"data,omitempty"`
	Argv      []string        `json:"argv,omitempty"`
}

// Response is the result of one Request. A non-success Code means the operation
// did not happen; Data is only meaningful when Code is CodeSuccess.
//
// The code is an enumerated value rather than a free-form string, because a
// string cannot distinguish a refusal from a missing file, and collapsing those
// two would let a caller probe for the existence of a file it may not read.
type Response struct {
	Code Code   `json:"code"`
	Data []byte `json:"data,omitempty"`
}

// Succeeded reports whether the operation happened.
func (r Response) Succeeded() bool {
	return r.Code.IsSuccess()
}

// Failure builds a response that carries a code and no data, so a refusal can
// never be mistaken for a partial success.
func Failure(code Code) Response {
	return Response{Code: code}
}

// Success builds a response that carries data and the success code.
func Success(data []byte) Response {
	return Response{Code: CodeSuccess, Data: data}
}
