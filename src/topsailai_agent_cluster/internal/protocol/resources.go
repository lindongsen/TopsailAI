// Package protocol defines provider-neutral Agent Cluster contracts.
package protocol

// Endpoint identifies one machine-scoped controller.
type Endpoint struct {
	EndpointID         string `json:"endpoint_id"`
	InstanceID         string `json:"instance_id"`
	DisplayName        string `json:"display_name"`
	Hostname           string `json:"hostname,omitempty"`
	ConnectionState    string `json:"connection_state"`
	ObservedAtMS       int64  `json:"observed_at_ms"`
	CapabilityRevision string `json:"capability_revision"`
}

// Session identifies a provider session without exposing provider routing details.
type Session struct {
	SessionID string `json:"session_id"`
	// ProviderSessionID is the provider-native session identifier reported by the
	// adapter. SessionID stays the opaque cluster resource ID used for routing.
	ProviderSessionID string `json:"provider_session_id,omitempty"`
	DisplayName       string `json:"display_name,omitempty"`
	AgentID           string `json:"agent_id"`
	Generation        string `json:"generation"`
	AdapterID         string `json:"adapter_id"`
	State             string `json:"state"`
	StateReason       string `json:"state_reason,omitempty"`
	Stale             bool   `json:"stale,omitempty"`
	Unknown           bool   `json:"unknown,omitempty"`
	CollectionStatus  string `json:"collection_status,omitempty"`
	ObservedAtMS      int64  `json:"observed_at_ms"`
	// Drive is the bounded controller summary reported by the adapter. It is
	// descriptive report data: Server stores and returns it without interpreting
	// provider semantics, and an absent summary means the provider reported no
	// driver observation rather than that no driver exists.
	Drive *DriveSummary `json:"drive,omitempty"`
}

// DriveSummary describes the standard controller state of one session.
//
// A driver is a resident controller that injects input on the operator's behalf.
// It is not the agent and not the session: stopping a driver leaves the agent
// running, and an agent can run with no driver at all.
type DriveSummary struct {
	State string `json:"state"`
	// Reason is a bounded standard reason code, never a provider diagnostic.
	Reason string `json:"reason,omitempty"`
	// ControllerPID is the reported controller process identity. It is evidence
	// for display only and is never a routing or signalling authority.
	ControllerPID int64 `json:"controller_pid,omitempty"`
	// RunID identifies one controller run so a replacement run is distinguishable.
	RunID string `json:"run_id,omitempty"`
	// Verified reports whether the controller liveness was actually verified.
	// An unverified record must never be presented as a running controller.
	Verified     bool  `json:"verified"`
	ObservedAtMS int64 `json:"observed_at_ms"`
}

// Standard drive states. They are provider-neutral: an adapter maps its own
// vocabulary onto these values and keeps provider-specific detail local.
const (
	// DriveStateNone means no controller record exists for the session.
	DriveStateNone = "none"
	// DriveStateRunning means a controller is verified alive.
	DriveStateRunning = "running"
	// DriveStateStale means a controller record exists but liveness is unverified.
	DriveStateStale = "stale"
	// DriveStateExited means a residual record from a clean controller exit.
	DriveStateExited = "exited"
	// DriveStateFailed means a residual record from a failed controller exit.
	DriveStateFailed = "failed"
	// DriveStateUnknown means the controller state could not be determined.
	DriveStateUnknown = "unknown"
)

// AdapterSummary describes an adapter as report data, not an execution selector.
type AdapterSummary struct {
	AdapterID        string               `json:"adapter_id"`
	ProviderType     string               `json:"provider_type"`
	DisplayName      string               `json:"display_name"`
	Version          string               `json:"version"`
	Health           string               `json:"health"`
	Capabilities     CapabilityDescriptor `json:"capabilities,omitempty"`
	CollectionStatus string               `json:"collection_status"`
	LastAttemptAtMS  int64                `json:"last_attempt_at_ms"`
	LastSuccessAtMS  *int64               `json:"last_success_at_ms,omitempty"`
	DataKnown        bool                 `json:"data_known"`
	Stale            bool                 `json:"stale,omitempty"`
}
