package filetool

import (
	"fmt"
	"io"
	"os"
)

// readBlockSize is the block size used when reading content that may need
// truncation. Reading in blocks avoids loading a huge file into memory when the
// caller only needs the leading part.
const readBlockSize = 1024

// ReadFileOptions controls a single-file read.
type ReadFileOptions struct {
	// Seek is the byte offset to start reading from. Negative values count from
	// the end of the file. Defaults to 0.
	Seek int64

	// Size is the maximum number of bytes to read. -1 reads to the end of the
	// file. Defaults to -1.
	Size int64

	// Options carries the truncation behaviour.
	Options
}

// ReadFile returns the text content of a file.
//
// The file is opened in binary mode and the requested byte window is read. When
// the file extension is not whitelisted, the content is read in blocks and
// truncated at the message limit with TruncateSuffix appended. Bytes are decoded
// with encoding detection and a UTF-8 replacement fallback.
func ReadFile(path string, opts ReadFileOptions) (string, error) {
	if path == "" {
		return "", invalidParameter("file_path", path, "must be a non-empty string")
	}
	if opts.Size < -1 {
		return "", invalidParameter("size", opts.Size, "must be -1 or a non-negative byte count")
	}

	fd, err := os.Open(path)
	if err != nil {
		return "", err
	}
	defer fd.Close()

	if opts.Seek < 0 {
		if _, err := fd.Seek(opts.Seek, io.SeekEnd); err != nil {
			return "", err
		}
	} else if _, err := fd.Seek(opts.Seek, io.SeekStart); err != nil {
		return "", err
	}

	needTruncate := opts.NeedsTruncate(extensionOf(path))
	data, err := readWindow(fd, opts.Size, needTruncate, opts.limit())
	if err != nil {
		return "", err
	}

	content := decodeBytes(data)
	if needTruncate {
		content = truncateContent(content, opts.limit())
	}
	return content, nil
}

// readWindow reads up to size bytes from fd. When truncate is true the read
// stops once the limit is reached, so an oversized file is never fully loaded.
func readWindow(fd io.Reader, size int64, truncate bool, limit int) ([]byte, error) {
	if size >= 0 && size <= readBlockSize {
		return readExactly(fd, size)
	}

	var out []byte
	for {
		block := make([]byte, readBlockSize)
		n, err := fd.Read(block)
		if n > 0 {
			out = append(out, block[:n]...)
		}
		if err != nil {
			if err == io.EOF {
				break
			}
			return nil, err
		}
		if n == 0 {
			break
		}

		if size > 0 && int64(len(out)) >= size {
			break
		}
		if truncate && len(out) >= limit {
			break
		}
	}

	if size >= 0 && int64(len(out)) > size {
		out = out[:size]
	}
	return out, nil
}

// readExactly reads exactly size bytes, returning fewer only at end of file.
func readExactly(fd io.Reader, size int64) ([]byte, error) {
	if size <= 0 {
		return nil, nil
	}
	buf := make([]byte, size)
	n, err := io.ReadFull(fd, buf)
	if err != nil && err != io.EOF && err != io.ErrUnexpectedEOF {
		return nil, err
	}
	return buf[:n], nil
}

// truncateContent cuts content at the byte limit and appends TruncateSuffix when
// the content is longer than the limit.
func truncateContent(content string, limit int) string {
	if len(content) <= limit {
		return content
	}
	return content[:limit] + TruncateSuffix
}

// ReadFiles reads several files and returns a path-to-content map.
//
// Every file is read with the default read options. A read failure is recorded
// as the map value so one unreadable file does not hide the others.
func ReadFiles(paths []string, opts ReadFileOptions) (map[string]string, error) {
	if len(paths) == 0 {
		return nil, invalidParameter("files", paths, "must be a non-empty list")
	}
	result := make(map[string]string, len(paths))
	for _, path := range paths {
		content, err := ReadFile(path, opts)
		if err != nil {
			result[path] = fmt.Sprintf("Error: %v", err)
			continue
		}
		result[path] = content
	}
	return result, nil
}
