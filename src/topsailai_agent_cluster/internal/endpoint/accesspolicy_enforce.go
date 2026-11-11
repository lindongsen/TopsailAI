package endpoint

import (
	"context"

	"topsailai_agent_cluster/internal/channel"
	"topsailai_agent_cluster/internal/protocol"
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
	return s.accessPolicy.Permit(s.endpointID, frame.EndpointToken, operation)
}

// refuseFrame logs one policy refusal and returns the shared refusal code.
//
// The log line names the operation and the request, never the token: a token is a
// secret, and a log that records it turns every log reader into a credential
// holder. The request ID is enough to correlate the refusal with the caller's own
// record.
func (s *Service) refuseFrame(ctx context.Context, frame channel.Frame, operation string, err error) string {
	s.loggerWarn("endpoint access policy refused operation", "operation", operation, "request_id", frame.RequestID, "error", err.Error())
	return policyDeniedCode
}
