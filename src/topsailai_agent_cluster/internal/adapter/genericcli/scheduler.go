package genericcli

import (
	"context"
	"errors"
	"fmt"
	"sync"
	"time"

	"topsailai_agent_cluster/internal/adapter"
	"topsailai_agent_cluster/internal/providercli"
)

// ErrCapacity reports that one Adapter instance has no immediate capacity for a
// Provider CLI invocation. Admission is deliberately non-blocking: waiting in an
// unbounded queue would let a caller believe its operation had already started.
//
// It wraps adapter.ErrBusy so the Endpoint can recognise a capacity condition
// through the contract it owns, without importing this implementation package.
var ErrCapacity = fmt.Errorf("%w: provider adapter capacity exhausted", adapter.ErrBusy)

type invocationClass string

const (
	// classDiscovery is the Endpoint's own periodic inventory collection. It is
	// the only class that may be skipped, because the next cycle retries.
	classDiscovery invocationClass = "discovery"
	// classRead is operator work that reads provider state: inspect, resolve,
	// read output, query and describe. It is separate from classDiscovery so the
	// Endpoint's own reporting can never delay a command the operator is waiting
	// for. Before this split every read shared the discovery slot, so a periodic
	// collection cycle made resume, history and model reads fail or wait.
	classRead     invocationClass = "read"
	classMutation invocationClass = "mutation"
	classFollow   invocationClass = "follow"
)

// scheduler bounds total and per-class Provider CLI processes for one Adapter.
//
// Each class owns its own channel, so a class can never consume another class's
// capacity. The shared total channel is a second, coarser bound; it is safe only
// while Total is at least the sum of the class limits, because otherwise a class
// could be refused by the total channel while its own channel still had room.
// That invariant is asserted against the production limits by
// TestProductionConcurrencyLeavesNoClassStarved, not inside newScheduler, because
// saturation tests deliberately construct a Total smaller than the class sum to
// prove the total bound is enforced.
type scheduler struct {
	total   chan struct{}
	classes map[invocationClass]chan struct{}
}

// newScheduler creates one independent per-Adapter scheduler.
//
// readLimit is Endpoint-local scheduling policy rather than a Provider capability,
// so it is a separate argument instead of a field on providercli.ConcurrencyLimits.
// The wire descriptor keeps its four fields and its closed schema, which means
// adding this class requires no Provider CLI or protocol change.
func newScheduler(limits providercli.ConcurrencyLimits, readLimit int) (*scheduler, error) {
	if err := validateConcurrencyLimits(limits); err != nil {
		return nil, err
	}
	if readLimit < 1 {
		return nil, errors.New("read concurrency limit must be positive")
	}
	return &scheduler{
		total: make(chan struct{}, limits.Total),
		classes: map[invocationClass]chan struct{}{
			classDiscovery: make(chan struct{}, limits.Discovery),
			classRead:      make(chan struct{}, readLimit),
			classMutation:  make(chan struct{}, limits.Mutation),
			classFollow:    make(chan struct{}, limits.Follow),
		},
	}, nil
}

// acquire reserves total and class capacity without waiting.
func (s *scheduler) acquire(class invocationClass) (func(), error) {
	classSlots, ok := s.classes[class]
	if !ok {
		return nil, fmt.Errorf("unknown provider invocation class %q", class)
	}
	select {
	case s.total <- struct{}{}:
	default:
		return nil, fmt.Errorf("%w: total", ErrCapacity)
	}
	select {
	case classSlots <- struct{}{}:
	default:
		<-s.total
		return nil, fmt.Errorf("%w: %s", ErrCapacity, class)
	}
	var once sync.Once
	return func() {
		once.Do(func() {
			<-classSlots
			<-s.total
		})
	}, nil
}

