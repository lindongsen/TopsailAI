package main

import "testing"

// TestProductionConcurrencyLeavesNoClassStarved proves the production limits
// satisfy the invariant the scheduler doc comment states: Total must be at least
// the sum of the class limits, or a class can be refused by the shared total
// channel while its own channel still has room.
//
// The invariant is asserted here rather than inside newScheduler, because
// saturation tests deliberately construct a Total smaller than the class sum to
// prove the total bound is enforced. Without this guard the invariant lives only
// in a comment, and a future edit to any single limit could silently starve a
// class.
func TestProductionConcurrencyLeavesNoClassStarved(t *testing.T) {
	limits := genericCLIConcurrency
	classSum := limits.Discovery + genericCLIReadConcurrency + limits.Mutation + limits.Follow
	if limits.Total < classSum {
		t.Fatalf("genericCLIConcurrency.Total = %d, want at least %d (discovery %d + read %d + mutation %d + follow %d), or a class is starved by the total channel",
			limits.Total, classSum, limits.Discovery, genericCLIReadConcurrency, limits.Mutation, limits.Follow)
	}
	if genericCLIReadConcurrency < 1 {
		t.Fatalf("genericCLIReadConcurrency = %d, want a positive read limit", genericCLIReadConcurrency)
	}
	if limits.Discovery < 1 {
		t.Fatalf("genericCLIConcurrency.Discovery = %d, want a positive discovery limit", limits.Discovery)
	}
}

// TestProductionReadCapacityExceedsDiscoveryCapacity proves the operator read
// class is not merely a rename of the discovery class.
//
// Reads must be able to run while a collection cycle is in flight, and several
// operators may read at once. A read ceiling equal to the discovery ceiling would
// let one collection cycle consume half of the read capacity, which is the
// coupling the class split removes.
func TestProductionReadCapacityExceedsDiscoveryCapacity(t *testing.T) {
	if genericCLIReadConcurrency <= genericCLIConcurrency.Discovery {
		t.Fatalf("genericCLIReadConcurrency = %d, want it to exceed genericCLIConcurrency.Discovery = %d",
			genericCLIReadConcurrency, genericCLIConcurrency.Discovery)
	}
}
