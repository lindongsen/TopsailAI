package filetool

import (
	"fmt"
	"os"
	"path/filepath"
	"runtime"
	"strings"
	"testing"
)

func editAllocatedBytes() uint64 {
	var stats runtime.MemStats
	runtime.ReadMemStats(&stats)
	return stats.TotalAlloc
}

func numberedLines(count int) string {
	var text strings.Builder
	for i := 1; i <= count; i++ {
		fmt.Fprintf(&text, "line-%02d\n", i)
	}
	return text.String()
}

func TestOverwriteLinesBoundedDiffMatchesWholeFileDiff(t *testing.T) {
	for _, tc := range []struct {
		name    string
		start   int
		end     int
		content string
	}{
		{name: "start", start: 1, end: 2, content: "START-A\nSTART-B\n"},
		{name: "middle", start: 10, end: 11, content: "MIDDLE-A\nMIDDLE-B\n"},
		{name: "end", start: 19, end: 20, content: "END-A\nEND-B\n"},
	} {
		t.Run(tc.name, func(t *testing.T) {
			before := numberedLines(20)
			path := writeFixture(t, "sample.txt", before)
			got, err := OverwriteLines(path, OverwriteLinesOptions{StartNum: tc.start, EndNum: tc.end, Content: tc.content})
			if err != nil {
				t.Fatal(err)
			}
			afterBytes, err := os.ReadFile(path)
			if err != nil {
				t.Fatal(err)
			}
			want := OverwriteWarning + unifiedDiff(before, string(afterBytes), "before", path)
			if got != want {
				t.Fatalf("diff mismatch\n--- got ---\n%s\n--- want ---\n%s", got, want)
			}
		})
	}
}

func TestInsertContentBoundedDiffMatchesWholeFileDiff(t *testing.T) {
	for _, tc := range []struct {
		name   string
		line   int
		before bool
	}{
		{name: "start", line: 1, before: true},
		{name: "middle", line: 10, before: false},
		{name: "end", line: 20, before: false},
	} {
		t.Run(tc.name, func(t *testing.T) {
			before := numberedLines(20)
			path := writeFixture(t, "sample.txt", before)
			got, err := InsertContent(path, InsertContentOptions{LineNum: tc.line, Before: tc.before, Content: "inserted"})
			if err != nil {
				t.Fatal(err)
			}
			afterBytes, err := os.ReadFile(path)
			if err != nil {
				t.Fatal(err)
			}
			want := unifiedDiff(before, string(afterBytes), "before", path)
			if got != want {
				t.Fatalf("diff mismatch\n--- got ---\n%s\n--- want ---\n%s", got, want)
			}
		})
	}
}

func TestLineEditsUseBoundedMemory(t *testing.T) {
	const lineCount = 1 << 20
	for _, tc := range []struct {
		name string
		run  func(string) error
	}{
		{name: "overwrite", run: func(path string) error {
			_, err := OverwriteLines(path, OverwriteLinesOptions{StartNum: lineCount / 2, Content: "changed\n"})
			return err
		}},
		{name: "insert", run: func(path string) error {
			_, err := InsertContent(path, InsertContentOptions{LineNum: lineCount / 2, Content: "inserted"})
			return err
		}},
	} {
		t.Run(tc.name, func(t *testing.T) {
			path := filepath.Join(t.TempDir(), "large.log")
			file, err := os.Create(path)
			if err != nil {
				t.Fatal(err)
			}
			block := strings.Repeat("line-00\n", 4096)
			for written := 0; written < lineCount; written += 4096 {
				if _, err := file.WriteString(block); err != nil {
					t.Fatal(err)
				}
			}
			if err := file.Close(); err != nil {
				t.Fatal(err)
			}
			before := editAllocatedBytes()
			if err := tc.run(path); err != nil {
				t.Fatal(err)
			}
			allocated := editAllocatedBytes() - before
			if allocated > 4<<20 {
				t.Fatalf("line edit allocated %d bytes; want at most %d", allocated, 4<<20)
			}
		})
	}
}

func TestOverwriteLinesAcceptsLineLargerThanReadScannerLimit(t *testing.T) {
	longLine := strings.Repeat("x", maxLineBytes+1)
	path := writeFixture(t, "long-line.log", longLine+"\ntail\n")
	if _, err := OverwriteLines(path, OverwriteLinesOptions{StartNum: 2, Content: "TAIL\n"}); err != nil {
		t.Fatal(err)
	}
	data, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	if string(data) != longLine+"\nTAIL\n" {
		t.Fatal("editing rejected or corrupted a line larger than the read scanner limit")
	}
}

func TestOverwriteLinesPreservesCRLFWithStreamingEdit(t *testing.T) {
	path := writeFixture(t, "windows.txt", "one\r\ntwo\r\nthree\r\n")
	if _, err := OverwriteLines(path, OverwriteLinesOptions{StartNum: 2, Content: "TWO"}); err != nil {
		t.Fatal(err)
	}
	got, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	if string(got) != "one\r\nTWO\r\nthree\r\n" {
		t.Fatalf("unexpected content %q", got)
	}
}
