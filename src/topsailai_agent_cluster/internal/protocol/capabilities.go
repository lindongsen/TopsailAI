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
