package filetool

import (
	"fmt"
	"os"
	"strings"
)

// OverwriteWarning is prepended to every line-range edit result so a caller
// knows the line numbers of the file have changed.
const OverwriteWarning = "> You CANNOT call continuously due to the line number will change after each call.\n" +
	"> Invoke the tool that provides line numbers to check content Now!\n"

// OverwriteLinesOptions controls a line-range replacement.
type OverwriteLinesOptions struct {
	// StartNum is the 1-based first line to replace. It is always replaced.
	StartNum int

	// EndNum is the 1-based inclusive last line to replace. 0 replaces only
	// StartNum; -1 replaces through the end of the file. Other negative values
	// are rejected.
	EndNum int

	// Content replaces the selected lines. An empty value deletes them.
	Content string
}

// OverwriteLines replaces a line range with new content and returns a unified
// diff of the change.
//
// Line endings of the surrounding file are preserved: when the new content does
// not end with a line ending, the terminator of the following original line is
// reused, or the terminator of the last replaced line when the range reaches the
// end of the file.
func OverwriteLines(path string, opts OverwriteLinesOptions) (string, error) {
	if path == "" {
		return "", invalidParameter("file_path", path, "must be a non-empty string")
	}
	if opts.EndNum < -1 {
		return "", invalidParameter("end_num", opts.EndNum, "must be -1, 0, or a positive line number")
	}
	if opts.StartNum < 1 {
		return "", invalidParameter("start_num", opts.StartNum, "must be >= 1")
	}

	original, err := os.ReadFile(path)
	if err != nil {
		return "", err
	}
	before := string(original)
	lines := splitLinesKeepEnds(before)

	startIdx := opts.StartNum - 1
	if startIdx >= len(lines) {
		return "", fmt.Errorf("%w: start_num (%d) exceeds file length (%d lines)", ErrInvalidRange, opts.StartNum, len(lines))
	}

	var endIdx int
	switch {
	case opts.EndNum == 0:
		endIdx = opts.StartNum
	case opts.EndNum == -1:
		endIdx = len(lines)
	default:
		endIdx = opts.EndNum
	}
	if endIdx > len(lines) {
		endIdx = len(lines)
	}
	if startIdx >= endIdx {
		return "", fmt.Errorf("%w: start_num (%d) > end_num (%d)", ErrInvalidRange, opts.StartNum, opts.EndNum)
	}

	newLines := splitLinesKeepEnds(opts.Content)
	if len(newLines) > 0 && !hasLineEnding(newLines[len(newLines)-1]) {
		newLines[len(newLines)-1] += trailingLineEnding(lines, endIdx)
	}

	updated := strings.Join(lines[:startIdx], "") + strings.Join(newLines, "") + strings.Join(lines[endIdx:], "")
	if err := writeText(path, updated); err != nil {
		return "", err
	}

	return OverwriteWarning + unifiedDiff(before, updated, "before", path), nil
}

// InsertContentOptions controls an insertion relative to a line number.
type InsertContentOptions struct {
	// LineNum is the 1-based reference line.
	LineNum int

	// Before inserts before the reference line; any other value inserts after.
	Before bool

	// Content is inserted. A trailing newline is added when missing.
	Content string
}

// InsertContent inserts content before or after a line and returns a unified
// diff of the change.
//
// The insertion index is clamped to the valid range, so inserting after the last
// line appends and inserting before the first line prepends. An empty file
// yields an empty diff because there is nothing to compare against.
func InsertContent(path string, opts InsertContentOptions) (string, error) {
	if path == "" {
		return "", invalidParameter("file_path", path, "must be a non-empty string")
	}
	if opts.LineNum < 1 {
		return "", invalidParameter("line_num", opts.LineNum, "must be >= 1")
	}

	original, err := os.ReadFile(path)
	if err != nil {
		return "", err
	}
	before := string(original)
	lines := splitLinesKeepEnds(before)

	content := opts.Content
	if content != "" && !hasLineEnding(content) {
		content += "\n"
	}

	insertIndex := opts.LineNum - 1
	if !opts.Before {
		insertIndex++
	}
	if insertIndex < 0 {
		insertIndex = 0
	}
	if insertIndex > len(lines) {
		insertIndex = len(lines)
	}

	updated := strings.Join(lines[:insertIndex], "") + content + strings.Join(lines[insertIndex:], "")
	if err := writeText(path, updated); err != nil {
		return "", err
	}

	if before == "" {
		return "", nil
	}
	return unifiedDiff(before, updated, "before", path), nil
}

// splitLinesKeepEnds splits text into lines while keeping each line terminator.
//
// A trailing fragment without a terminator becomes its own line, matching the
// behaviour of splitting a file that does not end with a newline.
func splitLinesKeepEnds(text string) []string {
	if text == "" {
		return nil
	}

	var lines []string
	start := 0
	for i := 0; i < len(text); i++ {
		switch text[i] {
		case '\n':
			lines = append(lines, text[start:i+1])
			start = i + 1
		case '\r':
			if i+1 < len(text) && text[i+1] == '\n' {
				lines = append(lines, text[start:i+2])
				i++
			} else {
				lines = append(lines, text[start:i+1])
			}
			start = i + 1
		}
	}
	if start < len(text) {
		lines = append(lines, text[start:])
	}
	return lines
}

// hasLineEnding reports whether text ends with a line terminator.
func hasLineEnding(text string) bool {
	return strings.HasSuffix(text, "\n") || strings.HasSuffix(text, "\r")
}

// trailingLineEnding returns the terminator to append to new content.
//
// The terminator of the first line after the replaced range is preferred so the
// file keeps a consistent style. When the range reaches the end of the file the
// terminator of the last replaced line is reused; a file without any terminator
// falls back to "\n" so blocks stay separated.
func trailingLineEnding(lines []string, endIdx int) string {
	if endIdx < len(lines) {
		if ending := lineEndingOf(lines[endIdx]); ending != "" {
			return ending
		}
		return "\n"
	}
	if endIdx > 0 && endIdx-1 < len(lines) {
		if ending := lineEndingOf(lines[endIdx-1]); ending != "" {
			return ending
		}
	}
	return ""
}

// lineEndingOf returns the trailing line terminator of one line.
func lineEndingOf(line string) string {
	if strings.HasSuffix(line, "\r\n") {
		return "\r\n"
	}
	if strings.HasSuffix(line, "\n") {
		return "\n"
	}
	if strings.HasSuffix(line, "\r") {
		return "\r"
	}
	return ""
}
