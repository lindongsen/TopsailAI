package filetool

import (
	"bufio"
	"fmt"
	"io"
	"regexp"
	"strconv"
	"strings"
)

const diffContextLines = 3

// editLine records one byte-preserving line and its source range.
type editLine struct {
	num   int
	start int64
	end   int64
	text  []byte
}

// scanEditLines scans byte-preserving lines with bounded reusable buffers.
func scanEditLines(r io.Reader, visit func(editLine) error) (int, int64, error) {
	reader := bufio.NewReaderSize(r, 64*1024)
	line := make([]byte, 0, 64*1024)
	chunk := make([]byte, 64*1024)
	lineNum := 1
	var lineStart int64
	var offset int64
	pendingCR := false
	emit := func() error {
		if err := visit(editLine{num: lineNum, start: lineStart, end: offset, text: line}); err != nil {
			return err
		}
		lineNum++
		lineStart = offset
		line = line[:0]
		return nil
	}
	for {
		n, err := reader.Read(chunk)
		for _, b := range chunk[:n] {
			if pendingCR {
				if b == '\n' {
					line = append(line, b)
					offset++
					pendingCR = false
					if emitErr := emit(); emitErr != nil {
						return 0, 0, emitErr
					}
					continue
				}
				pendingCR = false
				if emitErr := emit(); emitErr != nil {
					return 0, 0, emitErr
				}
			}
			line = append(line, b)
			offset++
			switch b {
			case '\r':
				pendingCR = true
			case '\n':
				if emitErr := emit(); emitErr != nil {
					return 0, 0, emitErr
				}
			}
		}
		if err != nil {
			if err != io.EOF {
				return 0, 0, err
			}
			break
		}
	}
	if pendingCR {
		if err := emit(); err != nil {
			return 0, 0, err
		}
	} else if len(line) > 0 {
		if err := emit(); err != nil {
			return 0, 0, err
		}
	}
	return lineNum - 1, offset, nil
}

// copyEditLine detaches a retained line from the scanner's reusable buffer.
func copyEditLine(line editLine) editLine {
	line.text = append([]byte(nil), line.text...)
	return line
}

// pushContext retains only the newest diff context lines.
func pushContext(ring []editLine, line editLine) []editLine {
	if len(ring) < diffContextLines {
		return append(ring, copyEditLine(line))
	}
	reuse := ring[0].text[:0]
	copy(ring, ring[1:])
	line.text = append(reuse, line.text...)
	ring[len(ring)-1] = line
	return ring
}

// joinEditLines reconstructs a byte-preserving context window.
func joinEditLines(lines []editLine) string {
	var out strings.Builder
	for _, line := range lines {
		out.Write(line.text)
	}
	return out.String()
}

// textLines converts replacement text into numbered diff lines.
func textLines(text string, startNum int) []editLine {
	parts := splitLinesKeepEnds(text)
	lines := make([]editLine, 0, len(parts))
	for i, part := range parts {
		lines = append(lines, editLine{num: startNum + i, text: []byte(part)})
	}
	return lines
}

var unifiedHeaderPattern = regexp.MustCompile(`^@@ -(\d+)(,\d+)? \+(\d+)(,\d+)? @@`)

// boundedUnifiedDiff builds a diff for one window and restores file line numbers.
func boundedUnifiedDiff(before, after, fromName, toName string, lineOffset int) string {
	text := unifiedDiff(before, after, fromName, toName)
	if lineOffset == 0 || strings.Contains(text, "Nothing Changed") {
		return text
	}
	rows := strings.SplitAfter(text, "\n")
	for i, row := range rows {
		match := unifiedHeaderPattern.FindStringSubmatch(row)
		if match == nil {
			continue
		}
		oldStart, _ := strconv.Atoi(match[1])
		newStart, _ := strconv.Atoi(match[3])
		header := fmt.Sprintf("@@ -%d%s +%d%s @@", oldStart+lineOffset, match[2], newStart+lineOffset, match[4])
		rows[i] = unifiedHeaderPattern.ReplaceAllString(row, header)
	}
	return strings.Join(rows, "")
}

