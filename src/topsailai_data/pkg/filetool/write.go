package filetool

import (
	"os"
	"path/filepath"

	"github.com/pmezard/go-difflib/difflib"
)

// WriteFileOptions controls how content is written.
type WriteFileOptions struct {
	// Seek is the byte offset where writing starts. Negative values count from
	// the end of the existing content. Defaults to 0.
	Seek int64

	// Insert inserts content at Seek instead of overwriting existing bytes.
	Insert bool

	// FS is the file system to write to. A nil value uses the operating
	// system file system.
	FS FS
}

// WriteFile writes content to a file, creating parent folders as needed.
//
// With Seek 0 and Insert false the whole file is replaced. A positive Seek is
// clamped to the existing content length. A negative Seek counts from the end;
// in insert mode the position is one past the counted offset so appending with
// Seek -1 works. In overwrite mode bytes from the position onward are replaced
// and the file is extended when the new content is longer.
func WriteFile(path string, content string, opts WriteFileOptions) error {
	if path == "" {
		return invalidParameter("file_path", path, "must be a non-empty string")
	}

	if opts.Insert {
		return insertAt(path, content, opts.Seek, opts.FS)
	}
	return overwriteAt(path, content, opts.Seek, opts.FS)
}

// insertAt inserts content at the requested position without removing bytes.
func insertAt(path, content string, seek int64, fs FS) error {
	existing, exists, err := readExisting(path, fs)
	if err != nil {
		return err
	}
	if !exists {
		return writeText(path, content, fs)
	}
	if seek == -1 {
		return appendText(path, content, fs)
	}

	position := resolvePosition(seek, len(existing), true)
	updated := existing[:position] + content + existing[position:]
	return writeText(path, updated, fs)
}

// overwriteAt replaces bytes starting at the requested position.
func overwriteAt(path, content string, seek int64, fs FS) error {
	if seek == 0 {
		return writeText(path, content, fs)
	}

	existing, exists, err := readExisting(path, fs)
	if err != nil {
		return err
	}
	if !exists {
		return writeText(path, content, fs)
	}

	position := resolvePosition(seek, len(existing), false)
	if position+len(content) <= len(existing) {
		updated := existing[:position] + content + existing[position+len(content):]
		return writeText(path, updated, fs)
	}
	return writeText(path, existing[:position]+content, fs)
}

// resolvePosition converts a seek value into a byte position within content.
//
// A negative seek counts from the end. Insert mode adds one so Seek -1 appends
// after the last byte; overwrite mode does not. The result is clamped to the
// content length.
func resolvePosition(seek int64, length int, insert bool) int {
	if seek < 0 {
		position := length + int(seek)
		if insert {
			position++
		}
		if position < 0 {
			return 0
		}
		if position > length {
			return length
		}
		return position
	}
	if seek > int64(length) {
		return length
	}
	return int(seek)
}

// readExisting returns the current file content and whether the file exists.
func readExisting(path string, fs FS) (string, bool, error) {
	data, err := resolveFS(fs).ReadFile(path)
	if err != nil {
		if os.IsNotExist(err) {
			return "", false, nil
		}
		return "", false, err
	}
	return string(data), true, nil
}

// writeText writes content to a file, creating parent folders as needed.
func writeText(path, content string, fs FS) error {
	target := resolveFS(fs)
	if dir := filepath.Dir(path); dir != "" && dir != "." {
		if err := target.MkdirAll(dir, 0o755); err != nil {
			return err
		}
	}
	return target.WriteFile(path, []byte(content), 0o644)
}

// AppendFile appends content to a file, creating parent folders as needed.
func AppendFile(path, content string) error {
	return AppendFileWithFS(path, content, nil)
}

// AppendFileWithFS appends content to a file through the given file system.
//
// A nil file system uses the operating system file system.
func AppendFileWithFS(path, content string, fs FS) error {
	if path == "" {
		return invalidParameter("file_path", path, "must be a non-empty string")
	}
	return appendText(path, content, fs)
}

// appendText appends content to a file, creating parent folders as needed.
func appendText(path, content string, fs FS) error {
	target := resolveFS(fs)
	if dir := filepath.Dir(path); dir != "" && dir != "." {
		if err := target.MkdirAll(dir, 0o755); err != nil {
			return err
		}
	}
	return target.AppendFile(path, []byte(content), 0o644)
}

// unifiedDiff renders a unified diff between two texts.
//
// The diff is produced from in-memory snapshots so the caller can compare the
// previous content with the new content without temporary files.
func unifiedDiff(before, after, fromName, toName string) string {
	diff := difflib.UnifiedDiff{
		A:        difflib.SplitLines(before),
		B:        difflib.SplitLines(after),
		FromFile: fromName,
		ToFile:   toName,
		Context:  3,
	}
	text, err := difflib.GetUnifiedDiffString(diff)
	if err != nil {
		return "\n---\nNothing Changed"
	}
	if text == "" {
		return "\n---\nNothing Changed"
	}
	return text
}
