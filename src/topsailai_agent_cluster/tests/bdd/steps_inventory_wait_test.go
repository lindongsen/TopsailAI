package bdd

import (
	"strings"
	"testing"
	"time"

	"topsailai_agent_cluster/internal/protocol"
)

// TestWaitRealInventoryBudgetIsGenerous guards the flake repair. The real-cluster
// scenarios wait for the Endpoint collection cycle, which under full-parallel
// package load can exceed a short fixed budget. A regression to a tight budget
// would reintroduce the flaky failure, so the budget is asserted here.
func TestWaitRealInventoryBudgetIsGenerous(t *testing.T) {
	if realInventoryWait < 20*time.Second {
		t.Fatalf("realInventoryWait = %s, want at least 20s so a loaded machine can finish the collection cycle", realInventoryWait)
	}
}

// TestWaitRealInventoryReportsUnreadableInventory verifies the timeout error names
// the budget and the last read error, so a failure is diagnosable without a rerun.
func TestWaitRealInventoryReportsUnreadableInventory(t *testing.T) {
	previous := activeScenario
	activeScenario = &Scenario{world: &World{}}
	t.Cleanup(func() { activeScenario = previous })

	_, err := waitRealInventory(120*time.Millisecond, func(protocol.InventoryReport) bool { return true })
	if err == nil {
		t.Fatal("waitRealInventory returned no error without a running cluster")
	}
	message := err.Error()
	if !strings.Contains(message, "within 120ms") {
		t.Fatalf("timeout error does not report the budget: %q", message)
	}
	if !strings.Contains(message, "real cluster is not running") {
		t.Fatalf("timeout error does not report the last read error: %q", message)
	}
}

// TestWaitRealInventoryHonoursTheGivenBudget verifies the helper does not exceed
// the budget it is given, so a caller can bound a diagnostic wait.
func TestWaitRealInventoryHonoursTheGivenBudget(t *testing.T) {
	previous := activeScenario
	activeScenario = &Scenario{world: &World{}}
	t.Cleanup(func() { activeScenario = previous })

	started := time.Now()
	if _, err := waitRealInventory(150*time.Millisecond, func(protocol.InventoryReport) bool { return true }); err == nil {
		t.Fatal("waitRealInventory returned no error without a running cluster")
	}
	if elapsed := time.Since(started); elapsed > 3*time.Second {
		t.Fatalf("waitRealInventory waited %s for a 150ms budget", elapsed)
	}
}
