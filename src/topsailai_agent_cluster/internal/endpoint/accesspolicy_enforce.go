package endpoint

import (
	"context"
	"errors"
	"fmt"

	"topsailai_agent_cluster/internal/channel"
	"topsailai_agent_cluster/internal/protocol"
	"topsailai_agent_cluster/internal/security"
)

// policyDeniedCode is the single refusal code for every operation the Endpoint
// policy refuses.
//
// One code covers every operation rather than one code per operation, because
// the command path already answers a refusal with this code
// (internal/endpoint/executor.go). A second vocabulary for reads would mean the
// same refusal had two names, and a client would have to recognise a new code
// every time an operation was added. The message names the refused operation, so
// the caller still learns which request was refused; that is not new information,
// because it asked for that operation.
const policyDeniedCode = protocol.PolicyDenied

// credentialRejectedCode is the refusal code for a caller whose credential could
// not be proven at all.
//
// It is a second code rather than a second message on the first one, because the
// two refusals have different remedies: a policy refusal means the credential was
// proven and its grants do not cover the operation, while this code means the
// credential could not be proven, so the operator must fix the credential itself.
// Reporting the second as the first sends the operator to a policy file that is
// already correct, which is the failure this code exists to prevent.
const credentialRejectedCode = protocol.CredentialRejected

// credentialError marks a refusal that happened because the credential could not
// be proven, before the access policy was consulted.
//
// It wraps the underlying cause instead of replacing it, so the specific reason
// (a missing signature, an unknown key identifier, a clock outside the accepted
// window, a replayed nonce or a credential form the configured mode does not
// accept) still reaches the log and the caller. The wrapper carries only the
// class, so one classification decides the code and the log message on both the
// read path and the command path.
type credentialError struct {
	cause error
}

func (e *credentialError) Error() string { return e.cause.Error() }

func (e *credentialError) Unwrap() error { return e.cause }

// RefusalCode names the refusal class of one policy-hook error.
//
// It is exported because the command path assembles its own policy hook in the
// Endpoint entry point and must answer with the same code the read path answers
// with. A second copy of this switch would be a second place to keep the two
// classes in step, and the two would drift the moment a class was added.
func RefusalCode(err error) string {
	var credential *credentialError
	if errors.As(err, &credential) {
		return credentialRejectedCode
	}
	return policyDeniedCode
}

// CredentialRefusal marks one error as an authentication failure rather than a
// policy decision.
//
// It is exported for the same reason RefusalCode is: the command path verifies the
// credential in the Endpoint entry point, so that call site must be able to say
// which class its error belongs to. Without it the entry point would return a bare
// verification error, RefusalCode would classify it as a policy refusal, and a
// caller that could not prove its credential would be told to edit a policy file.
//
// A nil error stays nil, so a caller can wrap unconditionally.
func CredentialRefusal(err error) error {
	if err == nil {
		return nil
	}
	return &credentialError{cause: err}
}

// permitOperation decides whether the caller behind one frame may exercise one
// operation on this Endpoint.
//
// The check runs before the transport is consulted and before the handler looks
// at the request, so a refused caller cannot infer from a status code or a
// response time whether the Endpoint has an adapter, a provider or a reachable
// session. A refusal therefore reveals nothing about the machine beyond the fact
// that this token may not ask.
//
// A nil policy permits everything, which is the state of an Endpoint that was
// never pointed at a policy directory.
func (s *Service) permitOperation(frame channel.Frame, operation string) error {
	if s.accessPolicy == nil {
		return nil
	}
	keyID, token, err := VerifyEndpointCredential(credentialOf(frame), s.authMode, s.verifier(), s.endpointID, operation, frame.EndpointRequestDigest)
	if err != nil {
		// The failure is wrapped so the caller can tell an authentication
		// refusal from a grant refusal. The policy is never consulted here,
		// which is the ordering this function exists to guarantee.
		return &credentialError{cause: err}
	}
	return s.accessPolicy.PermitCredential(s.endpointID, keyID, token, operation)
}

