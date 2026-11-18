package protocol

import "fmt"

const (
	OperationMessageSend        = "message.send"
	OperationContextInject      = "context.inject"
	OperationExecutionInterrupt = "execution.interrupt"
	OperationAgentStart         = "agent.start"
	OperationAgentResume        = "agent.resume"
	OperationAgentStop          = "agent.stop"
	OperationAgentDriveStart    = "agent.drive.start"
	OperationAgentDriveStop     = "agent.drive.stop"
	// OperationWorkspaceClean removes provider-owned expired artifacts for one
	// exact session target. Provider selectors and retention rules stay private
	// to the adapter.
	OperationWorkspaceClean = "workspace.clean"
	OperationOutputRead     = "output.read"
	// OperationOutputFollow streams output records until the consumer stops. It
	// is a separate capability from OperationOutputRead: a snapshot is one
	// bounded read, while a follow stays open. Advertising them separately lets a
	// provider that cannot stream report the gap instead of degrading a follow
	// into a snapshot that never updates.
	OperationOutputFollow = "output.follow"
	OperationDiscover     = "discover"
	// OperationCommandExec runs one allowlisted argv array in a session working
	// directory. It is a bounded standard operation, not a remote shell.
	OperationCommandExec = "command.exec"
	// OperationAgentModelList reads the model profiles a session can select. It
	// is a read-only operation: it never changes provider state, so it is
	// advertised with SafetyClassReadOnly and needs only the view scope.
	OperationAgentModelList = "agent.model.list"
	// OperationAgentModelSelect switches one session to a model profile. It
	// changes live agent behaviour, so it is advertised with SafetyClassMutating
	// and needs the control scope.
	OperationAgentModelSelect = "agent.model.select"

	// The five names below are policy identifiers for the frame-level read
	// queries that travel as their own frame type rather than as an immutable
	// intent. They never appear on the wire as an operation field, but they are
	// still operation names: an access policy grants or refuses them, and a
	// signed Endpoint credential covers the name of the operation it authorizes.
	//
	// They live here rather than beside the policy loader because two independent
	// components must agree on the exact string. The Endpoint verifies a signature
	// over the name, and the operator client signs it, so a second definition in
	// either component would let the two disagree and every signed read would fail
	// with a message that blames the caller's secret.
	//
	// OperationLaunchQuery reads the start-capable adapter catalog and one
	// adapter's managed projects.
	OperationLaunchQuery = "launch.query"
	// OperationHistoryRead reads provider session history.
	OperationHistoryRead = "history.read"
	// OperationMessagesRead reads one session's conversation context.
	OperationMessagesRead = "messages.read"
	// OperationMetricsRead reads one session's current message counts. It is a
	// live observation of a running session, so it is a separate permission from
	// messages.read: an operator may be allowed to see how much context a session
	// holds without being allowed to read the conversation itself.
	OperationMetricsRead = "metrics.read"
	// OperationDetailRead reads one session's provider metadata and runtime
	// document. The metadata is the provider's own session record, so it is a
	// separate permission from messages.read for the same reason.
	OperationDetailRead = "detail.read"
)

// PolicyDenied is the single refusal code for every operation an Endpoint access
// policy refuses.
//
// One code covers every operation rather than one code per operation, because a
// refusal is one decision: this caller may not exercise this operation on this
// machine. A per-operation vocabulary would grow with every operation added and
// force a client to learn each new name, while telling the caller nothing it did
// not already know, since it asked for that operation. The refused operation is
// named in the message instead.
//
// It lives here rather than in the Endpoint package because the Server must
// recognise the code to report it as a refusal instead of a provider failure, and
// two literals in two packages would drift.
const PolicyDenied = "policy_denied"

