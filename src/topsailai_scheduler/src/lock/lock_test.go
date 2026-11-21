package lock

import (
	"os"
	"path/filepath"
	"testing"
	"time"
)

// TestTryAcquireCreatesFolder verifies that the lock folder is created on
// demand, so a task in a new nested folder needs no preparation.
func TestTryAcquireCreatesFolder(t *testing.T) {
	path := filepath.Join(t.TempDir(), "a", "b", "task.lock")

	held, acquired, err := TryAcquire(path)
	if err != nil {
		t.Fatalf("TryAcquire failed: %v", err)
	}
	if !acquired || !held.Held() {
		t.Fatal("expected the lock to be acquired")
	}
	defer func() { _ = held.Release() }()

	if _, statErr := os.Stat(path); statErr != nil {
		t.Fatalf("expected the lock file to exist: %v", statErr)
	}
	if held.Path() != path {
		t.Errorf("expected path %q, got %q", path, held.Path())
	}
}

// TestTryAcquireSecondAttemptFails verifies that a second attempt on a held lock
// reports busy without an error, which is how a still-running task is skipped.
func TestTryAcquireSecondAttemptFails(t *testing.T) {
	path := filepath.Join(t.TempDir(), "task.lock")

	first, acquired, err := TryAcquire(path)
	if err != nil || !acquired {
		t.Fatalf("first acquire: err=%v acquired=%v", err, acquired)
	}
	defer func() { _ = first.Release() }()

	second, secondAcquired, err := TryAcquire(path)
	if err != nil {
		t.Fatalf("a busy lock must not be an error, got %v", err)
	}
	if secondAcquired {
		t.Fatal("expected the second attempt to fail")
	}
	if second.Held() {
		t.Error("expected the second lock to report not held")
	}
	// Releasing a lock that was never held must be a no-op.
	if err := second.Release(); err != nil {
		t.Errorf("releasing an unheld lock must not fail, got %v", err)
	}
}

// TestReleaseAllowsReacquire verifies that releasing makes the lock available
// again, so the next scheduled run proceeds.
func TestReleaseAllowsReacquire(t *testing.T) {
	path := filepath.Join(t.TempDir(), "task.lock")

	first, acquired, err := TryAcquire(path)
	if err != nil || !acquired {
		t.Fatalf("first acquire: err=%v acquired=%v", err, acquired)
	}
	if err := first.Release(); err != nil {
		t.Fatalf("release failed: %v", err)
	}
	if first.Held() {
		t.Error("expected the lock to report not held after release")
	}

	second, secondAcquired, err := TryAcquire(path)
	if err != nil || !secondAcquired {
		t.Fatalf("reacquire: err=%v acquired=%v", err, secondAcquired)
	}
	defer func() { _ = second.Release() }()
}

// TestReleaseIsIdempotent verifies that a double release is harmless, so a
// deferred release cannot fail a run that already released explicitly.
func TestReleaseIsIdempotent(t *testing.T) {
	path := filepath.Join(t.TempDir(), "task.lock")

	held, acquired, err := TryAcquire(path)
	if err != nil || !acquired {
		t.Fatalf("acquire: err=%v acquired=%v", err, acquired)
	}
	if err := held.Release(); err != nil {
		t.Fatalf("first release failed: %v", err)
	}
	if err := held.Release(); err != nil {
		t.Fatalf("second release must not fail, got %v", err)
	}
}

// TestLockFileSurvivesRelease verifies that the lock file stays on disk, because
// it is a handle rather than a state marker.
func TestLockFileSurvivesRelease(t *testing.T) {
	path := filepath.Join(t.TempDir(), "task.lock")

	held, acquired, err := TryAcquire(path)
	if err != nil || !acquired {
		t.Fatalf("acquire: err=%v acquired=%v", err, acquired)
	}
	if err := held.Release(); err != nil {
		t.Fatalf("release failed: %v", err)
	}
	if _, statErr := os.Stat(path); statErr != nil {
		t.Fatalf("expected the lock file to remain on disk: %v", statErr)
	}
}

// TestNilLockIsSafe verifies that the zero value is usable, so a caller need not
// branch on a nil lock.
func TestNilLockIsSafe(t *testing.T) {
	var empty *Lock
	if empty.Held() {
		t.Error("a nil lock must not report held")
	}
	if empty.Path() != "" {
		t.Errorf("a nil lock must report an empty path, got %q", empty.Path())
	}
	if err := empty.Release(); err != nil {
		t.Errorf("releasing a nil lock must not fail, got %v", err)
	}
}

// TestRecordRoundTrip verifies that a record written while the lock is held can
// be read back, which is what a restart relies on to find the in-flight run.
func TestRecordRoundTrip(t *testing.T) {
	path := filepath.Join(t.TempDir(), "task.lock")

	held, acquired, err := TryAcquire(path)
	if err != nil || !acquired {
		t.Fatalf("acquire: err=%v acquired=%v", err, acquired)
	}
	defer func() { _ = held.Release() }()

	want := Record{
		RunID:        "run-42",
		Provider:     "mock",
		PID:          4242,
		StartedAt:    time.Now().Truncate(time.Second),
		SchedulerPID: 99,
	}
	if writeErr := held.WriteRecord(want); writeErr != nil {
		t.Fatalf("WriteRecord failed: %v", writeErr)
	}

	got, readErr := ReadRecord(path)
	if readErr != nil {
		t.Fatalf("ReadRecord failed: %v", readErr)
	}
	if got.RunID != want.RunID || got.Provider != want.Provider || got.PID != want.PID {
		t.Fatalf("expected %+v, got %+v", want, got)
	}
	if got.SchedulerPID != want.SchedulerPID {
		t.Errorf("expected scheduler pid %d, got %d", want.SchedulerPID, got.SchedulerPID)
	}
	if !got.StartedAt.Equal(want.StartedAt) {
		t.Errorf("expected started_at %v, got %v", want.StartedAt, got.StartedAt)
	}
}

