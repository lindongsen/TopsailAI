// Package local implements the local filesystem adapter for topsailai_data.
package local

import (
	"archive/tar"
	"context"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"strings"

	"github.com/topsailai/topsailai_data/pkg/errors"
)

// metadataMarkerNames lists file and directory names that must be preserved
// during actual-data operations. These names are reserved for object
// lifecycle and metadata management.
var metadataMarkerNames = map[string]bool{
	"metadata.json": true,
}

// metadataMarkerSuffixes lists name suffixes that identify reserved marker
// files. A name matching any suffix is treated as metadata and excluded from
// actual-data read/write/delete operations. Note that ".md" is intentionally
// not reserved: the mandatory object.md file is actual data, not metadata.
var metadataMarkerSuffixes = []string{
	".tags",
	".lock",
	".deleted",
	".ceased",
}

// actualDataAdapter implements pkg/adapters.ActualDataAdapter using the local
// filesystem. The DataRef for this adapter is the absolute path to the object
// directory.
type actualDataAdapter struct {
	root string
}

// NewActualDataAdapter creates a local actual-data adapter rooted at root.
func NewActualDataAdapter(root string) *actualDataAdapter {
	return &actualDataAdapter{root: root}
}

// Init prepares the adapter root directory.
func (a *actualDataAdapter) Init(ctx context.Context) error {
	if ctx.Err() != nil {
		return ctx.Err()
	}
	if err := os.MkdirAll(a.root, 0o755); err != nil {
		return fmt.Errorf("create actual-data root %q: %w", a.root, err)
	}
	return nil
}

// Exists reports whether the object directory contains any actual data files.
// Metadata-only files (metadata.json, lock files, lifecycle markers) are ignored;
// everything else, including the mandatory {name}.md marker, counts as actual data.
func (a *actualDataAdapter) Exists(ctx context.Context, ref string) (bool, error) {
	if ctx.Err() != nil {
		return false, ctx.Err()
	}
	if ref == "" {
		return false, fmt.Errorf("%w: ref is empty", errors.ErrInvalidArgument)
	}
	entries, err := os.ReadDir(ref)
	if err != nil {
		if os.IsNotExist(err) {
			return false, nil
		}
		return false, fmt.Errorf("read object dir %q: %w", ref, err)
	}
	for _, entry := range entries {
		if entry.IsDir() {
			return true, nil
		}
		name := entry.Name()
		if isMetadataMarker(name) {
			continue
		}
		if strings.HasPrefix(name, ".") {
			continue
		}
		return true, nil
	}
	return false, nil
}

// WriteArchive replaces the actual data of an object with the contents of a
// tar archive stream. Existing actual-data files are removed first; metadata
// marker files are preserved. The returned ref is the absolute object path.
func (a *actualDataAdapter) WriteArchive(ctx context.Context, ref string, r io.Reader) (string, error) {
	if ctx.Err() != nil {
		return "", ctx.Err()
	}
	if ref == "" {
		return "", fmt.Errorf("%w: ref is empty", errors.ErrInvalidArgument)
	}
	if err := os.MkdirAll(ref, 0o755); err != nil {
		return "", fmt.Errorf("create object directory %q: %w", ref, err)
	}
	if err := a.clearActualData(ref); err != nil {
		return "", err
	}
	if err := a.untar(ref, r); err != nil {
		return "", err
	}
	return ref, nil
}

// ReadArchive returns a tar archive stream of the object's actual data.
// Metadata marker files are excluded from the archive.
func (a *actualDataAdapter) ReadArchive(ctx context.Context, ref string) (io.ReadCloser, error) {
	if ctx.Err() != nil {
		return nil, ctx.Err()
	}
	if ref == "" {
		return nil, fmt.Errorf("%w: ref is empty", errors.ErrInvalidArgument)
	}
	pr, pw := io.Pipe()
	go func() {
		err := a.tarDir(ref, pw)
		_ = pw.CloseWithError(err)
	}()
	return pr, nil
}

