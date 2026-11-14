package genericcli

import (
	"context"
	"testing"
	"time"
)

// TestBoundedContextPrefersTheEarlierDeadline pins the deterministic choice
// between the configured timeout and the absolute deadline. The earlier of the
// two wins, so a caller can never extend an invocation by configuring a longer
// timeout than the request allows.
func TestBoundedContextPrefersTheEarlierDeadline(t *testing.T) {
	now := time.Now()
	tests := []struct {
		name       string
		timeoutMS  int64
		deadlineMS int64
		wantBound  bool
	}{
		{name: "no budget is cancellable only", timeoutMS: 0, deadlineMS: 0, wantBound: false},
		{name: "timeout only", timeoutMS: 5000, deadlineMS: 0, wantBound: true},
		{name: "deadline only", timeoutMS: 0, deadlineMS: now.Add(time.Minute).UnixMilli(), wantBound: true},
		{name: "deadline earlier than timeout", timeoutMS: 60000, deadlineMS: now.Add(time.Second).UnixMilli(), wantBound: true},
		{name: "timeout earlier than deadline", timeoutMS: 1000, deadlineMS: now.Add(time.Minute).UnixMilli(), wantBound: true},
	}
	for _, test := range tests {
		t.Run(test.name, func(t *testing.T) {
			ctx, cancel := boundedContext(context.Background(), test.timeoutMS, test.deadlineMS)
			defer cancel()
			_, bound := ctx.Deadline()
			if bound != test.wantBound {
				t.Fatalf("deadline bound=%v, want %v", bound, test.wantBound)
			}
		})
	}
}

// TestBoundedContextUsesTheEarlierOfTwoBounds proves the earlier bound wins by
// measuring the resulting deadline, not merely that a deadline exists.
func TestBoundedContextUsesTheEarlierOfTwoBounds(t *testing.T) {
	now := time.Now()
	earlier := now.Add(2 * time.Second)
	ctx, cancel := boundedContext(context.Background(), 600000, earlier.UnixMilli())
	defer cancel()
	deadline, bound := ctx.Deadline()
	if !bound {
		t.Fatal("bounded context has no deadline")
	}
	if deadline.After(earlier.Add(100 * time.Millisecond)) {
		t.Fatalf("deadline=%s, want the absolute deadline %s to win over the longer timeout", deadline, earlier)
	}
}

// TestBoundedContextExpiresAnAlreadyPassedDeadline proves an absolute deadline
// in the past is not silently ignored: the context is already done.
func TestBoundedContextExpiresAnAlreadyPassedDeadline(t *testing.T) {
	ctx, cancel := boundedContext(context.Background(), 0, time.Now().Add(-time.Minute).UnixMilli())
	defer cancel()
	select {
	case <-ctx.Done():
	case <-time.After(time.Second):
		t.Fatal("a deadline in the past left the context live")
	}
	if err := ctx.Err(); err != context.DeadlineExceeded {
		t.Fatalf("context error=%v, want %v", err, context.DeadlineExceeded)
	}
}

// TestBoundedContextKeepsCancellationDistinct proves a cancelled parent is
// reported as cancellation, not as a deadline, so the two outcomes stay
// distinguishable downstream.
func TestBoundedContextKeepsCancellationDistinct(t *testing.T) {
	parent, cancelParent := context.WithCancel(context.Background())
	ctx, cancel := boundedContext(parent, 60000, 0)
	defer cancel()
	cancelParent()
	select {
	case <-ctx.Done():
	case <-time.After(time.Second):
		t.Fatal("cancelling the parent left the context live")
	}
	if err := ctx.Err(); err != context.Canceled {
		t.Fatalf("context error=%v, want %v", err, context.Canceled)
	}
}

// TestInvocationContextNeverExceedsTheRequestDeadline pins the same rule for the
// provider invocation path, which computes a remaining budget instead of an
// absolute deadline.
func TestInvocationContextNeverExceedsTheRequestDeadline(t *testing.T) {
	now := time.Now()
	ctx, cancel := invocationContext(context.Background(), time.Hour, now.Add(2*time.Second).UnixMilli())
	defer cancel()
	deadline, bound := ctx.Deadline()
	if !bound {
		t.Fatal("invocation context has no deadline")
	}
	if deadline.After(now.Add(3 * time.Second)) {
		t.Fatalf("deadline=%s, want the request deadline to win over the one hour timeout", deadline)
	}
}

// TestInvocationContextExpiresAnAlreadyPassedDeadline proves an expired request
// deadline still produces a bounded context rather than an unbounded one.
func TestInvocationContextExpiresAnAlreadyPassedDeadline(t *testing.T) {
	ctx, cancel := invocationContext(context.Background(), time.Hour, time.Now().Add(-time.Minute).UnixMilli())
	defer cancel()
	select {
	case <-ctx.Done():
	case <-time.After(time.Second):
		t.Fatal("an expired request deadline left the invocation context live")
	}
	if err := ctx.Err(); err != context.DeadlineExceeded {
		t.Fatalf("context error=%v, want %v", err, context.DeadlineExceeded)
	}
}

// TestInvocationContextUsesTheConfiguredTimeoutWhenNoDeadlineIsGiven proves the
// configured timeout still bounds an invocation that carries no request deadline.
func TestInvocationContextUsesTheConfiguredTimeoutWhenNoDeadlineIsGiven(t *testing.T) {
	ctx, cancel := invocationContext(context.Background(), 30*time.Millisecond, 0)
	defer cancel()
	select {
	case <-ctx.Done():
	case <-time.After(2 * time.Second):
		t.Fatal("the configured timeout did not bound the invocation")
	}
	if err := ctx.Err(); err != context.DeadlineExceeded {
		t.Fatalf("context error=%v, want %v", err, context.DeadlineExceeded)
	}
}
