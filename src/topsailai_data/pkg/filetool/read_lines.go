package filetool

import (
	"bufio"
	"fmt"
	"io"
	"os"
	"regexp"
	"sort"
	"strings"

	"golang.org/x/text/transform"
)

// maxLineBytes bounds a single scanned line so a pathological file cannot
// exhaust memory. Lines longer than this are reported as a read error.
const maxLineBytes = 16 * 1024 * 1024

// lineReader streams decoded lines from a file.
type lineReader struct {
	fd     *os.File
	reader *bufio.Scanner
}

// openLineReader opens a file and prepares a streaming line reader.
//
// A bounded byte sample is used to detect the encoding, then the whole stream is
// decoded incrementally so a large file is never fully loaded.
func openLineReader(path string) (*lineReader, error) {
	fd, err := os.Open(path)
	if err != nil {
		return nil, err
	}

	sample := make([]byte, encodingSampleSize)
	n, err := fd.Read(sample)
	if err != nil && err != io.EOF {
		fd.Close()
		return nil, err
	}
	sample = sample[:n]

	if _, err := fd.Seek(0, io.SeekStart); err != nil {
		fd.Close()
		return nil, err
	}

	var source io.Reader = fd
	if enc := lookupEncoding(detectEncoding(sample)); enc != nil {
		source = transform.NewReader(fd, enc.NewDecoder())
	}

	scanner := bufio.NewScanner(source)
	scanner.Buffer(make([]byte, 0, 64*1024), maxLineBytes)
	return &lineReader{fd: fd, reader: scanner}, nil
}

// next returns the next line without its line ending.
func (r *lineReader) next() (string, bool, error) {
	if !r.reader.Scan() {
		if err := r.reader.Err(); err != nil {
			return "", false, err
		}
		return "", false, nil
	}
	return strings.TrimSuffix(r.reader.Text(), "\r"), true, nil
}

// Close releases the underlying file.
func (r *lineReader) Close() error { return r.fd.Close() }

// ReadFileLinesOptions controls a line-range read.
type ReadFileLinesOptions struct {
	// StartNum is the 1-based first line to read. Values <= 0 fall back to 1.
	StartNum int

	// EndNum is the 1-based inclusive last line to read. 0 means only StartNum
	// is read; -1 means through the end of the file. Other negative values are
	// rejected.
	EndNum int
}

// ReadFileLines returns the requested lines formatted as "{n}-{content}".
//
// An empty file, or a start line past the end of the file, yields an empty
// string. A start line greater than a positive end line is an invalid range.
func ReadFileLines(path string, opts ReadFileLinesOptions) (string, error) {
	if path == "" {
		return "", invalidParameter("file_path", path, "must be a non-empty string")
	}
	if opts.EndNum < -1 {
		return "", invalidParameter("end_num", opts.EndNum, "must be -1, 0, or a positive line number")
	}

	startNum := opts.StartNum
	if startNum <= 0 {
		startNum = 1
	}
	endNum := opts.EndNum
	if endNum == 0 {
		endNum = startNum
	}
	if endNum > 0 && startNum > endNum {
		return "", fmt.Errorf("%w: start_num (%d) > end_num (%d)", ErrInvalidRange, startNum, endNum)
	}

	reader, err := openLineReader(path)
	if err != nil {
		return "", err
	}
	defer reader.Close()

	var output []string
	lineNum := 0
	for {
		line, ok, err := reader.next()
		if err != nil {
			return "", err
		}
		if !ok {
			break
		}
		lineNum++
		if endNum > 0 && lineNum > endNum {
			break
		}
		if lineNum >= startNum {
			output = append(output, fmt.Sprintf("%d-%s", lineNum, line))
		}
	}

	if lineNum == 0 || startNum > lineNum {
		return "", nil
	}
	return strings.Join(output, "\n"), nil
}

// ReadFileAroundLineOptions controls a context read around one line.
type ReadFileAroundLineOptions struct {
	// LineNumber is the 1-based target line.
	LineNumber int

	// ContextNum is the number of lines shown before and after the target.
	// Values <= 0 show only the target line.
	ContextNum int
}