// WriteFile writes a single file into the object's actual data. Parent
// directories are created as needed. The file path must be relative and must
// not traverse outside the object directory. The returned ref is the absolute
// object path.
func (a *actualDataAdapter) WriteFile(ctx context.Context, ref string, filename string, r io.Reader) (string, error) {
	if ctx.Err() != nil {
		return "", ctx.Err()
	}
	if ref == "" {
		return "", fmt.Errorf("%w: ref is empty", errors.ErrInvalidArgument)
	}
	if err := validateActualFilename(filename); err != nil {
		return "", err
	}
	fullPath := filepath.Join(ref, filename)
	if err := os.MkdirAll(filepath.Dir(fullPath), 0o755); err != nil {
		return "", fmt.Errorf("create parent directories for %q: %w", fullPath, err)
	}
	f, err := os.OpenFile(fullPath, os.O_CREATE|os.O_WRONLY|os.O_TRUNC, 0o644)
	if err != nil {
		return "", fmt.Errorf("create file %q: %w", fullPath, err)
	}
	defer f.Close()
	if _, err := io.Copy(f, r); err != nil {
		return "", fmt.Errorf("write file %q: %w", fullPath, err)
	}
	return ref, nil
}

// ReadFile returns a stream that reads a single file from the object's actual
// data.
func (a *actualDataAdapter) ReadFile(ctx context.Context, ref string, filename string) (io.ReadCloser, error) {
	if ctx.Err() != nil {
		return nil, ctx.Err()
	}
	if ref == "" {
		return nil, fmt.Errorf("%w: ref is empty", errors.ErrInvalidArgument)
	}
	if err := validateActualFilename(filename); err != nil {
		return nil, err
	}
	fullPath := filepath.Join(ref, filename)
	f, err := os.Open(fullPath)
	if err != nil {
		if os.IsNotExist(err) {
			return nil, fmt.Errorf("%w: file %q", errors.ErrObjectNotFound, filename)
		}
		return nil, fmt.Errorf("open file %q: %w", fullPath, err)
	}
	return f, nil
}

// Move copies the object directory from oldRef to newRef. For the local adapter
// newRef is the new absolute object directory path. The returned ref is newRef
// on success. The caller is responsible for deleting the old directory and for
// cleaning up any empty parent directories.
func (a *actualDataAdapter) Move(ctx context.Context, oldRef string, newRef string) (string, error) {
	if ctx.Err() != nil {
		return "", ctx.Err()
	}
	if oldRef == "" {
		return "", fmt.Errorf("%w: oldRef is empty", errors.ErrInvalidArgument)
	}
	if newRef == "" {
		return "", fmt.Errorf("%w: newRef is empty", errors.ErrInvalidArgument)
	}
	if _, err := os.Stat(oldRef); err != nil {
		if os.IsNotExist(err) {
			return "", fmt.Errorf("%w: source path %q", errors.ErrObjectNotFound, oldRef)
		}
		return "", fmt.Errorf("stat source path %q: %w", oldRef, err)
	}
	if err := os.MkdirAll(filepath.Dir(newRef), 0o755); err != nil {
		return "", fmt.Errorf("create parent directory for %q: %w", newRef, err)
	}
	if _, err := os.Stat(newRef); err == nil {
		return "", fmt.Errorf("%w: target path %q already exists", errors.ErrObjectExists, newRef)
	} else if !os.IsNotExist(err) {
		return "", fmt.Errorf("stat target path %q: %w", newRef, err)
	}
	if err := copyDir(oldRef, newRef); err != nil {
		return "", fmt.Errorf("copy object directory from %q to %q: %w", oldRef, newRef, err)
	}
	return newRef, nil
}

// copyDir recursively copies src to dst. dst must not already exist.
func copyDir(src, dst string) error {
	srcInfo, err := os.Stat(src)
	if err != nil {
		return fmt.Errorf("stat source %q: %w", src, err)
	}
	if !srcInfo.IsDir() {
		return fmt.Errorf("source %q is not a directory", src)
	}
	if err := os.MkdirAll(dst, srcInfo.Mode().Perm()); err != nil {
		return fmt.Errorf("create destination %q: %w", dst, err)
	}
	entries, err := os.ReadDir(src)
	if err != nil {
		return fmt.Errorf("read source directory %q: %w", src, err)
	}
	for _, entry := range entries {
		srcPath := filepath.Join(src, entry.Name())
		dstPath := filepath.Join(dst, entry.Name())
		info, err := entry.Info()
		if err != nil {
			return fmt.Errorf("get info for %q: %w", srcPath, err)
		}
		if entry.IsDir() {
			if err := copyDir(srcPath, dstPath); err != nil {
				return err
			}
			continue
		}
		if err := copyFile(srcPath, dstPath, info.Mode().Perm()); err != nil {
			return err
		}
	}
	return nil
}

