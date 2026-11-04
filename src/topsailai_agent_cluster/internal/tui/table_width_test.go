package tui

import (
	"io"
	"strings"
	"testing"
	"unicode/utf8"
)

// TestTableTerminalWidths bounds real display cells without changing row identity.
func TestTableTerminalWidths(t *testing.T) {
	for _, width := range []int{40, 80, 120, 180} {
		rows := []SessionRow{{EndpointID: strings.Repeat("中", 30), ProviderSessionID: strings.Repeat("s", 80), State: "running"}}
		var out strings.Builder
		if err := RenderTable(&out, io.Discard, rows, nil, TableOptions{Width: width}); err != nil {
			t.Fatal(err)
		}
		for _, line := range strings.Split(out.String(), "\n") {
			if !utf8.ValidString(line) || displayWidth(line) > width {
				t.Fatalf("width=%d line=%q", width, line)
			}
		}
		if rows[0].No != 1 || rows[0].EndpointID != strings.Repeat("中", 30) {
			t.Fatalf("mutated row: %+v", rows[0])
		}
	}
}

// TestTableUnknownWidthPreservesOutput keeps redirected output byte-identical.
func TestTableUnknownWidthPreservesOutput(t *testing.T) {
	rows := []SessionRow{{EndpointID: "ep", State: "running"}}
	var unknown, wide strings.Builder
	if err := RenderTable(&unknown, io.Discard, rows, nil, TableOptions{}); err != nil {
		t.Fatal(err)
	}
	if err := RenderTable(&wide, io.Discard, rows, nil, TableOptions{Width: 1000}); err != nil {
		t.Fatal(err)
	}
	if unknown.String() != wide.String() {
		t.Fatal("unconstrained output changed")
	}
	if OutputWidth(&unknown) != 0 {
		t.Fatal("nonterminal width")
	}
}

// TestNarrowTableWriteFailure preserves writer failure identity.
func TestNarrowTableWriteFailure(t *testing.T) {
	if err := writeNarrowTable(exampleFailureWriter{err: errTableFixture}, [][]string{{"example:"}}, 40); err != errTableFixture {
		t.Fatalf("error=%v", err)
	}
}

// sizedTableOutput supplies a width without any global terminal state.
type sizedTableOutput struct {
	strings.Builder
	width int
}

// TerminalWidth exposes the injected test terminal width.
func (out *sizedTableOutput) TerminalWidth() int { return out.width }

// TestOutputWidthCapability forwards explicit output size.
func TestOutputWidthCapability(t *testing.T) {
	if got := OutputWidth(&sizedTableOutput{width: 120}); got != 120 {
		t.Fatalf("width=%d", got)
	}
}
