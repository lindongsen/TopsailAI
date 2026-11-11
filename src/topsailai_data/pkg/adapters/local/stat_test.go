package local

import (
	"archive/tar"
	"bytes"
	"context"
	"io"
	"log/slog"
	"os"
	"strings"
	"testing"
	"time"

	"github.com/topsailai/topsailai_data/pkg/models"
)

func TestReadStatMissingReturnsZeroValue(t *testing.T) {
	objectDir := t.TempDir()

	stat, err := ReadStat(objectDir)
	if err != nil {
		t.Fatalf("ReadStat failed: %v", err)
	}
	if stat.SchemaVersion != 0 || stat.ReadCount != 0 || stat.WriteCount != 0 {
		t.Fatalf("expected zero-valued stat, got %+v", stat)
	}
	if stat.LastReadAt != nil || stat.LastWrittenAt != nil {
		t.Fatalf("expected nil timestamps, got %+v", stat)
	}
}

func TestIncrementReadAndWritePersistStat(t *testing.T) {
	objectDir := t.TempDir()
	readAt := time.Date(2026, 8, 24, 10, 0, 0, 0, time.Local)
	writtenAt := readAt.Add(time.Minute)

	if err := IncrementRead(objectDir, readAt, 0); err != nil {
		t.Fatalf("IncrementRead failed: %v", err)
	}
	if err := IncrementWrite(objectDir, writtenAt); err != nil {
		t.Fatalf("IncrementWrite failed: %v", err)
	}
	stat, err := ReadStat(objectDir)
	if err != nil {
		t.Fatalf("ReadStat failed: %v", err)
	}
	if stat.SchemaVersion != models.ObjectStatSchemaVersion {
		t.Fatalf("schema version = %d, want %d", stat.SchemaVersion, models.ObjectStatSchemaVersion)
	}
	if stat.ReadCount != 1 || stat.WriteCount != 1 {
		t.Fatalf("counts = read %d write %d, want 1 and 1", stat.ReadCount, stat.WriteCount)
	}
	if stat.LastReadAt == nil || !stat.LastReadAt.Equal(readAt) {
		t.Fatalf("last read = %v, want %v", stat.LastReadAt, readAt)
	}
	if stat.LastWrittenAt == nil || !stat.LastWrittenAt.Equal(writtenAt) {
		t.Fatalf("last write = %v, want %v", stat.LastWrittenAt, writtenAt)
	}
}

func TestIncrementReadDebouncesTimestampOnly(t *testing.T) {
	objectDir := t.TempDir()
	first := time.Date(2026, 8, 24, 10, 0, 0, 0, time.Local)
	second := first.Add(30 * time.Second)

	if err := IncrementRead(objectDir, first, time.Minute); err != nil {
		t.Fatalf("first IncrementRead failed: %v", err)
	}
	if err := IncrementRead(objectDir, second, time.Minute); err != nil {
		t.Fatalf("second IncrementRead failed: %v", err)
	}
	stat, err := ReadStat(objectDir)
	if err != nil {
		t.Fatalf("ReadStat failed: %v", err)
	}
	if stat.ReadCount != 2 {
		t.Fatalf("read count = %d, want 2", stat.ReadCount)
	}
	if stat.LastReadAt == nil || !stat.LastReadAt.Equal(first) {
		t.Fatalf("last read = %v, want debounced timestamp %v", stat.LastReadAt, first)
	}
}

func TestReadStatCorruptReturnsZeroValue(t *testing.T) {
	objectDir := t.TempDir()
	if err := os.WriteFile(StatFilePath(objectDir), []byte("{invalid"), 0o644); err != nil {
		t.Fatalf("write corrupt stat: %v", err)
	}

	stat, err := ReadStat(objectDir)
	if err != nil {
		t.Fatalf("ReadStat failed: %v", err)
	}
	if stat.ReadCount != 0 || stat.WriteCount != 0 || stat.LastReadAt != nil || stat.LastWrittenAt != nil {
		t.Fatalf("expected zero-valued stat, got %+v", stat)
	}
}

