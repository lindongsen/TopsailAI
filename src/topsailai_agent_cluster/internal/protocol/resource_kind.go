package protocol

// Standard resource kinds identify the Cluster resource namespace used by
// durable Endpoint mappings and Provider CLI observations.
const (
	ResourceAgent         = "agent"
	ResourceSession       = "session"
	ResourceTask          = "task"
	ResourceLaunchProfile = "launch_profile"
	ResourceModelProfile  = "model_profile"
)

// IsResourceKind reports whether value belongs to the closed Cluster resource
// vocabulary.
func IsResourceKind(value string) bool {
	switch value {
	case ResourceAgent, ResourceSession, ResourceTask, ResourceLaunchProfile, ResourceModelProfile:
		return true
	default:
		return false
	}
}
