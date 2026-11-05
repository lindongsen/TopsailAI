package tui

import (
	"context"
	"time"

	"topsailai_agent_cluster/internal/protocol"
)

// CommandStateReader retrieves durable command state for local wait polling.
type CommandStateReader interface {
	GetCommand(context.Context, string) (map[string]any, error)
}

// WaitForTerminal polls durable state until a terminal state or the local budget ends.
// A timeout returns the most recently observed persistent state without changing it.
// WaitForTerminal polls durable state until a terminal state or the local budget ends.
func WaitForTerminal(ctx context.Context, reader CommandStateReader, commandID string, interval time.Duration) (map[string]any, error) {
	if interval <= 0 {
		interval = 100 * time.Millisecond
	}
	var last map[string]any
	for {
		state, err := reader.GetCommand(ctx, commandID)
		if err == nil {
			last = state
			if IsTerminalState(state) {
				return state, nil
			}
		} else if last == nil {
			return nil, err
		}
		timer := time.NewTimer(interval)
		select {
		case <-ctx.Done():
			timer.Stop()
			return last, nil
		case <-timer.C:
		}
	}
}

// IsTerminalState reports whether durable command state is final.
func IsTerminalState(state map[string]any) bool {
	value, _ := state["status"].(string)
	switch protocol.CommandStatus(value) {
	case protocol.StatusFinished, protocol.StatusRejected, protocol.StatusFailed, protocol.StatusCancelled, protocol.StatusExpired, protocol.StatusUnconfirmed:
		return true
	default:
		return false
	}
}
