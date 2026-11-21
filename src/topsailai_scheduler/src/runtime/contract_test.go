package runtime

import "testing"

// TestSnapshotFindReturnsMatchingTask verifies lookup by task id.
func TestSnapshotFindReturnsMatchingTask(t *testing.T) {
	snapshot := Snapshot{
		Tasks: []TaskStatus{
			{ID: "a/b", State: StateIdle},
			{ID: "c", State: StateRunning},
		},
	}

	found, ok := snapshot.Find("c")
	if !ok {
		t.Fatal("expected task c to be found")
	}
	if found.State != StateRunning {
		t.Fatalf("unexpected state %q", found.State)
	}
}

// TestSnapshotFindReportsMissingTask verifies a missing id is reported instead
// of returning a zero status that looks valid.
func TestSnapshotFindReportsMissingTask(t *testing.T) {
	snapshot := Snapshot{Tasks: []TaskStatus{{ID: "a"}}}
	if _, ok := snapshot.Find("missing"); ok {
		t.Fatal("expected a missing task to be reported")
	}
}

// TestSnapshotFindOnEmptySnapshot verifies an empty snapshot is safe.
func TestSnapshotFindOnEmptySnapshot(t *testing.T) {
	var snapshot Snapshot
	if _, ok := snapshot.Find("a"); ok {
		t.Fatal("expected no task in an empty snapshot")
	}
}

// TestSentinelErrorsAreDistinct verifies the contract errors do not collide, so
// a transport can map each one to its own status code.
func TestSentinelErrorsAreDistinct(t *testing.T) {
	all := []error{ErrTaskNotFound, ErrTaskNotRunning, ErrTaskDisabled, ErrShuttingDown}
	seen := make(map[string]bool, len(all))
	for _, err := range all {
		if seen[err.Error()] {
			t.Fatalf("duplicate error message %q", err.Error())
		}
		seen[err.Error()] = true
	}
}

// TestStateValues verifies the reported state strings stay stable, because a
// CLI and any future transport display them directly.
func TestStateValues(t *testing.T) {
	cases := map[State]string{
		StateIdle:     "idle",
		StateRunning:  "running",
		StateDisabled: "disabled",
		StateInvalid:  "invalid",
	}
	for state, want := range cases {
		if string(state) != want {
			t.Fatalf("state %v: want %q, got %q", state, want, string(state))
		}
	}
}