// normalizeOverwriteContent preserves the original surrounding line-ending style.
func normalizeOverwriteContent(content string, selected []editLine, following []editLine) []byte {
	newLines := splitLinesKeepEnds(content)
	if len(newLines) == 0 || hasLineEnding(newLines[len(newLines)-1]) {
		return []byte(content)
	}
	ending := ""
	if len(following) > 0 {
		ending = lineEndingOf(string(following[0].text))
		if ending == "" {
			ending = "\n"
		}
	} else if len(selected) > 0 {
		ending = lineEndingOf(string(selected[len(selected)-1].text))
	}
	return append([]byte(content), ending...)
}

// planOverwriteLines scans one file and returns a bounded range edit and diff.
func planOverwriteLines(current io.Reader, path string, opts OverwriteLinesOptions) (FileEdit, string, error) {
	if opts.EndNum > 0 && opts.StartNum > opts.EndNum {
		return FileEdit{}, "", fmt.Errorf("%w: start_num (%d) > end_num (%d)", ErrInvalidRange, opts.StartNum, opts.EndNum)
	}
	var previous, selected, following []editLine
	endNum := opts.EndNum
	if endNum == 0 {
		endNum = opts.StartNum
	}
	lineCount, _, err := scanEditLines(current, func(line editLine) error {
		switch {
		case line.num < opts.StartNum:
			previous = pushContext(previous, line)
		case endNum == -1 || line.num <= endNum:
			selected = append(selected, copyEditLine(line))
		case len(following) < diffContextLines:
			following = append(following, copyEditLine(line))
		}
		return nil
	})
	if err != nil {
		return FileEdit{}, "", err
	}
	if len(selected) == 0 {
		return FileEdit{}, "", fmt.Errorf("%w: start_num (%d) exceeds file length (%d lines)", ErrInvalidRange, opts.StartNum, lineCount)
	}
	replacement := normalizeOverwriteContent(opts.Content, selected, following)
	beforeLines := append(append(append([]editLine{}, previous...), selected...), following...)
	afterLines := append(append(append([]editLine{}, previous...), textLines(string(replacement), opts.StartNum)...), following...)
	base := opts.StartNum
	if len(previous) > 0 {
		base = previous[0].num
	}
	diff := boundedUnifiedDiff(joinEditLines(beforeLines), joinEditLines(afterLines), "before", path, base-1)
	return FileEdit{Start: selected[0].start, End: selected[len(selected)-1].end, Replacement: replacement}, diff, nil
}

// planInsertContent scans one file and returns a bounded insertion and diff.
func planInsertContent(current io.Reader, path string, opts InsertContentOptions) (FileEdit, string, bool, error) {
	content := opts.Content
	if content != "" && !hasLineEnding(content) {
		content += "\n"
	}
	desired := opts.LineNum - 1
	if !opts.Before {
		desired++
	}
	var previous, following []editLine
	triggered := false
	var position int64
	lineCount, fileSize, err := scanEditLines(current, func(line editLine) error {
		if !triggered && line.num-1 == desired {
			triggered = true
			position = line.start
			following = append(following, copyEditLine(line))
			return nil
		}
		if triggered {
			if len(following) < diffContextLines {
				following = append(following, copyEditLine(line))
			}
			return nil
		}
		previous = pushContext(previous, line)
		return nil
	})
	if err != nil {
		return FileEdit{}, "", false, err
	}
	if !triggered {
		position = fileSize
	}
	if lineCount == 0 {
		return FileEdit{Start: 0, End: 0, Replacement: []byte(content)}, "", true, nil
	}
	beforeLines := append(append([]editLine{}, previous...), following...)
	afterLines := append(append(append([]editLine{}, previous...), textLines(content, desired+1)...), following...)
	base := 1
	if len(previous) > 0 {
		base = previous[0].num
	} else if len(following) > 0 {
		base = following[0].num
	}
	diff := boundedUnifiedDiff(joinEditLines(beforeLines), joinEditLines(afterLines), "before", path, base-1)
	return FileEdit{Start: position, End: position, Replacement: []byte(content)}, diff, false, nil
}
