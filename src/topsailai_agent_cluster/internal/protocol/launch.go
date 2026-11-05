package protocol

// Project is a provider-managed directory, not a cluster resource identity.
type Project struct {
	Name string `json:"name"`
	Path string `json:"path"`
}

// LaunchQuery selects an optional adapter project handler; empty selects the catalog.
type LaunchQuery struct {
	AdapterID string `json:"adapter_id,omitempty"`
}

// LaunchHandler identifies a configured, start-capable adapter and its revision.
type LaunchHandler struct {
	AdapterID   string `json:"adapter_id"`
	DisplayName string `json:"display_name"`
	Revision    string `json:"revision"`
}

// LaunchOptions carries bounded handler/project results with explicit failures.
type LaunchOptions struct {
	Handlers  []LaunchHandler `json:"handlers"`
	Projects  []Project       `json:"projects"`
	ErrorCode string          `json:"error_code,omitempty"`
}

const MaxProjects = 1000
const MaxProjectBytes = 256 << 10
const MaxInitialTaskBytes = 8192
