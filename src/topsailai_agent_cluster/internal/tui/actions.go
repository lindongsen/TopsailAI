package tui

import (
	"context"
	"fmt"
	"time"

	"topsailai_agent_cluster/internal/protocol"
)

// CapabilityQuerier retrieves the authoritative capability declaration for an Endpoint.
type CapabilityQuerier interface {
	GetCapabilities(context.Context, string) (protocol.CapabilityDescriptor, error)
}

const defaultWaitTimeout = 10 * time.Second

// WaitTimeout returns the caller wait limit, using the safe default when unset.
func WaitTimeout(budget protocol.Budget) time.Duration {
	if budget.WaitTimeoutMS <= 0 {
		return defaultWaitTimeout
	}
	return time.Duration(budget.WaitTimeoutMS) * time.Millisecond
}

// WaitContext creates a bounded local wait context without changing durable execution state.
func WaitContext(parent context.Context, budget protocol.Budget) (context.Context, context.CancelFunc) {
	return context.WithTimeout(parent, WaitTimeout(budget))
}

// RequireConfirmation enforces the second confirmation for mutating actions.
func RequireConfirmation(confirmed bool, operation, target, parameters string) error {
	if confirmed {
		return nil
	}
	return fmt.Errorf("confirmation required for %s target=%s parameters=%s; rerun with --yes", operation, target, parameters)
}

// ValidateCapability rejects an operation that is not explicitly advertised.
func ValidateCapability(descriptor protocol.CapabilityDescriptor, operation string) error {
	for _, capability := range descriptor.Capabilities {
		if capability.Name == operation {
			return nil
		}
	}
	return fmt.Errorf("unsupported capability %q", operation)
}

// PreflightCapability retrieves and validates one operation before command submission.
func PreflightCapability(ctx context.Context, querier CapabilityQuerier, endpointID, operation string) (protocol.CapabilityDescriptor, error) {
	if querier == nil {
		return protocol.CapabilityDescriptor{}, fmt.Errorf("capability query unavailable for endpoint %q", endpointID)
	}
	descriptor, err := querier.GetCapabilities(ctx, endpointID)
	if err != nil {
		return protocol.CapabilityDescriptor{}, fmt.Errorf("capability query failed for endpoint %q: %w", endpointID, err)
	}
	if err := ValidateCapability(descriptor, operation); err != nil {
		return protocol.CapabilityDescriptor{}, fmt.Errorf("endpoint %q: %w", endpointID, err)
	}
	return descriptor, nil
}

// ValidateStopTarget requires an exact generation for stop operations.
func ValidateStopTarget(target protocol.CommandTarget) error {
	if target.ResourceID == "" || target.Generation == "" {
		return fmt.Errorf("stop requires resource_id and generation")
	}
	return nil
}