// acquireWithin reserves capacity, waiting inside the caller's own budget instead
// of failing on the first refusal.
//
// acquire is deliberately non-blocking, because an unbounded queue would let a
// caller believe its operation had already started. That reasoning does not apply
// here: the caller already carries a deadline, and waiting inside a budget the
// caller set is exactly what the budget is for. Without this wait a read that
// collided with another read of the same Adapter instance failed outright.
//
// The wait is bounded by ctx, so a caller that cannot get capacity in time still
// fails, and it reports the context error so the caller can tell a busy adapter
// from a broken provider.
func (s *scheduler) acquireWithin(ctx context.Context, class invocationClass) (func(), error) {
	release, err := s.acquire(class)
	if err == nil {
		return release, nil
	}
	if !errors.Is(err, ErrCapacity) {
		return nil, err
	}
	ticker := time.NewTicker(capacityPollInterval)
	defer ticker.Stop()
	for {
		select {
		case <-ctx.Done():
			return nil, fmt.Errorf("%w: %w", err, ctx.Err())
		case <-ticker.C:
			release, retryErr := s.acquire(class)
			if retryErr == nil {
				return release, nil
			}
			if !errors.Is(retryErr, ErrCapacity) {
				return nil, retryErr
			}
			err = retryErr
		}
	}
}

// acquireWithinBudget reserves capacity, waiting at most budget for a slot.
//
// It exists for a follow, which is the one invocation whose admission the operator
// is waiting on. acquireWithin bounds the wait by the caller's context, and a
// follow's context carries no deadline because the stream itself must stay open for
// as long as the operator watches. Without a separate budget a follow that cannot
// get a slot waits without limit while the operator already believes the stream is
// live.
//
// The budget expiry deliberately does not wrap the context error. The Endpoint
// classifies a follow failure by checking context.Canceled and
// context.DeadlineExceeded before adapter.ErrBusy, so an error carrying either
// sentinel would be reported as cancelled and the operator would read a capacity
// refusal as a stream that ended. A budget expiry therefore wraps only ErrCapacity,
// which the Endpoint maps to adapter_busy.
func (s *scheduler) acquireWithinBudget(ctx context.Context, class invocationClass, budget time.Duration) (func(), error) {
	release, err := s.acquire(class)
	if err == nil {
		return release, nil
	}
	if !errors.Is(err, ErrCapacity) {
		return nil, err
	}
	ticker := time.NewTicker(capacityPollInterval)
	defer ticker.Stop()
	budgetTimer := time.NewTimer(budget)
	defer budgetTimer.Stop()
	for {
		select {
		case <-ctx.Done():
			return nil, fmt.Errorf("%w: %w", err, ctx.Err())
		case <-budgetTimer.C:
			return nil, fmt.Errorf("%w: %s after %s", ErrCapacity, class, budget)
		case <-ticker.C:
			release, retryErr := s.acquire(class)
			if retryErr == nil {
				return release, nil
			}
			if !errors.Is(retryErr, ErrCapacity) {
				return nil, retryErr
			}
			err = retryErr
		}
	}
}

// capacityPollInterval is how often a caller waiting for capacity retries. It is
// short enough that a collection cycle of a few tens of milliseconds is absorbed
// without a visible delay, and long enough that a waiting caller does not spin.
const capacityPollInterval = 10 * time.Millisecond

// effectiveConcurrency narrows Endpoint and Adapter limits with Provider limits.
func effectiveConcurrency(endpoint, configured, provider providercli.ConcurrencyLimits) (providercli.ConcurrencyLimits, error) {
	for label, limits := range map[string]providercli.ConcurrencyLimits{
		"endpoint": endpoint, "adapter": configured, "provider": provider,
	} {
		if err := validateConcurrencyLimits(limits); err != nil {
			return providercli.ConcurrencyLimits{}, fmt.Errorf("%s concurrency: %w", label, err)
		}
	}
	return providercli.ConcurrencyLimits{
		Total:     minPositive(endpoint.Total, configured.Total, provider.Total),
		Discovery: minPositive(endpoint.Discovery, configured.Discovery, provider.Discovery),
		Mutation:  minPositive(endpoint.Mutation, configured.Mutation, provider.Mutation),
		Follow:    minPositive(endpoint.Follow, configured.Follow, provider.Follow),
	}, nil
}

func validateConcurrencyLimits(limits providercli.ConcurrencyLimits) error {
	if limits.Total < 1 || limits.Discovery < 1 || limits.Mutation < 1 || limits.Follow < 1 {
		return errors.New("all concurrency limits must be positive")
	}
	if limits.Discovery > limits.Total || limits.Mutation > limits.Total || limits.Follow > limits.Total {
		return errors.New("class concurrency exceeds total")
	}
	return nil
}

func minPositive(values ...int) int {
	result := values[0]
	for _, value := range values[1:] {
		if value < result {
			result = value
		}
	}
	return result
}
