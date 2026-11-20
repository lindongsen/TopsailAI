package protocol

// Project is one provider-managed directory registered on an Endpoint.
//
// ProjectID is the required opaque Cluster identity minted by the Endpoint.
// Name and Path are provider observations and are never used as Cluster authority.
type Project struct {
	ProjectID string `json:"project_id"`
	Name      string `json:"name"`
	Path      string `json:"path"`
}

// LaunchQuery selects one optional launch-profile Adapter; empty selects the catalog.
type LaunchQuery struct {
	AdapterID string `json:"adapter_id,omitempty"`
}

// LaunchHandler identifies a configured, start-capable adapter and its revision.
type LaunchHandler struct {
	AdapterID       string `json:"adapter_id"`
	LaunchProfileID string `json:"launch_profile_id"`
	DisplayName     string `json:"display_name"`
	Revision        string `json:"revision"`
}

// LaunchOptions carries bounded launch-profile handler results with explicit failures.
type LaunchOptions struct {
	Handlers  []LaunchHandler `json:"handlers"`
	ErrorCode string          `json:"error_code,omitempty"`
}

const MaxProjects = 1000
const MaxProjectBytes = 256 << 10
const MaxInitialTaskBytes = 8192
