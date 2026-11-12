package genericcli

import (
	"errors"
	"fmt"
	"sync"

	"topsailai_agent_cluster/internal/providercli"
)

// ErrCapacity reports that one Adapter instance has no immediate capacity for a
// Provider CLI invocation. Admission is deliberately non-blocking: waiting in an
// unbounded queue would let a caller believe its operation had already started.
var ErrCapacity = errors.New("provider adapter capacity exhausted")

type invocationClass string

const (
	classDiscovery invocationClass = "discovery"
	classMutation  invocationClass = "mutation"
	classFollow    invocationClass = "follow"
)

// scheduler bounds total and per-class Provider CLI processes for one Adapter.
type scheduler struct {
	total   chan struct{}
	classes map[invocationClass]chan struct{}
}

// newScheduler creates one independent per-Adapter scheduler.
func newScheduler(limits providercli.ConcurrencyLimits) (*scheduler, error) {
	if err := validateConcurrencyLimits(limits); err != nil {
		return nil, err
	}
	return &scheduler{
		total: make(chan struct{}, limits.Total),
		classes: map[invocationClass]chan struct{}{
			classDiscovery: make(chan struct{}, limits.Discovery),
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