// ReadFileAroundLine returns the target line and its surrounding context.
//
// The target line is marked with ":" and context lines with "-", formatted as
// "{n}{marker}{content}". A target outside the file yields an out-of-range
// error; an empty file yields an empty string.
func ReadFileAroundLine(path string, opts ReadFileAroundLineOptions) (string, error) {
	if path == "" {
		return "", invalidParameter("file_path", path, "must be a non-empty string")
	}
	if opts.LineNumber <= 0 {
		return "", invalidParameter("line_number", opts.LineNumber, "must be a positive line number")
	}

	targetIdx := opts.LineNumber - 1
	contextNum := opts.ContextNum
	if contextNum < 0 {
		contextNum = 0
	}

	reader, err := openLineReader(path)
	if err != nil {
		return "", err
	}
	defer reader.Close()

	var output []string
	totalLines := 0
	startIdx := targetIdx - contextNum
	if startIdx < 0 {
		startIdx = 0
	}
	endIdx := targetIdx + contextNum

	for {
		line, ok, err := reader.next()
		if err != nil {
			return "", err
		}
		if !ok {
			break
		}
		idx := totalLines
		totalLines++
		if idx > endIdx {
			break
		}
		if idx < startIdx {
			continue
		}
		marker := "-"
		if idx == targetIdx {
			marker = ":"
		}
		output = append(output, fmt.Sprintf("%d%s%s", idx+1, marker, line))
	}

	if totalLines == 0 {
		return "", nil
	}
	if targetIdx < 0 || targetIdx >= totalLines {
		return "", fmt.Errorf("%w: line number %d is out of range (file has %d lines)", ErrInvalidRange, opts.LineNumber, totalLines)
	}
	return strings.Join(output, "\n"), nil
}

// ReadFileWithContextOptions controls a pattern search with context.
type ReadFileWithContextOptions struct {
	// Pattern is a regular expression matched against each line.
	Pattern string

	// ContextNum is the number of lines shown before and after each match.
	// Values <= 0 show only matching lines.
	ContextNum int

	// CaseSensitive enables case-sensitive matching when true.
	CaseSensitive bool
}

// ReadFileWithContext returns lines matching a regular expression with context.
//
// Matching lines are marked with ":" and context lines with "-". Context lines
// are deduplicated when matches are close together and output is ordered by line
// number. No match yields an empty string.
func ReadFileWithContext(path string, opts ReadFileWithContextOptions) (string, error) {
	if path == "" {
		return "", invalidParameter("file_path", path, "must be a non-empty string")
	}

	expression := opts.Pattern
	if !opts.CaseSensitive {
		expression = "(?i)" + expression
	}
	regex, err := regexp.Compile(expression)
	if err != nil {
		return "", invalidParameter("pattern", opts.Pattern, fmt.Sprintf("invalid regular expression: %v", err))
	}

	contextNum := opts.ContextNum
	if contextNum < 0 {
		contextNum = 0
	}

	reader, err := openLineReader(path)
	if err != nil {
		return "", err
	}
	defer reader.Close()

	matches := make(map[int]string)
	var window []int
	windowLines := make(map[int]string)
	postRemaining := 0
	lineNum := 0

	for {
		line, ok, err := reader.next()
		if err != nil {
			return "", err
		}
		if !ok {
			break
		}
		lineNum++

		if regex.MatchString(line) {
			for _, ln := range window {
				matches[ln] = fmt.Sprintf("%d-%s", ln, windowLines[ln])
			}
			matches[lineNum] = fmt.Sprintf("%d:%s", lineNum, line)
			postRemaining = contextNum
			window = window[:0]
			windowLines = make(map[int]string)
			continue
		}

		if postRemaining > 0 {
			matches[lineNum] = fmt.Sprintf("%d-%s", lineNum, line)
			postRemaining--
		}

		if contextNum > 0 {
			window = append(window, lineNum)
			windowLines[lineNum] = line
			if len(window) > contextNum {
				delete(windowLines, window[0])
				window = window[1:]
			}
		}
	}

	if len(matches) == 0 {
		return "", nil
	}

	numbers := make([]int, 0, len(matches))
	for number := range matches {
		numbers = append(numbers, number)
	}
	sort.Ints(numbers)

	output := make([]string, 0, len(numbers))
	for _, number := range numbers {
		output = append(output, matches[number])
	}
	return strings.Join(output, "\n"), nil
}
