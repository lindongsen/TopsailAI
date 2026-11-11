package local

import (
	"bufio"
	"fmt"
	"log/slog"
	"os"
	"path/filepath"
	"strings"
	"unicode"
	"unicode/utf8"

	apperrors "github.com/topsailai/topsailai_data/pkg/errors"
)

const maxStoredTagBytes = 64 * 1024

// validateStoredTag rejects values that cannot round-trip through the line format.
func validateStoredTag(tag string) error {
	if err := ValidateTag(tag); err != nil {
		return err
	}
	if len(tag) > maxStoredTagBytes || !utf8.ValidString(tag) || strings.TrimSpace(tag) != tag {
		return fmt.Errorf("tag length, encoding or whitespace: %w", apperrors.ErrInvalidTag)
	}
	for _, prefix := range []string{"#", ";", "//", "--"} {
		if strings.HasPrefix(tag, prefix) {
			return fmt.Errorf("comment-prefix tag: %w", apperrors.ErrInvalidTag)
		}
	}
	for _, r := range tag {
		if unicode.IsControl(r) {
			return fmt.Errorf("control character in tag: %w", apperrors.ErrInvalidTag)
		}
	}
	return nil
}

// readObjectTags reads only this object's metadata tags, without inheritance.
func readObjectTags(metaDir string) ([]string, error) {
	path := filepath.Join(metaDir, "tags")
	f, err := os.Open(path)
	if os.IsNotExist(err) {
		return []string{}, nil
	}
	if err != nil {
		return nil, fmt.Errorf("open object tags %q: %w", path, err)
	}
	defer f.Close()
	scanner := bufio.NewScanner(f)
	scanner.Buffer(make([]byte, 4096), maxStoredTagBytes+2)
	tags := []string{}
	for line := 1; scanner.Scan(); line++ {
		tag := strings.TrimSpace(scanner.Text())
		if tag == "" || strings.HasPrefix(tag, "#") || strings.HasPrefix(tag, ";") || strings.HasPrefix(tag, "//") || strings.HasPrefix(tag, "--") {
			continue
		}
		if err := validateStoredTag(tag); err != nil {
			return nil, fmt.Errorf("object tags %q line %d: %w", path, line, err)
		}
		tags = append(tags, tag)
	}
	if err := scanner.Err(); err != nil {
		return nil, fmt.Errorf("read object tags %q: %w", path, err)
	}
	return MergeTags(nil, tags), nil
}

// writeObjectTags replaces validated tags atomically; callers hold the object lock.
// The metadata directory must already exist. Empty sets retain an empty tags file.
func writeObjectTags(metaDir string, tags []string) error {
	for _, tag := range tags {
		if err := validateStoredTag(tag); err != nil {
			return fmt.Errorf("write object tags in %q: %w", metaDir, err)
		}
	}
	content := strings.Join(MergeTags(nil, tags), "\n")
	if content != "" {
		content += "\n"
	}
	f, err := os.CreateTemp(metaDir, ".tags-*.tmp")
	if err != nil {
		return fmt.Errorf("create temporary tags in %q: %w", metaDir, err)
	}
	defer func() {
		_ = f.Close()
		if err := os.Remove(f.Name()); err == nil {
			slog.Info("removed temporary tags", "path", f.Name())
		} else if !os.IsNotExist(err) {
			slog.Error("remove temporary tags", "path", f.Name(), "error", err)
		}
	}()
	if _, err := f.WriteString(content); err != nil {
		return fmt.Errorf("write temporary tags: %w", err)
	}
	if err := f.Sync(); err != nil {
		return fmt.Errorf("sync temporary tags: %w", err)
	}
	if err := f.Close(); err != nil {
		return fmt.Errorf("close temporary tags: %w", err)
	}
	if err := os.Rename(f.Name(), filepath.Join(metaDir, "tags")); err != nil {
		return fmt.Errorf("replace object tags: %w", err)
	}
	return nil
}
