package local

import (
	"errors"
	"os"
	"path/filepath"
	"testing"
	"time"

	apperrors "github.com/topsailai/topsailai_data/pkg/errors"
)

func TestAcquireWriteLockAndRelease(t *testing.T) {
	root := t.TempDir()
	objectPath := filepath.Join(root, "obj")
	if err := os.MkdirAll(objectPath, 0o755); err != nil {
		t.Fatalf("mkdir object path: %v", err)
	}

	lock, err := AcquireWriteLock(objectPath)
	if err != nil {
		t.Fatalf("AcquireWriteLock failed: %v", err)
	}

	lockPath := filepath.Join(objectPath, "obj.lock")
	if _, err := os.Stat(lockPath); err != nil {
		t.Fatalf("lock file was not created: %v", err)
	}

	if lock.Path() != lockPath {
		t.Fatalf("lock.Path() = %q, want %q", lock.Path(), lockPath)
	}

	if err := lock.Release(); err != nil {
		t.Fatalf("Release failed: %v", err)
	}
}

func TestAcquireReadLockAndRelease(t *testing.T) {
	root := t.TempDir()
	objectPath := filepath.Join(root, "obj")
	if err := os.MkdirAll(objectPath, 0o755); err != nil {
		t.Fatalf("mkdir object path: %v", err)
	}

	lock, err := AcquireReadLock(objectPath)
	if err != nil {
		t.Fatalf("AcquireReadLock failed: %v", err)
	}
	if err := lock.Release(); err != nil {
		t.Fatalf("Release failed: %v", err)
	}
}

func TestWriteLockContention(t *testing.T) {
	root := t.TempDir()
	objectPath := filepath.Join(root, "obj")
	if err := os.MkdirAll(objectPath, 0o755); err != nil {
		t.Fatalf("mkdir object path: %v", err)
	}

	first, err := AcquireWriteLock(objectPath)
	if err != nil {
		t.Fatalf("first AcquireWriteLock failed: %v", err)
	}
	defer first.Release()

	second, err := AcquireWriteLock(objectPath)
	if err == nil {
		second.Release()
		t.Fatal("expected second write lock to fail")
	}
	if !errors.Is(err, apperrors.ErrObjectLocked) {
		t.Fatalf("expected ErrObjectLocked, got %v", err)
	}
}

func TestReadLockSharedAccess(t *testing.T) {
	root := t.TempDir()
	objectPath := filepath.Join(root, "obj")
	if err := os.MkdirAll(objectPath, 0o755); err != nil {
		t.Fatalf("mkdir object path: %v", err)
	}

	first, err := AcquireReadLock(objectPath)
	if err != nil {
		t.Fatalf("first AcquireReadLock failed: %v", err)
	}
	defer first.Release()

	second, err := AcquireReadLock(objectPath)
	if err != nil {
		t.Fatalf("second AcquireReadLock failed: %v", err)
	}
	if err := second.Release(); err != nil {
		t.Fatalf("second Release failed: %v", err)
	}
}

func TestWriteLockBlocksReadLock(t *testing.T) {
	root := t.TempDir()
	objectPath := filepath.Join(root, "obj")
	if err := os.MkdirAll(objectPath, 0o755); err != nil {
		t.Fatalf("mkdir object path: %v", err)
	}

	writeLock, err := AcquireWriteLock(objectPath)
	if err != nil {
		t.Fatalf("AcquireWriteLock failed: %v", err)
	}
	defer writeLock.Release()

	readLock, err := AcquireReadLock(objectPath)
	if err == nil {
		readLock.Release()
		t.Fatal("expected read lock to fail while write lock is held")
	}
	if !errors.Is(err, apperrors.ErrObjectLocked) {
		t.Fatalf("expected ErrObjectLocked, got %v", err)
	}
}

func TestReadLockBlocksWriteLock(t *testing.T) {
	root := t.TempDir()
	objectPath := filepath.Join(root, "obj")
	if err := os.MkdirAll(objectPath, 0o755); err != nil {
		t.Fatalf("mkdir object path: %v", err)
	}

	readLock, err := AcquireReadLock(objectPath)
	if err != nil {
		t.Fatalf("AcquireReadLock failed: %v", err)
	}
	defer readLock.Release()

	writeLock, err := AcquireWriteLock(objectPath)
	if err == nil {
		writeLock.Release()
		t.Fatal("expected write lock to fail while read lock is held")
	}
	if !errors.Is(err, apperrors.ErrObjectLocked) {
		t.Fatalf("expected ErrObjectLocked, got %v", err)
	}
}

func TestLockReleaseTwiceIsSafe(t *testing.T) {
	root := t.TempDir()
	objectPath := filepath.Join(root, "obj")
	if err := os.MkdirAll(objectPath, 0o755); err != nil {
		t.Fatalf("mkdir object path: %v", err)
	}

	lock, err := AcquireWriteLock(objectPath)
	if err != nil {
		t.Fatalf("AcquireWriteLock failed: %v", err)
	}
	if err := lock.Release(); err != nil {
		t.Fatalf("first Release failed: %v", err)
	}
	if err := lock.Release(); err != nil {
		t.Fatalf("second Release failed: %v", err)
	}
}

func TestLockCreatesObjectDirectory(t *testing.T) {
	root := t.TempDir()
	objectPath := filepath.Join(root, "new-obj")

	lock, err := AcquireWriteLock(objectPath)
	if err != nil {
		t.Fatalf("AcquireWriteLock failed: %v", err)
	}
	defer lock.Release()

	if _, err := os.Stat(objectPath); err != nil {
		t.Fatalf("object directory was not created: %v", err)
	}
}

func TestLockReleasedAfterGoroutine(t *testing.T) {
	root := t.TempDir()
	objectPath := filepath.Join(root, "obj")
	if err := os.MkdirAll(objectPath, 0o755); err != nil {
		t.Fatalf("mkdir object path: %v", err)
	}

	acquired := make(chan struct{})
	release := make(chan struct{})

	go func() {
		lock, err := AcquireWriteLock(objectPath)
		if err != nil {
			t.Errorf("goroutine AcquireWriteLock failed: %v", err)
			close(acquired)
			return
		}
		close(acquired)
		<-release
		_ = lock.Release()
	}()

	select {
	case <-acquired:
	case <-time.After(2 * time.Second):
		t.Fatal("goroutine did not acquire lock")
	}

	// The main goroutine should not be able to acquire the lock now.
	_, err := AcquireWriteLock(objectPath)
	if err == nil {
		close(release)
		t.Fatal("expected lock contention with goroutine")
	}
	if !errors.Is(err, apperrors.ErrObjectLocked) {
		close(release)
		t.Fatalf("expected ErrObjectLocked, got %v", err)
	}

	close(release)

	// Wait for the goroutine to actually release the lock before re-acquiring.
	// The kernel releases the flock when the file descriptor is closed, but
	// closing happens asynchronously after the goroutine receives the signal.
	for {
		lock, err := AcquireWriteLock(objectPath)
		if err == nil {
			lock.Release()
			return
		}
		if !errors.Is(err, apperrors.ErrObjectLocked) {
			t.Fatalf("AcquireWriteLock after release failed: %v", err)
		}
		time.Sleep(5 * time.Millisecond)
	}
}
