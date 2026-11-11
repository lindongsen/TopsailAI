package local

import (
	"context"
	"fmt"
	"os"
	"path/filepath"
	"testing"
	"time"

	"github.com/topsailai/topsailai_data/pkg/models"
)

// BenchmarkMetadataDiskScale measures real metadata I/O without payload traversal.
func BenchmarkMetadataDiskScale(b *testing.B) {
	for _, count := range []int{1000, 100000} {
		b.Run(fmt.Sprintf("objects-%d", count), func(b *testing.B) {
			root := b.TempDir()
			b.Cleanup(func() { b.Logf("deleting disk-scale fixture tree: %s", root) })
			ctx := context.Background()
			adapter := NewMetadataAdapter(root)
			if err := adapter.Init(ctx); err != nil {
				b.Fatal(err)
			}
			layout, err := NewStoreLayout(root)
			if err != nil {
				b.Fatal(err)
			}
			started := time.Now()
			for i := 0; i < count; i++ {
				id := models.ObjectID(fmt.Sprintf("scale-%06d", i))
				ref := "2026/1111/1200/" + string(id)
				obj := &models.Object{ID: id, Name: string(id), Path: ref, DataRef: ref, Status: models.ObjectStatusActive, SchemaVersion: models.CurrentSchemaVersion}
				data, err := encodeMetadataRecord(obj)
				if err != nil {
					b.Fatal(err)
				}
				dir, err := layout.ObjectMetaPath(id)
				if err != nil {
					b.Fatal(err)
				}
				if err := os.MkdirAll(dir, 0755); err != nil {
					b.Fatal(err)
				}
				if err := os.WriteFile(filepath.Join(dir, "metadata.json"), data, 0600); err != nil {
					b.Fatal(err)
				}
				tag := "ordinary\n"
				if i == count-1 {
					tag = "unique-scale-target\n"
				}
				if err := os.WriteFile(filepath.Join(dir, "tags"), []byte(tag), 0600); err != nil {
					b.Fatal(err)
				}
			}
			b.Logf("fixture records=%d setup=%s (not production creation throughput)", count, time.Since(started))
			target := models.ObjectID(fmt.Sprintf("scale-%06d", count-1))
			b.Run("Init", func(b *testing.B) {
				for i := 0; i < b.N; i++ {
					if err := adapter.Init(ctx); err != nil {
						b.Fatal(err)
					}
				}
			})
			b.Run("Get", func(b *testing.B) {
				for i := 0; i < b.N; i++ {
					obj, err := adapter.Get(ctx, target, false)
					if err != nil {
						b.Fatal(err)
					}
					if obj.ID != target {
						b.Fatalf("wrong ID: %s", obj.ID)
					}
				}
			})
			b.Run("List", func(b *testing.B) {
				for i := 0; i < b.N; i++ {
					objects, err := adapter.List(ctx, models.ListOptions{})
					if err != nil {
						b.Fatal(err)
					}
					if len(objects) != count {
						b.Fatalf("list count=%d want=%d", len(objects), count)
					}
				}
			})
			b.Run("Search", func(b *testing.B) {
				for i := 0; i < b.N; i++ {
					objects, err := adapter.Search(ctx, []string{"unique-scale-target"}, models.ListOptions{})
					if err != nil {
						b.Fatal(err)
					}
					if len(objects) != 1 || objects[0].ID != target {
						b.Fatalf("incorrect search result: %v", objects)
					}
				}
			})
		})
	}
}
