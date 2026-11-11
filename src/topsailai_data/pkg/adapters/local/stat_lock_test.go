package local

import (
	"context"
	"errors"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"sync"
	"testing"
	"time"

	apperrors "github.com/topsailai/topsailai_data/pkg/errors"
)

// incrementLockedStat exercises a complete serialized read/write update pair.
func incrementLockedStat(dir string, count int) error {
	for i := 0; i < count; i++ {
		lock, err := acquireStatLock(context.Background(), dir)
		if err != nil {
			return err
		}
		updateErr := IncrementRead(dir, time.Now(), 0)
		if updateErr == nil {
			updateErr = IncrementWrite(dir, time.Now())
		}
		if err := errors.Join(updateErr, lock.Release()); err != nil {
			return err
		}
	}
	return nil
}

// TestStatLockProcessWorker is invoked only through explicit subprocess arguments.
func TestStatLockProcessWorker(t *testing.T) {
	args := os.Args
	if len(args) < 3 || args[len(args)-2] != "stat-lock-worker" {
		return
	}
	if err := incrementLockedStat(args[len(args)-1], 12); err != nil {
		t.Fatal(err)
	}
}

// TestStatLockConcurrentProcesses proves serialization across independent processes.
func TestStatLockConcurrentProcesses(t *testing.T) {
	dir := t.TempDir()
	executable, err := os.Executable()
	if err != nil {
		t.Fatal(err)
	}
	var wg sync.WaitGroup
	results := make(chan error, 4)
	for i := 0; i < 4; i++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			cmd := exec.Command(executable, "-test.run=^TestStatLockProcessWorker$", "--", "stat-lock-worker", dir)
			output, err := cmd.CombinedOutput()
			if err != nil {
				results <- fmt.Errorf("worker: %w: %s", err, output)
				return
			}
			results <- nil
		}()
	}
	wg.Wait()
	close(results)
	for err := range results {
		if err != nil {
			t.Fatal(err)
		}
	}
	stat, err := ReadStat(dir)
	if err != nil {
		t.Fatal(err)
	}
	if stat.ReadCount != 48 || stat.WriteCount != 48 {
		t.Fatalf("lost increments: %+v", stat)
	}
}

// TestStatLockConcurrentGoroutines proves separate descriptors serialize updates.
func TestStatLockConcurrentGoroutines(t *testing.T) {
	dir := t.TempDir()
	results := make(chan error, 6)
	for i := 0; i < 6; i++ {
		go func() { results <- incrementLockedStat(dir, 10) }()
	}
	for i := 0; i < 6; i++ {
		if err := <-results; err != nil {
			t.Fatal(err)
		}
	}
	stat, err := ReadStat(dir)
	if err != nil {
		t.Fatal(err)
	}
	if stat.ReadCount != 60 || stat.WriteCount != 60 {
		t.Fatalf("lost increments: %+v", stat)
	}
}

// TestStatLockCancellation checks cancellation with an already-held exclusive lock.
func TestStatLockCancellation(t *testing.T) {
	dir := t.TempDir()
	first, err := acquireStatLock(context.Background(), dir)
	if err != nil {
		t.Fatal(err)
	}
	defer first.Release()
	ctx, cancel := context.WithTimeout(context.Background(), 25*time.Millisecond)
	defer cancel()
	lock, err := acquireStatLock(ctx, dir)
	if lock != nil {
		_ = lock.Release()
		t.Fatal("acquired lock while first descriptor holds it")
	}
	if !errors.Is(err, context.DeadlineExceeded) {
		t.Fatalf("cancellation: %v", err)
	}
	if err := first.Release(); err != nil {
		t.Fatal(err)
	}
	next, err := acquireStatLock(context.Background(), dir)
	if err != nil {
		t.Fatal(err)
	}
	if err := next.Release(); err != nil {
		t.Fatal(err)
	}
}

// TestStatLockMissingAndCanceledNeverCreate checks rejection before directory growth.
func TestStatLockMissingAndCanceledNeverCreate(t *testing.T) {
	root := t.TempDir()
	missing := filepath.Join(root, "missing")
	if lock, err := acquireStatLock(context.Background(), missing); err == nil || lock != nil {
		t.Fatal("accepted missing directory")
	}
	if _, err := os.Lstat(missing); !os.IsNotExist(err) {
		t.Fatalf("created missing directory: %v", err)
	}
	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	if lock, err := acquireStatLock(ctx, root); !errors.Is(err, context.Canceled) || lock != nil {
		t.Fatalf("canceled lock: %v", err)
	}
	if _, err := os.Lstat(filepath.Join(root, "stat.lock")); !os.IsNotExist(err) {
		t.Fatalf("created lock: %v", err)
	}
}

// TestStatLockUnsafeLeaves checks aliases and special leaves without modifying targets.
func TestStatLockUnsafeLeaves(t *testing.T) {
	for _, kind := range []string{"live", "dangling", "directory"} {
		t.Run(kind, func(t *testing.T) {
			dir := t.TempDir()
			path := filepath.Join(dir, "stat.lock")
			target := filepath.Join(t.TempDir(), "target")
			if kind == "directory" {
				if err := os.Mkdir(path, 0o700); err != nil {
					t.Fatal(err)
				}
			} else {
				if kind == "live" {
					if err := os.WriteFile(target, []byte("preserved"), 0o600); err != nil {
						t.Fatal(err)
					}
				}
				if err := os.Symlink(target, path); err != nil {
					t.Fatal(err)
				}
			}
			if lock, err := acquireStatLock(context.Background(), dir); !errors.Is(err, apperrors.ErrInvalidPath) || lock != nil {
				t.Fatalf("unsafe lock: %v", err)
			}
			if kind == "live" {
				data, err := os.ReadFile(target)
				if err != nil || string(data) != "preserved" {
					t.Fatalf("target changed: %q %v", data, err)
				}
			}
			if kind == "dangling" {
				if _, err := os.Lstat(target); !os.IsNotExist(err) {
					t.Fatalf("created target: %v", err)
				}
			}
			if kind != "directory" {
				if got, err := os.Readlink(path); err != nil || got != target {
					t.Fatalf("link changed: %q %v", got, err)
				}
			}
		})
	}
}

// TestRecordStatCancellation leaves counters unchanged while another writer holds custody.
func TestRecordStatCancellation(t *testing.T) {
	dir := t.TempDir()
	held, err := acquireStatLock(context.Background(), dir)
	if err != nil {
		t.Fatal(err)
	}
	defer held.Release()
	ctx, cancel := context.WithTimeout(context.Background(), 25*time.Millisecond)
	defer cancel()
	if err := RecordStat(ctx, dir, true, time.Now(), 0); !errors.Is(err, context.DeadlineExceeded) {
		t.Fatalf("record cancellation: %v", err)
	}
	stat, err := ReadStat(dir)
	if err != nil || stat.WriteCount != 0 {
		t.Fatalf("canceled increment: %+v %v", stat, err)
	}
	if err := held.Release(); err != nil {
		t.Fatal(err)
	}
	if err := RecordStat(context.Background(), dir, true, time.Now(), 0); err != nil {
		t.Fatal(err)
	}
	stat, err = ReadStat(dir)
	if err != nil || stat.WriteCount != 1 {
		t.Fatalf("subsequent increment: %+v %v", stat, err)
	}
}