// CredentialRejected reports that the Endpoint could not authenticate the caller,
// so the request was refused before the access policy was consulted.
//
// It is deliberately distinct from PolicyDenied, because the two refusals have
// different remedies and the same code would hide which one happened. A policy
// refusal means the credential was proven and its grants do not cover the
// operation, so the operator edits the policy file. A credential rejection means
// the credential could not be proven at all, so the operator fixes the credential
// itself: a missing signature, a wrong key identifier, a clock outside the
// accepted window, a replayed nonce or a credential form the configured mode does
// not accept. Reporting the second as the first sends the operator to a policy
// file that is already correct.
//
// The distinction is also a security property, not only a diagnostic one. The
// policy is consulted only after the credential is proven, so a caller that
// cannot prove possession never learns which operations exist or which are
// granted. Collapsing the two codes would let an unauthenticated caller infer a
// grant decision from the answer it received.
//
// It lives here rather than in the Endpoint package because the Server must
// recognise the code to report it as an authentication failure instead of a
// provider failure, and two literals in two packages would drift.
const CredentialRejected = "credential_rejected"

// InvalidTarget reports that a request named an identity the addressed surface
// cannot accept, so the request was rejected before any provider process started.
//
// It is deliberately distinct from a provider failure. The caller supplied the
// wrong kind of identity, so the remedy is to supply the right one; reporting it
// as a provider failure sends the operator to investigate a provider that was
// never invoked. The Server already uses this code for a missing selector, so one
// vocabulary covers both a missing identity and a wrong one.
//
// It lives here rather than in the Endpoint package because the Server must
// recognise the code to report it as a caller error instead of a provider
// failure, and two literals in two packages would drift.
const InvalidTarget = "invalid_target"

// AdapterBusy reports that an adapter could not obtain the capacity it needs
// within the caller's budget, so the requested provider call never happened.
//
// It is deliberately distinct from a provider failure. A busy adapter says
// nothing about the target and nothing about the provider: the same request may
// succeed unchanged once the competing invocation finishes, so the operator must
// be told to retry rather than to investigate a provider that was never invoked.
// The Endpoint's own periodic collection is the usual competitor, which is why
// this condition is transient rather than a fault.
//
// It lives here rather than in the Endpoint package because the Server must
// recognise the code to report it as a transient condition instead of a provider
// failure, and two literals in two packages would drift.
const AdapterBusy = "adapter_busy"

// OutputLimit reports that a streamed read stopped because a local byte budget was
// exhausted, so the provider was not at fault.
//
// It is deliberately distinct from a provider failure. The provider wrote valid
// frames and the Endpoint refused to buffer more of them, so the operator must be
// told that the local bound was reached rather than sent to investigate a provider
// that behaved correctly. A record count is not part of this condition: a live
// follow is bounded by bytes and by its deadline, because a record count truncates
// a healthy stream whose only fault is being long.
//
// It lives here rather than in the Endpoint package because the Server and the TUI
// must recognise the code to report it as a local bound instead of a provider
// failure, and two literals in two packages would drift.
const OutputLimit = "output_limit"

// Standard safety classes. The vocabulary is closed, because the value decides
// whether an operator must confirm an operation and which scope a credential must
// hold. A read-only listing advertised as mutating is a contract lie: it forces a
// confirmation and a stronger scope onto an operation that changes nothing, while
// hiding the operations that really do change state behind the same label.
const (
	// SafetyClassReadOnly marks an operation that never changes provider state.
	SafetyClassReadOnly = "read_only"
	// SafetyClassMutating marks an operation that may change provider state.
	SafetyClassMutating = "mutating"
)

// ValidateSafetyClass rejects a safety class outside the closed vocabulary
// instead of guessing what an unknown value was meant to mean.
func ValidateSafetyClass(value string) error {
	switch value {
	case SafetyClassReadOnly, SafetyClassMutating:
		return nil
	default:
		return fmt.Errorf("invalid safety class %q", value)
	}
}

// Capability describes one standard operation supported by an Endpoint.
type Capability struct {
	Name               string   `json:"name"`
	Version            string   `json:"version"`
	TargetKinds        []string `json:"target_kinds"`
	PayloadSchema      string   `json:"payload_schema"`
	SafetyClass        string   `json:"safety_class"`
	RequiredPermission string   `json:"required_permission"`
}

// CapabilityDescriptor is the versioned standard capability declaration.
type CapabilityDescriptor struct {
	Revision     string       `json:"revision"`
	Capabilities []Capability `json:"capabilities"`
}
