package tui

import (
	"bytes"
	"strings"
	"testing"

	"topsailai_agent_cluster/internal/protocol"
)

// TestFilterProviderOutputNormalizesCarriageReturns proves a provider carriage
// return is rendered as a line break instead of a replacement rune. A provider
// progress frame such as "\rGenerating... 0 chars" is ordinary log content, so
// the operator must be able to read it.
func TestFilterProviderOutputNormalizesCarriageReturns(t *testing.T) {
	testCases := []struct {
		name  string
		input string
		want  string
	}{
		{name: "crlf collapses to one break", input: "a\r\nb", want: "a\nb"},
		{name: "standalone cr becomes a break", input: "a\rb", want: "a\nb"},
		{name: "leading cr becomes a break", input: "\rGenerating... 0 chars", want: "\nGenerating... 0 chars"},
		{name: "repeated redraw frames stay readable", input: "\rGenerating... 0 chars\rGenerating... 4 chars", want: "\nGenerating... 0 chars\nGenerating... 4 chars"},
		{name: "no carriage return is unchanged", input: "plain\ntext", want: "plain\ntext"},
	}
	for _, testCase := range testCases {
		t.Run(testCase.name, func(t *testing.T) {
			got := filterProviderOutput(testCase.input, ColorPolicy{})
			if got != testCase.want {
				t.Fatalf("filterProviderOutput(%q) = %q, want %q", testCase.input, got, testCase.want)
			}
			if strings.ContainsRune(got, '\uFFFD') {
				t.Fatalf("carriage return was reported as a replacement rune: %q", got)
			}
			if strings.ContainsRune(got, '\r') {
				t.Fatalf("raw carriage return reached the terminal: %q", got)
			}
		})
	}
}

// TestFilterProviderOutputKeepsColourAcrossCarriageReturns proves normalizing a
// carriage return does not disturb the SGR allow list, so provider colour still
// survives when the policy is enabled and still disappears when it is disabled.
func TestFilterProviderOutputKeepsColourAcrossCarriageReturns(t *testing.T) {
	input := "\rGenerating\x1b[31m...\x1b[0m 4 chars"
	coloured := filterProviderOutput(input, ColorPolicy{Enabled: true})
	if !strings.Contains(coloured, "\x1b[31m") || !strings.Contains(coloured, "\x1b[0m") {
		t.Fatalf("provider colour was lost: %q", coloured)
	}
	if strings.ContainsRune(coloured, '\r') || strings.ContainsRune(coloured, '\uFFFD') {
		t.Fatalf("carriage return survived with colour enabled: %q", coloured)
	}
	plain := filterProviderOutput(input, ColorPolicy{})
	if strings.Contains(plain, "\x1b[") {
		t.Fatalf("escape sequence survived with colour disabled: %q", plain)
	}
	if strings.ContainsRune(plain, '\r') || strings.ContainsRune(plain, '\uFFFD') {
		t.Fatalf("carriage return survived with colour disabled: %q", plain)
	}
}

// TestSanitizeTerminalStillReplacesCarriageReturn proves the stricter rule for
// trusted-context interpolation is unchanged. Prompts, table cells and
// diagnostics keep replacing a control byte, because those surfaces must never
// gain an extra row from untrusted text.
func TestSanitizeTerminalStillReplacesCarriageReturn(t *testing.T) {
	got := sanitizeTerminal([]byte("a\rb"))
	if strings.ContainsRune(got, '\r') {
		t.Fatalf("raw carriage return reached a trusted surface: %q", got)
	}
	if !strings.ContainsRune(got, '\uFFFD') {
		t.Fatalf("trusted surface no longer reports the control byte: %q", got)
	}
}

// TestRenderSnapshotStyledNormalizesCarriageReturns proves the snapshot entry
// point the logs command uses renders a provider redraw frame as a readable line
// rather than a replacement rune.
func TestRenderSnapshotStyledNormalizesCarriageReturns(t *testing.T) {
	var out strings.Builder
	RenderSnapshotStyled(&out, 123, "\rGenerating... 0 chars\rGenerating... 4 chars\n", false, 0, ColorPolicy{})
	rendered := out.String()
	if strings.ContainsRune(rendered, '\uFFFD') {
		t.Fatalf("snapshot reported a replacement rune: %q", rendered)
	}
	if strings.ContainsRune(rendered, '\r') {
		t.Fatalf("snapshot emitted a raw carriage return: %q", rendered)
	}
	if !strings.Contains(rendered, "Generating... 0 chars") || !strings.Contains(rendered, "Generating... 4 chars") {
		t.Fatalf("snapshot lost a provider frame: %q", rendered)
	}
}

// TestRenderSnapshotStyledCountsRedrawFramesAsLines proves the line budget is
// applied after normalization. Counting a multi-frame provider line as one line
// and then printing every frame would exceed the requested limit.
func TestRenderSnapshotStyledCountsRedrawFramesAsLines(t *testing.T) {
	var out strings.Builder
	RenderSnapshotStyled(&out, 123, "first\rsecond\rthird\n", false, 2, ColorPolicy{})
	rendered := out.String()
	if strings.Contains(rendered, "first") {
		t.Fatalf("line budget was applied before normalization: %q", rendered)
	}
	if !strings.Contains(rendered, "second") || !strings.Contains(rendered, "third") {
		t.Fatalf("newest frames were dropped: %q", rendered)
	}
	if !strings.Contains(rendered, "truncated: true") {
		t.Fatalf("clipping was not reported: %q", rendered)
	}
}

// TestRenderFollowRecordNormalizesCarriageReturns proves the follow path shares
// the same normalization, so a streamed redraw frame is as readable as a
// snapshot one.
func TestRenderFollowRecordNormalizesCarriageReturns(t *testing.T) {
	var buffer bytes.Buffer
	record := protocol.OutputFollowRecord{Lines: []string{"\rGenerating... 4 chars"}}
	if err := renderFollowRecord(&buffer, record, ColorPolicy{}, false); err != nil {
		t.Fatalf("renderFollowRecord: %v", err)
	}
	rendered := buffer.String()
	if strings.ContainsRune(rendered, '\uFFFD') {
		t.Fatalf("follow reported a replacement rune: %q", rendered)
	}
	if strings.ContainsRune(rendered, '\r') {
		t.Fatalf("follow emitted a raw carriage return: %q", rendered)
	}
	if !strings.Contains(rendered, "Generating... 4 chars") {
		t.Fatalf("follow lost the provider frame: %q", rendered)
	}
}
