package protocol

const (
	OperationMessageSend        = "message.send"
	OperationContextInject      = "context.inject"
	OperationExecutionInterrupt = "execution.interrupt"
	OperationAgentStart         = "agent.start"
	OperationAgentResume        = "agent.resume"
	OperationAgentStop          = "agent.stop"
	OperationAgentDriveStart    = "agent.drive.start"
	OperationAgentDriveStop     = "agent.drive.stop"
	OperationOutputRead         = "output.read"
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
)

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
