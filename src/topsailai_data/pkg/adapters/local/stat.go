// Package local implements the local filesystem adapter for topsailai_data.
package local

import (
	"encoding/json"
	"fmt"
	"log/slog"
	"os"
	"path/filepath"
	"time"

	"github.com/topsailai/topsailai_data/pkg/models"
)

const statFileName = ".stat.json"

// StatFilePath returns the path of the stat file inside objectDir.
func StatFilePath(objectDir string) string {
	return filepath.Join(objectDir, statFileName)
}

// RemoveStatFile removes an object's stat record and logs the deletion.
// A missing stat file is treated as an already-completed cleanup.
func RemoveStatFile(objectDir string) error {
	path := StatFilePath(objectDir)
	if err := os.Remove(path); err != nil {
		if os.IsNotExist(err) {
			return nil
		}
		return fmt.Errorf("remove object stat %q: %w", path, err)
	}
	slog.Info("removed object stat file", "path", path)
	return nil
}

// ReadStat reads an object's stat record. A missing or corrupt record is
// represented by a zero-valued stat so observability never blocks object use.
func ReadStat(objectDir string) (*models.ObjectStat, error) {
	path := StatFilePath(objectDir)
	data, err := os.ReadFile(path)
	if err != nil {
		if os.IsNotExist(err) {
			return &models.ObjectStat{}, nil
		}
		return nil, fmt.Errorf("read object stat %q: %w", path, err)
	}

	var stat models.ObjectStat
	if err := json.Unmarshal(data, &stat); err != nil {
		slog.Warn("ignoring corrupt object stat", "path", path, "error", err)
		return &models.ObjectStat{}, nil
	}
	return &stat, nil
}

// WriteStat atomically replaces an object's stat record.
func WriteStat(objectDir string, stat *models.ObjectStat) error {
	if stat == nil {
		return fmt.Errorf("write object stat: stat is nil")
	}
	data, err := json.MarshalIndent(stat, "", "  ")
	if err != nil {
		return fmt.Errorf("marshal object stat: %w", err)
	}
	data = append(data, '\n')

	temporary, err := os.CreateTemp(objectDir, ".stat-*.tmp")
	if err != nil {
		return fmt.Errorf("create temporary object stat in %q: %w", objectDir, err)
	}
	temporaryPath := temporary.Name()
	cleanup := func() {
		if err := os.Remove(temporaryPath); err == nil {
			slog.Info("removed temporary object stat file", "path", temporaryPath)
		} else if !os.IsNotExist(err) {
			slog.Warn("failed to remove temporary object stat file", "path", temporaryPath, "error", err)
		}
	}

	if err := temporary.Chmod(0o644); err != nil {
		_ = temporary.Close()
		cleanup()
		return fmt.Errorf("set temporary object stat permissions: %w", err)
	}
	if _, err := temporary.Write(data); err != nil {
		_ = temporary.Close()
		cleanup()
		return fmt.Errorf("write temporary object stat: %w", err)
	}
	if err := temporary.Sync(); err != nil {
		_ = temporary.Close()
		cleanup()
		return fmt.Errorf("sync temporary object stat: %w", err)
	}
	if err := temporary.Close(); err != nil {
		cleanup()
		return fmt.Errorf("close temporary object stat: %w", err)
	}
	if err := os.Rename(temporaryPath, StatFilePath(objectDir)); err != nil {
		cleanup()
		return fmt.Errorf("replace object stat: %w", err)
	}
	return nil
}

// IncrementRead increments the read count and atomically persists the result.
// LastReadAt is updated only when the debounce interval has elapsed.
func IncrementRead(objectDir string, now time.Time, debounce time.Duration) error {
	stat, err := ReadStat(objectDir)
	if err != nil {
		return err
	}
	stat.SchemaVersion = models.ObjectStatSchemaVersion
	stat.ReadCount++
	if stat.LastReadAt == nil || debounce <= 0 || now.Sub(*stat.LastReadAt) >= debounce {
		readAt := now
		stat.LastReadAt = &readAt
	}
	return WriteStat(objectDir, stat)
}

// IncrementWrite increments the write count and atomically persists the result.
func IncrementWrite(objectDir string, now time.Time) error {
	stat, err := ReadStat(objectDir)
	if err != nil {
		return err
	}
	stat.SchemaVersion = models.ObjectStatSchemaVersion
	stat.WriteCount++
	writtenAt := now
	stat.LastWrittenAt = &writtenAt
	return WriteStat(objectDir, stat)
}
