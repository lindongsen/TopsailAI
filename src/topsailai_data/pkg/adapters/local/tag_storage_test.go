package local

import (
	"errors"
	"os"
	"path/filepath"
	"reflect"
	"strings"
	"testing"

	apperrors "github.com/topsailai/topsailai_data/pkg/errors"
)

// TestObjectTagStorageRoundTrip covers missing, deduplicated, maximum and empty sets.
func TestObjectTagStorageRoundTrip(t *testing.T) {
	dir := t.TempDir()
	got, err := readObjectTags(dir)
	if err != nil || len(got) != 0 {
		t.Fatalf("missing: %v %v", got, err)
	}
	for _, tags := range [][]string{{"work", "中文", "with space", "work"}, {strings.Repeat("a", maxStoredTagBytes)}, {}} {
		if err := writeObjectTags(dir, tags); err != nil {
			t.Fatal(err)
		}
		got, err := readObjectTags(dir)
		if err != nil || !reflect.DeepEqual(got, MergeTags(nil, tags)) {
			t.Fatalf("round trip: %v", err)
		}
	}
	entries, err := os.ReadDir(dir)
	if err != nil || len(entries) != 1 || entries[0].Name() != "tags" {
		t.Fatalf("unexpected entries: %v %v", entries, err)
	}
}

// TestObjectTagStorageInvalidPreserves checks rejection before replacing prior bytes.
func TestObjectTagStorageInvalidPreserves(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, "tags")
	if err := writeObjectTags(dir, []string{"keep"}); err != nil {
		t.Fatal(err)
	}
	for _, tag := range []string{"", "two\nlines", "\ttab", "inner\tcontrol", "#comment", ";comment", "--comment", " a", "a\u00a0", "a/b", "\xff", strings.Repeat("a", maxStoredTagBytes+1)} {
		if err := writeObjectTags(dir, []string{tag}); !errors.Is(err, apperrors.ErrInvalidTag) {
			t.Fatalf("invalid accepted: %q %v", tag[:min(len(tag), 20)], err)
		}
		data, err := os.ReadFile(path)
		if err != nil || string(data) != "keep\n" {
			t.Fatalf("prior bytes changed: %q %v", data, err)
		}
	}
}

// TestObjectTagStorageParsing checks comments, duplicate lines and malformed input.
func TestObjectTagStorageParsing(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, "tags")
	if err := os.WriteFile(path, []byte(" # comment\n; comment\n// comment\n-- comment\n\n work \nwork\nother\n"), 0600); err != nil {
		t.Fatal(err)
	}
	got, err := readObjectTags(dir)
	if err != nil || !reflect.DeepEqual(got, []string{"work", "other"}) {
		t.Fatalf("parse: %v %v", got, err)
	}
	for _, data := range []string{"bad/tag\n", "inner\tcontrol\n", strings.Repeat("x", maxStoredTagBytes+3)} {
		if err := os.WriteFile(path, []byte(data), 0600); err != nil {
			t.Fatal(err)
		}
		if _, err := readObjectTags(dir); err == nil {
			t.Fatal("malformed tags accepted")
		}
	}
}

// TestObjectTagStorageFailures checks rename cleanup and unavailable directories.
func TestObjectTagStorageFailures(t *testing.T) {
	dir := t.TempDir()
	target := filepath.Join(dir, "tags")
	if err := os.Mkdir(target, 0700); err != nil {
		t.Fatal(err)
	}
	keep := filepath.Join(target, "keep")
	if err := os.WriteFile(keep, []byte("keep"), 0600); err != nil {
		t.Fatal(err)
	}
	if err := writeObjectTags(dir, []string{"new"}); err == nil {
		t.Fatal("rename succeeded over directory")
	}
	entries, err := os.ReadDir(dir)
	if err != nil || len(entries) != 1 {
		t.Fatalf("temporary leak: %v %v", entries, err)
	}
	if data, err := os.ReadFile(keep); err != nil || string(data) != "keep" {
		t.Fatalf("unrelated data: %q %v", data, err)
	}
	if _, err := readObjectTags(dir); err == nil {
		t.Fatal("directory read accepted")
	}
	if err := writeObjectTags(filepath.Join(dir, "missing"), nil); err == nil {
		t.Fatal("missing directory accepted")
	}
	if _, err := readObjectTags(keep); err == nil {
		t.Fatal("invalid parent accepted")
	}
}

// TestObjectTagStorageAliases rejects existing and dangling aliases before I/O.
func TestObjectTagStorageAliases(t *testing.T) {
	for _, exists := range []bool{false, true} {
		dir := t.TempDir()
		target := filepath.Join(t.TempDir(), "target")
		if exists {
			if err := os.WriteFile(target, []byte("sentinel\n"), 0600); err != nil {
				t.Fatal(err)
			}
		}
		path := filepath.Join(dir, "tags")
		if err := os.Symlink(target, path); err != nil {
			t.Fatal(err)
		}
		if _, err := readObjectTags(dir); !errors.Is(err, apperrors.ErrCorruptedMetadata) {
			t.Fatalf("alias read accepted: %v", err)
		}
		if err := writeObjectTags(dir, []string{"new"}); !errors.Is(err, apperrors.ErrCorruptedMetadata) {
			t.Fatalf("alias write accepted: %v", err)
		}
		link, err := os.Readlink(path)
		if err != nil || link != target {
			t.Fatalf("alias changed: %q %v", link, err)
		}
		data, err := os.ReadFile(target)
		if exists && (err != nil || string(data) != "sentinel\n") {
			t.Fatalf("target changed: %q %v", data, err)
		}
		if !exists && !os.IsNotExist(err) {
			t.Fatalf("dangling target created: %v", err)
		}
		entries, err := os.ReadDir(dir)
		if err != nil || len(entries) != 1 {
			t.Fatalf("unexpected files after rejection: %v %v", entries, err)
		}
	}
}
