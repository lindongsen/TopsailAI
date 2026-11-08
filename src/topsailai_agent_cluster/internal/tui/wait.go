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
func WaitForTerminal(ctx context.Context, reader CommandStateReader, commandID string, interval time.Duration) (map[string]any, error) {
	return WaitForTerminalWithProgress(ctx, reader, commandID, interval, nil)
}

// WaitForTerminalWithProgress polls durable state and reports each observed
// lifecycle stage to progress.
//
// The stage is derived from the same durable state the wait already reads, so a
// progress row is evidence rather than a guess, and it costs no extra request.
// Progress is presentation only: a nil reporter reports nothing, and a reporter
// failure never changes the returned state or error.
func WaitForTerminalWithProgress(ctx context.Context, reader CommandStateReader, commandID string, interval time.Duration, progress *ActionProgress) (map[string]any, error) {
	if interval <= 0 {
		interval = 100 * time.Millisecond
	}
	var last map[string]any
	for {
		state, err := reader.GetCommand(ctx, commandID)
		if err == nil {
			last = state
			progress.Stage(progressStage(state))
			if IsTerminalState(state) {
				return state, nil
			}
		} else if last == nil {
			return nil, err
		}
		// The tick prints buffered stages once the threshold has passed, so a
		// command whose state does not change still shows that it is in flight.
		progress.Tick()
		timer := time.NewTimer(interval)
		select {
		case <-ctx.Done():
			timer.Stop()
			return last, nil
		case <-timer.C:
		}
	}
}

// progressStage maps one durable command state onto the operator-facing stage
// row. It reuses StatusLabel, so the progress wording and the final receipt
// wording can never disagree about what a state means.
func progressStage(state map[string]any) string {
	status := protocol.CommandStatus(stringValue(state, "status"))
	if status == "" {
		return ""
	}
	return StatusLabel(status, ReceiptForStatus(state))
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
