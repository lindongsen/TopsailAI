package local

import (
	"context"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"strings"

	apperrors "github.com/topsailai/topsailai_data/pkg/errors"
	"github.com/topsailai/topsailai_data/pkg/models"
)

// scanMetadataRecords enumerates metadata only, including lifecycle recovery states.
// Concurrently removed records are skipped; corruption never returns partial success.
func (l StoreLayout) scanMetadataRecords(ctx context.Context) ([]*models.Object, error) {
	if l.storeRoot == "" {
		return nil, fmt.Errorf("uninitialized metadata scan: %w", apperrors.ErrInvalidPath)
	}
	objects := []*models.Object{}
	err := l.walkMetadataShards(ctx, l.MetaRoot(), nil, &objects)
	if err != nil {
		return nil, err
	}
	return objects, nil
}

// walkMetadataShards traverses three shard levels and validates each hash leaf.
func (l StoreLayout) walkMetadataShards(ctx context.Context, dir string, shards []string, objects *[]*models.Object) error {
	if err := ctx.Err(); err != nil {
		return err
	}
	if err := checkMetadataDirectory(dir); err != nil {
		return err
	}
	entries, err := os.ReadDir(dir)
	if os.IsNotExist(err) {
		return nil
	}
	if err != nil {
		return fmt.Errorf("enumerate metadata %q: %w", dir, err)
	}
	for _, entry := range entries {
		if err := ctx.Err(); err != nil {
			return err
		}
		name := entry.Name()
		if err := validateMetadataShardEntry(entry, shards); err != nil {
			return fmt.Errorf("metadata directory %q: %w", dir, err)
		}
		path := filepath.Join(dir, name)
		if len(shards) == 3 {
			if err := l.appendMetadataLeaf(ctx, path, objects); err != nil {
				return err
			}
			continue
		}
		next := append(append([]string{}, shards...), name)
		if err := l.walkMetadataShards(ctx, path, next, objects); err != nil {
			return err
		}
	}
	return nil
}

// validateMetadataShardEntry requires lowercase hash components and real directories.
func validateMetadataShardEntry(entry os.DirEntry, shards []string) error {
	name := entry.Name()
	size := 2
	if len(shards) == 3 {
		size = 64
	}
	if !entry.IsDir() || len(name) != size || strings.Trim(name, "0123456789abcdef") != "" {
		return fmt.Errorf("invalid hash directory %q: %w", name, apperrors.ErrCorruptedMetadata)
	}
	if size == 64 && !strings.HasPrefix(name, strings.Join(shards, "")) {
		return fmt.Errorf("hash directory %q differs from shards: %w", name, apperrors.ErrCorruptedMetadata)
	}
	return nil
}

// appendMetadataLeaf validates identity and loads only the leaf record and tags.
func (l StoreLayout) appendMetadataLeaf(ctx context.Context, dir string, objects *[]*models.Object) error {
	if err := ctx.Err(); err != nil {
		return err
	}
	path := filepath.Join(dir, "metadata.json")
	if err := checkMetadataRecordFile(path); err != nil {
		return err
	}
	data, err := os.ReadFile(path)
	if os.IsNotExist(err) {
		return nil
	}
	if err != nil {
		return fmt.Errorf("read metadata leaf %q: %w", path, err)
	}
	obj, err := decodeMetadataRecord(data)
	if err != nil {
		return fmt.Errorf("decode metadata leaf %q: %w", path, err)
	}
	expected, err := l.ObjectMetaPath(obj.ID)
	if err != nil || expected != dir {
		return fmt.Errorf("metadata identity misplaced at %q: %w", dir, errors.Join(apperrors.ErrCorruptedMetadata, err))
	}
	obj.Tags, err = readObjectTags(dir)
	if err != nil {
		return err
	}
	*objects = append(*objects, obj)
	return nil
}