// copyFile copies src to dst, creating parent directories as needed.
func copyFile(src, dst string, perm os.FileMode) error {
	if err := os.MkdirAll(filepath.Dir(dst), 0o755); err != nil {
		return fmt.Errorf("create parent directories for %q: %w", dst, err)
	}
	srcFile, err := os.Open(src)
	if err != nil {
		return fmt.Errorf("open source file %q: %w", src, err)
	}
	defer srcFile.Close()
	dstFile, err := os.OpenFile(dst, os.O_CREATE|os.O_WRONLY|os.O_TRUNC, perm)
	if err != nil {
		return fmt.Errorf("create destination file %q: %w", dst, err)
	}
	if _, err := io.Copy(dstFile, srcFile); err != nil {
		_ = dstFile.Close()
		return fmt.Errorf("copy %q to %q: %w", src, dst, err)
	}
	if err := dstFile.Close(); err != nil {
		return fmt.Errorf("close destination file %q: %w", dst, err)
	}
	return nil
}

// RemoveEmptyParents walks upward from dir and removes each parent directory
// if it is empty, stopping when it reaches root or a non-empty directory.
// The root directory itself is never removed.
func RemoveEmptyParents(dir, root string) error {
	root = filepath.Clean(root)
	current := filepath.Clean(dir)
	for {
		parent := filepath.Dir(current)
		if parent == current || parent == root {
			return nil
		}
		entries, err := os.ReadDir(parent)
		if err != nil {
			if os.IsNotExist(err) {
				current = parent
				continue
			}
			return fmt.Errorf("read directory %q: %w", parent, err)
		}
		if len(entries) > 0 {
			return nil
		}
		if err := os.Remove(parent); err != nil {
			if os.IsNotExist(err) {
				current = parent
				continue
			}
			return fmt.Errorf("remove empty directory %q: %w", parent, err)
		}
		current = parent
	}
}

// Delete removes all actual-data files and directories inside the object
// directory while preserving metadata marker files and the mandatory object
// marker file ({folder-name}.md).
func (a *actualDataAdapter) Delete(ctx context.Context, ref string) error {
	if ctx.Err() != nil {
		return ctx.Err()
	}
	if ref == "" {
		return fmt.Errorf("%w: ref is empty", errors.ErrInvalidArgument)
	}
	return a.clearActualData(ref)
}

// clearActualData removes all entries inside dir that are not metadata markers.
// The mandatory object marker file ({folder-name}.md) in the root directory is
// preserved because the metadata scanner uses it to identify object folders.
func (a *actualDataAdapter) clearActualData(dir string) error {
	entries, err := os.ReadDir(dir)
	if err != nil {
		if os.IsNotExist(err) {
			return nil
		}
		return fmt.Errorf("read directory %q: %w", dir, err)
	}
	markerName := filepath.Base(dir) + ".md"
	for _, entry := range entries {
		if isMetadataMarker(entry.Name()) {
			continue
		}
		if entry.Name() == markerName {
			continue
		}
		fullPath := filepath.Join(dir, entry.Name())
		if err := os.RemoveAll(fullPath); err != nil {
			return fmt.Errorf("remove %q: %w", fullPath, err)
		}
	}
	return nil
}

// Close releases resources held by the adapter. For the local adapter this is
// a no-op.
func (a *actualDataAdapter) Close() error {
	return nil
}

// isMetadataMarker reports whether name is a reserved metadata marker.
func isMetadataMarker(name string) bool {
	if metadataMarkerNames[name] {
		return true
	}
	for _, suffix := range metadataMarkerSuffixes {
		if strings.HasSuffix(name, suffix) {
			return true
		}
	}
	return false
}

