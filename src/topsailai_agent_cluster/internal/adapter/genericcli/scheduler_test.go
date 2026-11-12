package genericcli

import (
	"errors"
	"testing"

	"topsailai_agent_cluster/internal/providercli"
)

func TestSchedulerRejectsTotalSaturationWithoutBlocking(t *testing.T) {
	scheduler := mustScheduler(t, providercli.ConcurrencyLimits{Total: 1, Discovery: 1, Mutation: 1, Follow: 1})
	release, err := scheduler.acquire(classDiscovery)
	if err != nil {
		t.Fatalf("acquire first slot: %v", err)
	}
	defer release()
	if _, err := scheduler.acquire(classMutation); !errors.Is(err, ErrCapacity) {
		t.Fatalf("second acquire error = %v, want ErrCapacity", err)
	}
}

func TestSchedulerRejectsClassSaturationAndRestoresTotalSlot(t *testing.T) {
	scheduler := mustScheduler(t, providercli.ConcurrencyLimits{Total: 2, Discovery: 1, Mutation: 1, Follow: 1})
	releaseDiscovery, err := scheduler.acquire(classDiscovery)
	if err != nil {
		t.Fatalf("acquire discovery: %v", err)
	}
	defer releaseDiscovery()
	if _, err := scheduler.acquire(classDiscovery); !errors.Is(err, ErrCapacity) {
		t.Fatalf("second discovery error = %v, want ErrCapacity", err)
	}
	releaseMutation, err := scheduler.acquire(classMutation)
	if err != nil {
		t.Fatalf("class rejection leaked total capacity: %v", err)
	}
	releaseMutation()
}

func TestSchedulerReleaseIsIdempotent(t *testing.T) {
	scheduler := mustScheduler(t, providercli.ConcurrencyLimits{Total: 1, Discovery: 1, Mutation: 1, Follow: 1})
	release, err := scheduler.acquire(classFollow)
	if err != nil {
		t.Fatalf("acquire follow: %v", err)
	}
	release()
	release()
	next, err := scheduler.acquire(classFollow)
	if err != nil {
		t.Fatalf("acquire after duplicate release: %v", err)
	}
	next()
}

func TestSchedulersHaveIndependentCapacity(t *testing.T) {
	limits := providercli.ConcurrencyLimits{Total: 1, Discovery: 1, Mutation: 1, Follow: 1}
	first := mustScheduler(t, limits)
	second := mustScheduler(t, limits)
	releaseFirst, err := first.acquire(classMutation)
	if err != nil {
		t.Fatalf("acquire first scheduler: %v", err)
	}
	defer releaseFirst()
	releaseSecond, err := second.acquire(classMutation)
	if err != nil {
		t.Fatalf("first scheduler consumed second capacity: %v", err)
	}
	releaseSecond()
}

func TestEffectiveConcurrencyUsesPositiveMinimum(t *testing.T) {
	limits, err := effectiveConcurrency(
		providercli.ConcurrencyLimits{Total: 12, Discovery: 8, Mutation: 6, Follow: 4},
		providercli.ConcurrencyLimits{Total: 10, Discovery: 5, Mutation: 5, Follow: 3},
		providercli.ConcurrencyLimits{Total: 7, Discovery: 6, Mutation: 2, Follow: 2},
	)
	if err != nil {
		t.Fatalf("effectiveConcurrency: %v", err)
	}
	want := providercli.ConcurrencyLimits{Total: 7, Discovery: 5, Mutation: 2, Follow: 2}
	if limits != want {
		t.Fatalf("limits = %+v, want %+v", limits, want)
	}
}

func TestEffectiveConcurrencyRejectsInvalidInput(t *testing.T) {
	valid := providercli.ConcurrencyLimits{Total: 1, Discovery: 1, Mutation: 1, Follow: 1}
	_, err := effectiveConcurrency(valid, providercli.ConcurrencyLimits{}, valid)
	if err == nil {
		t.Fatal("invalid adapter limits were accepted")
	}
}

func mustScheduler(t *testing.T, limits providercli.ConcurrencyLimits) *scheduler {
	t.Helper()
	scheduler, err := newScheduler(limits)
	if err != nil {
		t.Fatalf("newScheduler: %v", err)
	}
	return scheduler
}
