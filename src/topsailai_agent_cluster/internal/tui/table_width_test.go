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
	if err := writeNarrowTable(exampleFailureWriter{err: errTableFixture}, [][]string{{"example:"}}, 40, ColorPolicy{}); err != errTableFixture {
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

// narrowProbeWidth returns a width below the tabular threshold without magic numbers.
func narrowProbeWidth() int {
	return minimumTableWidth(len(tableHeaders)) - len("abcd")
}

// TestNarrowTableKeepsStylingAndFullSessionName guards the narrow-terminal contract.
func TestNarrowTableKeepsStylingAndFullSessionName(t *testing.T) {
	name := "PS11-" + strings.Repeat("segment-", 899) + "tail"
	rows := []SessionRow{
		{No: 701, EndpointID: "ep", AdapterID: "ad", ProviderSessionID: "prov", DisplayName: name, State: "running", CollectionStatus: "succeeded"},
		{No: 702, EndpointID: "ep", AdapterID: "ad", ProviderSessionID: "prov2", DisplayName: "other", State: "failed", CollectionStatus: "failed"},
	}
	var out strings.Builder
	if err := RenderTable(&out, io.Discard, rows, nil, TableOptions{Width: narrowProbeWidth(), Color: ColorPolicy{Enabled: true}}); err != nil {
		t.Fatal(err)
	}
	rendered := out.String()
	if !strings.Contains(rendered, "SESSION_NAME: ") {
		t.Fatalf("expected narrow layout, got %q", rendered)
	}
	if !strings.Contains(rendered, name) {
		t.Fatalf("session name was truncated: %q", rendered)
	}
	if !strings.Contains(rendered, ansiBoldCyan+"SESSION_NAME: "+ansiReset) {
		t.Fatalf("narrow label is not styled: %q", rendered)
	}
	if !strings.Contains(rendered, ansiGreen+"running"+ansiReset) {
		t.Fatalf("running state is not green: %q", rendered)
	}
	if !strings.Contains(rendered, ansiRed+"failed"+ansiReset) {
		t.Fatalf("failed state is not red: %q", rendered)
	}
}

// TestNarrowTableWithoutColorStaysPlain keeps redirected narrow output free of escapes.
func TestNarrowTableWithoutColorStaysPlain(t *testing.T) {
	rows := []SessionRow{{No: 703, EndpointID: "ep", AdapterID: "ad", DisplayName: "name", State: "running", CollectionStatus: "succeeded"}}
	var out strings.Builder
	if err := RenderTable(&out, io.Discard, rows, nil, TableOptions{Width: narrowProbeWidth()}); err != nil {
		t.Fatal(err)
	}
	if strings.Contains(out.String(), "\x1b[") {
		t.Fatalf("plain narrow output contains escapes: %q", out.String())
	}
}
