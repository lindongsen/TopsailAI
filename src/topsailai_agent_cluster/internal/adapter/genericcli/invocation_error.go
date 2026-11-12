package genericcli

import (
	"fmt"

	"topsailai_agent_cluster/internal/providercli"
)

// invocationError preserves a valid Provider failure response when the process
// exit status independently reports failure.
type invocationError struct {
	response providercli.Response
	cause    error
}

func (e *invocationError) Error() string {
	return fmt.Sprintf("provider invocation failed: %v", e.cause)
}

func (e *invocationError) Unwrap() error { return e.cause }
