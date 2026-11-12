package genericcli

import (
	"context"
	"time"
)

func boundedContext(parent context.Context, timeoutMS, deadlineAtMS int64) (context.Context, context.CancelFunc) {
	deadline := time.Time{}
	if timeoutMS > 0 {
		deadline = time.Now().Add(time.Duration(timeoutMS) * time.Millisecond)
	}
	if deadlineAtMS > 0 {
		absolute := time.UnixMilli(deadlineAtMS)
		if deadline.IsZero() || absolute.Before(deadline) {
			deadline = absolute
		}
	}
	if deadline.IsZero() {
		return context.WithCancel(parent)
	}
	return context.WithDeadline(parent, deadline)
}
