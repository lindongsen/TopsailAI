package protocol

import "fmt"

// CanTransition reports whether a Server command status transition is legal.
func CanTransition(from, to CommandStatus) bool {
	if from == to {
		return true
	}
	switch from {
	case StatusAdmitted:
		return to == StatusDispatched || to == StatusCancelled || to == StatusExpired || to == StatusRejected || to == StatusFailed
	case StatusDispatched:
		return to == StatusEndpointAdmitted || to == StatusExpired || to == StatusRejected || to == StatusFailed
	case StatusEndpointAdmitted:
		return to == StatusExecuting || to == StatusFinished || to == StatusRejected || to == StatusFailed
	case StatusExecuting:
		return to == StatusFinished || to == StatusFailed || to == StatusUnconfirmed
	default:
		return false
	}
}

// ValidateTransition validates a requested durable status transition.
func ValidateTransition(from, to CommandStatus) error {
	if !CanTransition(from, to) {
		return fmt.Errorf("invalid command transition %q to %q", from, to)
	}
	return nil
}

// CanCancel reports whether a command can still be cancelled before dispatch.
func CanCancel(status CommandStatus) bool { return status == StatusAdmitted }