// TestWriteRecordKeepsTheLockedInode verifies that writing a record does not
// replace the file.
//
// This is the property the whole design rests on. A rename would give the path a
// new inode while the flock stayed on the old one, so the next process would lock
// the new file successfully and mutual exclusion would be silently gone.
func TestWriteRecordKeepsTheLockedInode(t *testing.T) {
	path := filepath.Join(t.TempDir(), "task.lock")

	held, acquired, err := TryAcquire(path)
	if err != nil || !acquired {
		t.Fatalf("acquire: err=%v acquired=%v", err, acquired)
	}
	defer func() { _ = held.Release() }()

	before, statErr := os.Stat(path)
	if statErr != nil {
		t.Fatalf("stat before: %v", statErr)
	}

	if writeErr := held.WriteRecord(Record{RunID: "run-1", Provider: "mock"}); writeErr != nil {
		t.Fatalf("WriteRecord failed: %v", writeErr)
	}

	after, statErr := os.Stat(path)
	if statErr != nil {
		t.Fatalf("stat after: %v", statErr)
	}
	if !os.SameFile(before, after) {
		t.Fatal("writing the record replaced the lock file, which would break mutual exclusion")
	}

	// The lock must still be exclusive after the write.
	second, secondAcquired, secondErr := TryAcquire(path)
	if secondErr != nil {
		t.Fatalf("second acquire: %v", secondErr)
	}
	if secondAcquired {
		_ = second.Release()
		t.Fatal("the lock was lost after writing the record")
	}
}

// TestClearRecordEmptiesTheFile verifies that clearing leaves an empty file
// rather than removing it, so the inode and the lock survive.
func TestClearRecordEmptiesTheFile(t *testing.T) {
	path := filepath.Join(t.TempDir(), "task.lock")

	held, acquired, err := TryAcquire(path)
	if err != nil || !acquired {
		t.Fatalf("acquire: err=%v acquired=%v", err, acquired)
	}
	defer func() { _ = held.Release() }()

	if writeErr := held.WriteRecord(Record{RunID: "run-1", Provider: "mock"}); writeErr != nil {
		t.Fatalf("WriteRecord failed: %v", writeErr)
	}
	if clearErr := held.ClearRecord(); clearErr != nil {
		t.Fatalf("ClearRecord failed: %v", clearErr)
	}

	content, readErr := os.ReadFile(path)
	if readErr != nil {
		t.Fatalf("read after clear: %v", readErr)
	}
	if len(content) != 0 {
		t.Fatalf("expected an empty file, got %q", string(content))
	}

	record, recordErr := ReadRecord(path)
	if recordErr != nil {
		t.Fatalf("ReadRecord after clear: %v", recordErr)
	}
	if !record.IsZero() {
		t.Fatalf("expected a zero record after clear, got %+v", record)
	}
}

// TestReadRecordTreatsMissingAndTornFilesAsUnknown verifies that every
// uninformative file reports a zero record without an error.
//
// None of these cases is evidence that nothing was running, so the caller must
// see "unknown" rather than a failure it might mistake for "no run".
func TestReadRecordTreatsMissingAndTornFilesAsUnknown(t *testing.T) {
	folder := t.TempDir()

	cases := map[string]string{
		"missing": "",
		"empty":   "",
		"torn":    `{"run_id":"run-1","provid`,
		"garbage": "not json at all",
	}

	for name, content := range cases {
		t.Run(name, func(t *testing.T) {
			path := filepath.Join(folder, name+".lock")
			if content != "" {
				if err := os.WriteFile(path, []byte(content), 0o600); err != nil {
					t.Fatalf("write fixture: %v", err)
				}
			}

			record, err := ReadRecord(path)
			if err != nil {
				t.Fatalf("expected no error, got %v", err)
			}
			if !record.IsZero() {
				t.Fatalf("expected a zero record, got %+v", record)
			}
		})
	}
}

// TestRecordSurvivesRelease verifies that releasing the lock does not erase the
// record, so a supervisor that ends abnormally leaves the breadcrumb behind.
func TestRecordSurvivesRelease(t *testing.T) {
	path := filepath.Join(t.TempDir(), "task.lock")

	held, acquired, err := TryAcquire(path)
	if err != nil || !acquired {
		t.Fatalf("acquire: err=%v acquired=%v", err, acquired)
	}
	if writeErr := held.WriteRecord(Record{RunID: "run-7", Provider: "mock"}); writeErr != nil {
		t.Fatalf("WriteRecord failed: %v", writeErr)
	}
	if releaseErr := held.Release(); releaseErr != nil {
		t.Fatalf("Release failed: %v", releaseErr)
	}

	record, readErr := ReadRecord(path)
	if readErr != nil {
		t.Fatalf("ReadRecord failed: %v", readErr)
	}
	if record.RunID != "run-7" {
		t.Fatalf("expected the record to survive release, got %+v", record)
	}
}
