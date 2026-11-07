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
	OperationDiscover           = "discover"
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
