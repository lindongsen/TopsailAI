package local

import (
	"encoding/json"
	"fmt"
	"io"
	"log/slog"
	"os"
	"path/filepath"

	apperrors "github.com/topsailai/topsailai_data/pkg/errors"
	"github.com/topsailai/topsailai_data/pkg/models"
)

const layoutMarkerName = "topsailai_data.json"

// layoutMarker identifies the fresh-store format independently of object schema.
type layoutMarker struct {
	Layout        string `json:"layout"`
	LayoutVersion int    `json:"layout_version"`
	SchemaVersion int    `json:"schema_version"`
}

// Init prepares or validates the new store layout without migrating old stores.
// It is not used by legacy adapters until the coherent runtime cutover.
func (l StoreLayout) Init() error {
	if l.storeRoot == "" {
		return fmt.Errorf("uninitialized layout: %w", apperrors.ErrInvalidPath)
	}
	if err := os.MkdirAll(l.storeRoot, 0o755); err != nil {
		return fmt.Errorf("create store root: %w", err)
	}
	if err := requireLayoutDirectory(l.storeRoot); err != nil {
		return err
	}
	lock, err := AcquireNamespaceLock(l.storeRoot)
	if err != nil {
		return err
	}
	defer func() {
		if err := lock.Release(); err != nil {
			slog.Error("release layout initialization lock", "error", err)
		}
	}()
	if err := l.prepareLayoutMarker(); err != nil {
		return err
	}
	for _, path := range []string{l.ObjectRoot(), l.MetaRoot()} {
		if err := os.Mkdir(path, 0o755); err != nil && !os.IsExist(err) {
			return fmt.Errorf("create layout tree %q: %w", path, err)
		}
		if err := requireLayoutDirectory(path); err != nil {
			return err
		}
	}
	return nil
}

// requireLayoutDirectory rejects symlinks and other non-directory tree roots.
func requireLayoutDirectory(path string) error {
	info, err := os.Lstat(path)
	if err != nil {
		return fmt.Errorf("inspect layout directory %q: %w", path, err)
	}
	if !info.IsDir() {
		return fmt.Errorf("layout root %q is not a directory: %w", path, apperrors.ErrInvalidPath)
	}
	return nil
}

// prepareLayoutMarker accepts only the known format or an empty fresh root.
func (l StoreLayout) prepareLayoutMarker() error {
	path := filepath.Join(l.storeRoot, layoutMarkerName)
	info, err := os.Lstat(path)
	if err == nil {
		if !info.Mode().IsRegular() {
			return fmt.Errorf("layout marker must be regular: %w", apperrors.ErrInvalidPath)
		}
		return validateLayoutMarker(path)
	}
	if !os.IsNotExist(err) {
		return fmt.Errorf("inspect layout marker: %w", err)
	}
	if err := l.requireFreshLayoutRoot(); err != nil {
		return err
	}
	marker := layoutMarker{Layout: "object-meta", LayoutVersion: 1, SchemaVersion: models.CurrentSchemaVersion}
	data, err := json.Marshal(marker)
	if err != nil {
		return fmt.Errorf("encode layout marker: %w", err)
	}
	return publishLayoutMarker(path, append(data, '\n'))
}

// publishLayoutMarker publishes only a fully written marker under the namespace lock.
func publishLayoutMarker(path string, data []byte) error {
	f, err := os.CreateTemp(filepath.Dir(path), ".layout-marker-*.tmp")
	if err != nil {
		return fmt.Errorf("create temporary layout marker: %w", err)
	}
	defer func() {
		_ = f.Close()
		if err := os.Remove(f.Name()); err == nil {
			slog.Info("removed temporary layout marker", "path", f.Name())
		} else if !os.IsNotExist(err) {
			slog.Error("remove temporary layout marker", "path", f.Name(), "error", err)
		}
	}()
	if _, err := f.Write(data); err != nil {
		return fmt.Errorf("write layout marker: %w", err)
	}
	if err := f.Sync(); err != nil {
		return fmt.Errorf("sync layout marker: %w", err)
	}
	if err := f.Close(); err != nil {
		return fmt.Errorf("close layout marker: %w", err)
	}
	if err := os.Rename(f.Name(), path); err != nil {
		return fmt.Errorf("publish layout marker: %w", err)
	}
	return nil
}

// requireFreshLayoutRoot reads at most two entries to reject nonempty stores.
func (l StoreLayout) requireFreshLayoutRoot() error {
	f, err := os.Open(l.storeRoot)
	if err != nil {
		return fmt.Errorf("open fresh store root: %w", err)
	}
	defer f.Close()
	entries, err := f.Readdirnames(2)
	if err != nil && err != io.EOF {
		return fmt.Errorf("read fresh store root: %w", err)
	}
	for _, name := range entries {
		if name != ".topsailai-data-namespace.lock" {
			return fmt.Errorf("unmarked nonempty store requires a fresh root; migration is unsupported: %w", apperrors.ErrInvalidPath)
		}
	}
	return nil
}

// validateLayoutMarker bounds reads and refuses unknown layout/schema versions.
func validateLayoutMarker(path string) error {
	f, err := os.Open(path)
	if err != nil {
		return fmt.Errorf("open layout marker: %w", err)
	}
	defer f.Close()
	data, err := io.ReadAll(io.LimitReader(f, 4097))
	if err != nil {
		return fmt.Errorf("read layout marker: %w", err)
	}
	var marker layoutMarker
	if len(data) > 4096 || json.Unmarshal(data, &marker) != nil {
		return fmt.Errorf("invalid layout marker: %w", apperrors.ErrCorruptedMetadata)
	}
	if marker.Layout != "object-meta" || marker.LayoutVersion != 1 || marker.SchemaVersion != models.CurrentSchemaVersion {
		return fmt.Errorf("unsupported layout %q version %d schema %d: %w", marker.Layout, marker.LayoutVersion, marker.SchemaVersion, apperrors.ErrCorruptedMetadata)
	}
	return nil
}