// verifier returns the verifier this Service must check a signature against.
//
// It is derived from the policy in force rather than captured once at
// construction, because a policy reload replaces the declared secrets. A verifier
// captured at startup would keep accepting a secret the operator had already
// rotated away, which is the one failure a rotation exists to prevent.
//
// The fallback covers an Endpoint with no policy directory: it holds no secrets,
// so it can verify nothing, and HMAC mode therefore refuses every caller. That is
// the fail-closed direction, and it is why an Endpoint that enforces HMAC must be
// given a policy directory.
func (s *Service) verifier() *security.Verifier {
	if s.accessPolicy != nil {
		return s.accessPolicy.Verifier(s.signatureWindow)
	}
	return s.credentialVerifier
}

// VerifyEndpointCredential proves one Endpoint credential and returns the identity
// the policy must be evaluated against.
//
// It is exported because two independent call paths must make the same decision:
// the read path inside the Service, and the command path whose policy hook is
// assembled by the Endpoint entry point. A second copy of this switch in the
// entry point would be a second place to keep the mode rules in step, and the two
// would drift the moment a mode was added.
//
// Exactly one of the two returned identities is non-empty, and which one is
// decided by the mode. In HMAC mode the identity is the verified key identifier,
// never the presented secret: the policy file names the key identifier, so a
// leaked policy file does not leak a usable credential. In bearer mode the
// identity is the presented token, which is the existing behaviour and the reason
// bearer mode is the compatibility mode rather than the default.
func VerifyEndpointCredential(credential security.EndpointCredential, authMode string, verifier *security.Verifier, endpointID, operation, requestDigest string) (string, string, error) {
	mode := security.AuthMode(authMode)
	if mode == "" {
		mode = security.DefaultAuthMode
	}
	switch mode {
	case security.ModeBearer:
		// A signed credential is refused in bearer mode rather than accepted as
		// a token. Its signature field is not a secret the policy could match, so
		// accepting it would compare a proof against a secret and always fail
		// with a message that blames the caller's grants.
		if credential.IsHMAC() {
			return "", "", fmt.Errorf("endpoint requires a bearer credential but a signed credential was presented")
		}
		return "", credential.Token, nil
	case security.ModeHMAC:
		if verifier == nil {
			return "", "", fmt.Errorf("endpoint requires a signed credential but no verifier is configured")
		}
		if err := security.VerifyEndpointCredential(verifier, credential, operation, endpointID, requestDigest); err != nil {
			return "", "", err
		}
		return credential.KeyID, "", nil
	default:
		return "", "", fmt.Errorf("unsupported endpoint authentication mode %q", mode)
	}
}

// credentialOf returns the frame's Endpoint credential, or the zero credential
// when the frame carried none.
//
// It exists so the command path and the read path read the envelope the same way.
// A nil pointer means "nothing was presented", which the verifier refuses in HMAC
// mode; dereferencing it without this helper would panic on exactly the request
// that must be refused.
func credentialOf(frame channel.Frame) security.EndpointCredential {
	if frame.EndpointCredential == nil {
		return security.EndpointCredential{}
	}
	return *frame.EndpointCredential
}

// refuseFrame logs one refusal and returns the code that names its class.
//
// The class decides both the code and the message, because the two refusals have
// different remedies. A credential that could not be proven is an authentication
// failure: the operator must fix the credential, and the log says so. A credential
// that was proven but does not cover the operation is a policy decision: the
// operator must edit the policy file. Reporting the first as the second sends the
// operator to a policy file that is already correct, which is exactly the
// misdirection this split removes.
//
// The log line names the operation and the request, never the token: a token is a
// secret, and a log that records it turns every log reader into a credential
// holder. The request ID is enough to correlate the refusal with the caller's own
// record.
func (s *Service) refuseFrame(ctx context.Context, frame channel.Frame, operation string, err error) string {
	code := RefusalCode(err)
	message := "endpoint access policy refused operation"
	if code == credentialRejectedCode {
		message = "endpoint rejected the caller credential"
	}
	s.loggerWarn(message, "operation", operation, "request_id", frame.RequestID, "error", err.Error())
	return code
}
