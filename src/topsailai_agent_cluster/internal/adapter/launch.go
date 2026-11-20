package adapter

import (
	"context"

	"topsailai_agent_cluster/internal/protocol"
)

// LaunchProfileHandler optionally returns the Endpoint-mapped launch profile for an Adapter.
type LaunchProfileHandler interface {
	LaunchProfile(context.Context) (protocol.LaunchHandler, error)
}
