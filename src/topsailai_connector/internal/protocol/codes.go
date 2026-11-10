package protocol

import "fmt"

// Code is the business status code carried by every response. The codes are
// enumerated rather than free-form strings, because a caller must be able to
// tell "you may not" from "it is not there" from "the Node is not connected",
// and a single error string cannot express that distinction.
type Code int

const (
	// CodeSuccess means the operation happened.
	CodeSuccess Code = 0
	// CodeInvalidArgument means the request is malformed: an unknown operation,
	// a bad scope name, a rejected path or bad JSON.
	CodeInvalidArgument Code = 1001
	// CodeUnauthenticated means a secret was missing, empty or did not match.
	CodeUnauthenticated Code = 1002
	// CodeNodeOffline means there is no live connection for that node id.
	CodeNodeOffline Code = 1003
	// CodeNodeTimeout means the Node did not answer within the request timeout.
	CodeNodeTimeout Code = 1004
	// CodeDenied means the Node refused: no grant, or the policy does not allow
	// the operation on that scope.
	CodeDenied Code = 1005
	// CodeNotFound means the path does not exist inside the scope.
	CodeNotFound Code = 1006
	// CodeUnsupportedOperation means the operation is declared but not enabled in
	// this version.
	CodeUnsupportedOperation Code = 1007
	// CodeTooLarge means the response exceeds the cap or the request body
	// exceeds the limit.
	CodeTooLarge Code = 1008
	// CodeInternal means the Server failed. Details are logged, never returned.
	CodeInternal Code = 1009
)

// Name returns the stable name of a code. The name is what appears in a
// response, so a caller can match on it without depending on the number.
func (c Code) Name() string {
	switch c {
	case CodeSuccess:
		return "success"
	case CodeInvalidArgument:
		return "invalid_argument"
	case CodeUnauthenticated:
		return "unauthenticated"
	case CodeNodeOffline:
		return "node_offline"
	case CodeNodeTimeout:
		return "node_timeout"
	case CodeDenied:
		return "denied"
	case CodeNotFound:
		return "not_found"
	case CodeUnsupportedOperation:
		return "unsupported_operation"
	case CodeTooLarge:
		return "too_large"
	case CodeInternal:
		return "internal"
	default:
		return "unknown"
	}
}

// Retryable reports whether a caller may usefully retry the same request. A
// refusal is not retryable, because retrying a refusal is how a caller turns a
// policy decision into a load problem.
func (c Code) Retryable() bool {
	switch c {
	case CodeNodeOffline, CodeNodeTimeout, CodeInternal:
		return true
	default:
		return false
	}
}

// Error implements the error interface so a code can be returned where an error
// is expected without losing the code.
func (c Code) Error() string {
	return fmt.Sprintf("%s (%d)", c.Name(), int(c))
}

// IsSuccess reports whether the code means the operation happened.
func (c Code) IsSuccess() bool {
	return c == CodeSuccess
}