func TestWriteStatAtomicallyReplacesFile(t *testing.T) {
	objectDir := t.TempDir()
	stat := &models.ObjectStat{SchemaVersion: models.ObjectStatSchemaVersion, ReadCount: 7}

	if err := WriteStat(objectDir, stat); err != nil {
		t.Fatalf("WriteStat failed: %v", err)
	}
	entries, err := os.ReadDir(objectDir)
	if err != nil {
		t.Fatalf("ReadDir failed: %v", err)
	}
	if len(entries) != 1 || entries[0].Name() != statFileName {
		t.Fatalf("expected only %s after atomic write, got %v", statFileName, entries)
	}
	read, err := ReadStat(objectDir)
	if err != nil {
		t.Fatalf("ReadStat failed: %v", err)
	}
	if read.ReadCount != 7 {
		t.Fatalf("read count = %d, want 7", read.ReadCount)
	}
}

// TestStatFileIsSeparateFromActualData preserves user-owned statistic names.
func TestStatFileIsSeparateFromActualData(t *testing.T) {
	ctx := context.Background()
	root := t.TempDir()
	adapter := NewActualDataAdapter(root)
	if err := adapter.Init(ctx); err != nil {
		t.Fatal(err)
	}
	layout, err := NewStoreLayout(root)
	if err != nil {
		t.Fatal(err)
	}
	meta, err := layout.ObjectMetaPath("obj")
	if err != nil {
		t.Fatal(err)
	}
	if err := os.MkdirAll(meta, 0700); err != nil {
		t.Fatal(err)
	}
	if err := WriteStat(meta, &models.ObjectStat{SchemaVersion: models.ObjectStatSchemaVersion, ReadCount: 7}); err != nil {
		t.Fatal(err)
	}
	ref := "2026/1111/0604/obj"
	for name, body := range map[string]string{"obj.md": "object", statFileName: "user statistic"} {
		if _, err := adapter.WriteFile(ctx, ref, name, strings.NewReader(body)); err != nil {
			t.Fatal(err)
		}
	}
	reader, err := adapter.ReadFile(ctx, ref, statFileName)
	if err != nil {
		t.Fatal(err)
	}
	data, readErr := io.ReadAll(reader)
	closeErr := reader.Close()
	if readErr != nil || closeErr != nil || string(data) != "user statistic" {
		t.Fatalf("user statistic: %q %v %v", data, readErr, closeErr)
	}
	archive, err := adapter.ReadArchive(ctx, ref)
	if err != nil {
		t.Fatal(err)
	}
	defer archive.Close()
	tr := tar.NewReader(archive)
	found := false
	for {
		header, err := tr.Next()
		if err == io.EOF {
			break
		}
		if err != nil {
			t.Fatal(err)
		}
		if header.Name == statFileName {
			body, err := io.ReadAll(tr)
			if err != nil || string(body) != "user statistic" {
				t.Fatalf("archive statistic: %q %v", body, err)
			}
			found = true
		}
	}
	if !found {
		t.Fatal("archive omitted user statistic")
	}
	if err := adapter.Delete(ctx, ref); err != nil {
		t.Fatal(err)
	}
	stat, err := ReadStat(meta)
	if err != nil || stat.ReadCount != 7 {
		t.Fatalf("payload deletion changed internal statistic: %+v %v", stat, err)
	}
}

func TestRemoveStatFileRemovesAndLogs(t *testing.T) {
	objectDir := t.TempDir()
	if err := WriteStat(objectDir, &models.ObjectStat{SchemaVersion: models.ObjectStatSchemaVersion}); err != nil {
		t.Fatalf("WriteStat failed: %v", err)
	}

	var logs bytes.Buffer
	previous := slog.Default()
	slog.SetDefault(slog.New(slog.NewTextHandler(&logs, nil)))
	t.Cleanup(func() { slog.SetDefault(previous) })

	if err := RemoveStatFile(objectDir); err != nil {
		t.Fatalf("RemoveStatFile failed: %v", err)
	}
	if _, err := os.Stat(StatFilePath(objectDir)); !os.IsNotExist(err) {
		t.Fatalf("stat file should be removed, got %v", err)
	}
	if !strings.Contains(logs.String(), "removed object stat file") {
		t.Fatalf("expected stat deletion log, got %q", logs.String())
	}
	if err := RemoveStatFile(objectDir); err != nil {
		t.Fatalf("missing stat cleanup should succeed: %v", err)
	}
}
