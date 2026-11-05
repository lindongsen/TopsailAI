package adapter

import (
	"context"
	"topsailai_agent_cluster/internal/protocol"
)

// ProjectHandler optionally discovers provider-managed launch folders without mutation.
type ProjectHandler interface {
	Projects(context.Context) ([]protocol.Project, error)
}
