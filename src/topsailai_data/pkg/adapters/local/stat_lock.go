package local

import (
	"context"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"time"

	apperrors "github.com/topsailai/topsailai_data/pkg/errors"
)

// acquireStatLock serializes statistic updates while the caller holds object custody.
// It never creates metadata directories or reacquires the namespace gate.
func acquireStatLock(ctx context.Context, metadataDir string) (*Lock, error) {
	if err := ctx.Err(); err != nil {
		return nil, err
	}
	info, err := os.Lstat(metadataDir)
	if err != nil {
		return nil, fmt.Errorf("inspect statistic directory: %w", err)
	}
	if !info.IsDir() {
		return nil, fmt.Errorf("statistic directory must be a directory: %w", apperrors.ErrInvalidPath)
	}
	path := filepath.Join(metadataDir, "stat.lock")
	if info, err := os.Lstat(path); err == nil {
		if !info.Mode().IsRegular() {
			return nil, fmt.Errorf("statistic lock must be regular: %w", apperrors.ErrInvalidPath)
		}
	} else if !os.IsNotExist(err) {
		return nil, fmt.Errorf("inspect statistic lock: %w", err)
	}
	f, err := os.OpenFile(path, os.O_CREATE|os.O_RDWR, 0o600)
	if err != nil {
		return nil, fmt.Errorf("open statistic lock: %w", err)
	}
	if err := waitStatLock(ctx, f); err != nil {
		return nil, errors.Join(err, f.Close())
	}
	return &Lock{path: path, file: f}, nil
}

// waitStatLock waits only for contention and returns cancellation or permanent errors.
func waitStatLock(ctx context.Context, f *os.File) error {
	for {
		if err := ctx.Err(); err != nil {
			return err
		}
		err := flockAcquire(f, true)
		if err == nil {
			return nil
		}
		if !errors.Is(err, apperrors.ErrObjectLocked) {
			return fmt.Errorf("acquire statistic lock: %w", err)
		}
		timer := time.NewTimer(5 * time.Millisecond)
		select {
		case <-ctx.Done():
			timer.Stop()
			return ctx.Err()
		case <-timer.C:
		}
	}
}

// RecordStat serializes a complete increment while the caller holds object custody.
// The metadata directory must already exist; cancellation never allocates it.
func RecordStat(ctx context.Context, metadataDir string, write bool, now time.Time, debounce time.Duration) (err error) {
	lock, err := acquireStatLock(ctx, metadataDir)
	if err != nil {
		return err
	}
	defer func() { err = errors.Join(err, lock.Release()) }()
	if err := ctx.Err(); err != nil {
		return err
	}
	if write {
		return IncrementWrite(metadataDir, now)
	}
	return IncrementRead(metadataDir, now, debounce)
}
