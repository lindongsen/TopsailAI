package local

import (
	"fmt"
	"log/slog"
	"os"
	"path/filepath"

	apperrors "github.com/topsailai/topsailai_data/pkg/errors"
	"github.com/topsailai/topsailai_data/pkg/models"
)

// readMetadataRecord loads an ID-addressed record without scanning payloads.
// Callers coordinate lifecycle changes through the metadata lock protocol.
func (l StoreLayout) readMetadataRecord(id models.ObjectID) (*models.Object, error) {
	dir, err := l.ResolveObjectMetaPath(id)
	if err != nil {
		return nil, err
	}
	path := filepath.Join(dir, "metadata.json")
	if err := checkMetadataRecordFile(path); err != nil {
		return nil, err
	}
	data, err := os.ReadFile(path)
	if os.IsNotExist(err) {
		return nil, fmt.Errorf("metadata for %q: %w", id, apperrors.ErrObjectNotFound)
	}
	if err != nil {
		return nil, fmt.Errorf("read metadata record %q: %w", path, err)
	}
	obj, err := decodeMetadataRecord(data)
	if err != nil {
		return nil, fmt.Errorf("read metadata record %q: %w", path, err)
	}
	if obj.ID != id {
		return nil, fmt.Errorf("metadata identity %q differs from requested %q: %w", obj.ID, id, apperrors.ErrCorruptedMetadata)
	}
	return obj, nil
}

// writeMetadataRecord atomically replaces the tag-free record under an object lock.
// The metadata directory must already exist; failed writes preserve old contents.
func (l StoreLayout) writeMetadataRecord(obj *models.Object) error {
	data, err := encodeMetadataRecord(obj)
	if err != nil {
		return err
	}
	dir, err := l.ResolveObjectMetaPath(obj.ID)
	if err != nil {
		return err
	}
	path := filepath.Join(dir, "metadata.json")
	if err := checkMetadataRecordFile(path); err != nil {
		return err
	}
	return publishMetadataRecord(path, data)
}

// checkMetadataRecordFile rejects aliases and special nodes while allowing creation.
func checkMetadataRecordFile(path string) error {
	info, err := os.Lstat(path)
	if os.IsNotExist(err) {
		return nil
	}
	if err != nil {
		return fmt.Errorf("inspect metadata record %q: %w", path, err)
	}
	if !info.Mode().IsRegular() {
		return fmt.Errorf("metadata record %q must be regular: %w", path, apperrors.ErrCorruptedMetadata)
	}
	return nil
}

// publishMetadataRecord commits a fully written temporary record by rename.
func publishMetadataRecord(path string, data []byte) error {
	f, err := os.CreateTemp(filepath.Dir(path), ".metadata-*.tmp")
	if err != nil {
		return fmt.Errorf("create temporary metadata record: %w", err)
	}
	defer func() {
		_ = f.Close()
		if err := os.Remove(f.Name()); err == nil {
			slog.Info("removed temporary metadata record", "path", f.Name())
		} else if !os.IsNotExist(err) {
			slog.Error("remove temporary metadata record", "path", f.Name(), "error", err)
		}
	}()
	if _, err := f.Write(data); err != nil {
		return fmt.Errorf("write temporary metadata record: %w", err)
	}
	if err := f.Sync(); err != nil {
		return fmt.Errorf("sync temporary metadata record: %w", err)
	}
	if err := f.Close(); err != nil {
		return fmt.Errorf("close temporary metadata record: %w", err)
	}
	if err := os.Rename(f.Name(), path); err != nil {
		return fmt.Errorf("publish metadata record: %w", err)
	}
	return nil
}