// validateActualFilename checks that filename is a safe relative path inside
// an object directory.
func validateActualFilename(filename string) error {
	if filename == "" {
		return fmt.Errorf("%w: empty filename", errors.ErrInvalidArgument)
	}
	if filepath.IsAbs(filename) {
		return fmt.Errorf("%w: filename must be relative", errors.ErrInvalidArgument)
	}
	clean := filepath.ToSlash(filepath.Clean(filename))
	if strings.HasPrefix(clean, "..") || strings.Contains(clean, "../") {
		return fmt.Errorf("%w: filename traverses outside object directory", errors.ErrInvalidPath)
	}
	if isMetadataMarker(filepath.Base(filename)) {
		return fmt.Errorf("%w: filename %q is a reserved metadata marker", errors.ErrInvalidName, filename)
	}
	return nil
}

// tarDir writes a tar archive of dir to w, excluding metadata marker files.
func (a *actualDataAdapter) tarDir(dir string, w io.Writer) error {
	tw := tar.NewWriter(w)
	defer tw.Close()

	return filepath.WalkDir(dir, func(path string, d os.DirEntry, err error) error {
		if err != nil {
			return err
		}
		if path == dir {
			return nil
		}
		if isMetadataMarker(d.Name()) {
			if d.IsDir() {
				return filepath.SkipDir
			}
			return nil
		}

		rel, err := filepath.Rel(dir, path)
		if err != nil {
			return fmt.Errorf("relate path %q to object directory: %w", path, err)
		}
		info, err := d.Info()
		if err != nil {
			return fmt.Errorf("get info for %q: %w", path, err)
		}

		hdr, err := tar.FileInfoHeader(info, "")
		if err != nil {
			return fmt.Errorf("create tar header for %q: %w", path, err)
		}
		hdr.Name = filepath.ToSlash(rel)
		if err := tw.WriteHeader(hdr); err != nil {
			return fmt.Errorf("write tar header for %q: %w", path, err)
		}
		if !d.IsDir() && info.Mode().IsRegular() {
			f, err := os.Open(path)
			if err != nil {
				return fmt.Errorf("open file %q: %w", path, err)
			}
			if _, err := io.Copy(tw, f); err != nil {
				_ = f.Close()
				return fmt.Errorf("copy file %q to tar: %w", path, err)
			}
			if err := f.Close(); err != nil {
				return fmt.Errorf("close file %q: %w", path, err)
			}
		}
		return nil
	})
}

// untar extracts a tar archive stream into dir.
func (a *actualDataAdapter) untar(dir string, r io.Reader) error {
	tr := tar.NewReader(r)
	for {
		hdr, err := tr.Next()
		if err == io.EOF {
			break
		}
		if err != nil {
			return fmt.Errorf("read tar header: %w", err)
		}
		if filepath.IsAbs(hdr.Name) {
			return fmt.Errorf("%w: tar entry %q is absolute", errors.ErrInvalidPath, hdr.Name)
		}
		clean := filepath.ToSlash(filepath.Clean(hdr.Name))
		if strings.HasPrefix(clean, "..") || strings.Contains(clean, "../") {
			return fmt.Errorf("%w: tar entry %q traverses outside object directory", errors.ErrInvalidPath, hdr.Name)
		}
		if isMetadataMarker(filepath.Base(hdr.Name)) {
			continue
		}

		target := filepath.Join(dir, hdr.Name)
		switch hdr.Typeflag {
		case tar.TypeDir:
			if err := os.MkdirAll(target, 0o755); err != nil {
				return fmt.Errorf("create directory %q: %w", target, err)
			}
		case tar.TypeReg:
			if err := os.MkdirAll(filepath.Dir(target), 0o755); err != nil {
				return fmt.Errorf("create parent directories for %q: %w", target, err)
			}
			f, err := os.OpenFile(target, os.O_CREATE|os.O_WRONLY|os.O_TRUNC, os.FileMode(hdr.Mode)&0o777)
			if err != nil {
				return fmt.Errorf("create file %q: %w", target, err)
			}
			if _, err := io.Copy(f, tr); err != nil {
				_ = f.Close()
				return fmt.Errorf("write file %q: %w", target, err)
			}
			if err := f.Close(); err != nil {
				return fmt.Errorf("close file %q: %w", target, err)
			}
		default:
			return fmt.Errorf("unsupported tar entry type %d for %q", hdr.Typeflag, hdr.Name)
		}
	}
	return nil
}
