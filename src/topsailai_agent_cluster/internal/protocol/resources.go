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
	// ClusterSessionID is the opaque cluster resource ID the Endpoint minted for
	// this session. It is the only routing identity the Server ever sees, and it
	// is never derived from a provider key, a row number or a PID.
	ClusterSessionID string `json:"cluster_session_id"`
	// ProviderSessionID is the provider-native session identifier reported by the
	// adapter. It is evidence and a provider-side selector, never a cluster
	// routing identity.
	ProviderSessionID string `json:"provider_session_id,omitempty"`
	// ProviderPID is the provider-native process identity the provider reported for
	// this session. It is display evidence only: it never participates in routing,
	// generation validation or signalling, because a reused PID cannot prove which
	// process an operation would reach. Zero means the provider reported no PID,
	// which is not the same as a session with no process.
	ProviderPID int64 `json:"provider_pid,omitempty"`
	// ProviderDisplayName is the provider session name, descriptive only.
	ProviderDisplayName string `json:"provider_display_name,omitempty"`
	// ProviderSessionQualifier distinguishes sibling provider rows that share a
	// session name. It is descriptive only and never participates in routing,
	// capability selection, or authorization.
	ProviderSessionQualifier string `json:"provider_session_qualifier,omitempty"`
	// ProviderProjectWorkspace is the workspace the session is working on, as
	// reported by the provider. It is descriptive report data only: it never
	// participates in routing, capability selection, or authorization.
	ProviderProjectWorkspace string `json:"provider_project_workspace,omitempty"`
	// ProviderAgentID is the provider's own agent identity, forwarded verbatim.
	// The cluster never mints an agent ID, so this value is provider evidence and
	// must never be read as a cluster identity.
	ProviderAgentID string `json:"provider_agent_id"`
	// ProviderGeneration is the provider's own process generation for this
	// session. It is the value an operation revalidates against, and an empty
	// value means the provider could not verify liveness.
	ProviderGeneration string `json:"provider_generation"`
	AdapterID          string `json:"adapter_id"`
	State              string `json:"state"`
	StateReason        string `json:"state_reason,omitempty"`
	Stale              bool   `json:"stale,omitempty"`
	Unknown            bool   `json:"unknown,omitempty"`
	CollectionStatus   string `json:"collection_status,omitempty"`
	ObservedAtMS       int64  `json:"observed_at_ms"`
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
	// DrivePID is the reported drive process identity. It is evidence for display
	// only and is never a routing or signalling authority.
	DrivePID int64 `json:"drive_pid,omitempty"`
	// RunID identifies one controller run so a replacement run is distinguishable.
	RunID string `json:"run_id,omitempty"`
	// Verified reports whether the controller liveness was actually verified.
	// An unverified record must never be presented as a running controller.
	Verified     bool  `json:"verified"`
	ObservedAtMS int64 `json:"observed_at_ms"`
}

// Standard session states. They are provider-neutral: an adapter maps its own
// vocabulary onto these values and keeps provider-specific detail local, so the
// cluster contract never depends on one provider's spelling.
const (
	// SessionStateRunning means the provider proved a live process that is not
	// waiting for input.
	SessionStateRunning = "running"
	// SessionStateWaitingInput means the provider proved a live process that is
	// waiting for input. It is the state an operator reacts to, so it is a
	// standard value rather than a provider word.
	SessionStateWaitingInput = "waiting_input"
	// SessionStateIdle means the provider reported no live process for the
	// record. The record still exists, so it remains addressable by resume.
	SessionStateIdle = "idle"
	// SessionStateUnknown means the provider reported the record but could not
	// verify the liveness of the process behind it. It is a real observation of
	// an unverified session, not an unavailable observation: the record exists,
	// only its liveness is unproven.
	SessionStateUnknown = "unknown"
)

// StateReasonLivenessUnverified means the provider listed the session but could
// not confirm that a process still holds its output file, so no generation was
// reported. Such a session is not routable for operations that require a live
// target, because the Endpoint cannot prove which process it would address.
const StateReasonLivenessUnverified = "liveness_unverified"

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
