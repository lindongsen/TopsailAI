// Package protocol defines provider-neutral Agent Cluster contracts.
package protocol

// Endpoint identifies one machine-scoped controller.
type Endpoint struct {
	EndpointID         string `json:"endpoint_id"`
	InstanceID         string `json:"instance_id"`
	DisplayName        string `json:"display_name"`
	ConnectionState    string `json:"connection_state"`
	ObservedAtMS       int64  `json:"observed_at_ms"`
	CapabilityRevision string `json:"capability_revision"`
}

// Session identifies a provider session without exposing provider routing details.
type Session struct {
	SessionID        string `json:"session_id"`
	DisplayName      string `json:"display_name,omitempty"`
	AgentID          string `json:"agent_id"`
	Generation       string `json:"generation"`
	AdapterID        string `json:"adapter_id"`
	State            string `json:"state"`
	StateReason      string `json:"state_reason,omitempty"`
	Stale            bool   `json:"stale,omitempty"`
	Unknown          bool   `json:"unknown,omitempty"`
	CollectionStatus string `json:"collection_status,omitempty"`
	ObservedAtMS     int64  `json:"observed_at_ms"`
}

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
