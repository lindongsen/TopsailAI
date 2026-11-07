package tui

import (
	"bytes"
	"strings"
	"testing"
)

// providerBody mixes colour, a cursor clear and an OSC title change, so one
// fixture proves both halves of the contract: styling survives, control does not.
const providerBody = "\x1b[36mcyan\x1b[0m \x1b[1;31mboldred\x1b[0m \x1b[2Jcleared \x1b]0;evil\x07plain"

// TestRenderSnapshotStyledKeepsOnlySGRColour proves that enabling colour keeps
// colour-only SGR sequences while cursor movement and OSC title changes are
// still stripped, because the body is untrusted provider data.
func TestRenderSnapshotStyledKeepsOnlySGRColour(t *testing.T) {
	var out bytes.Buffer
	RenderSnapshotStyled(&out, 123, providerBody, false, 0, ColorPolicy{Enabled: true})
	got := out.String()

	for _, want := range []string{"\x1b[36m", "\x1b[1;31m", "cyan", "boldred", "cleared", "plain"} {
		if !strings.Contains(got, want) {
			t.Fatalf("output %q lost %q", got, want)
		}
	}
	for _, banned := range []string{"\x1b[2J", "\x1b]0;", "\x07"} {
		if strings.Contains(got, banned) {
			t.Fatalf("output %q kept dangerous sequence %q", got, banned)
		}
	}
}

// TestRenderSnapshotStyledDisabledEmitsNoEscape proves that a disabled colour
// policy produces byte-identical plain text, so --no-color, NO_COLOR, TERM=dumb
// and a redirected stream never receive an escape sequence.
func TestRenderSnapshotStyledDisabledEmitsNoEscape(t *testing.T) {
	var out bytes.Buffer
	RenderSnapshotStyled(&out, 123, providerBody, false, 0, ColorPolicy{})
	got := out.String()

	if strings.Contains(got, "\x1b") {
		t.Fatalf("disabled colour emitted an escape sequence: %q", got)
	}
	for _, want := range []string{"cyan", "boldred", "cleared", "plain"} {
		if !strings.Contains(got, want) {
			t.Fatalf("output %q lost text %q", got, want)
		}
	}
}

// TestRenderSnapshotCompatWrapperEmitsNoEscape proves the legacy entry point
// keeps its documented behaviour: it never emits an escape sequence, so a caller
// without a colour policy cannot leak provider control bytes.
func TestRenderSnapshotCompatWrapperEmitsNoEscape(t *testing.T) {
	var out bytes.Buffer
	RenderSnapshot(&out, 123, providerBody, false, 0)
	if strings.Contains(out.String(), "\x1b") {
		t.Fatalf("compatibility wrapper emitted an escape sequence: %q", out.String())
	}
}

// TestIsSGRSequenceAllowList pins the allow list to colour-only SGR, so a future
// change cannot widen it to cursor controls or private modes.
func TestIsSGRSequenceAllowList(t *testing.T) {
	cases := []struct {
		name     string
		sequence string
		want     bool
	}{
		{"reset", "\x1b[0m", true},
		{"colour", "\x1b[36m", true},
		{"bold colour", "\x1b[1;31m", true},
		{"colon form", "\x1b[38:5:196m", true},
		{"cursor clear", "\x1b[2J", false},
		{"cursor move", "\x1b[10;20H", false},
		{"private mode", "\x1b[?25l", false},
		{"osc title", "\x1b]0;evil\x07", false},
		{"bare escape", "\x1b", false},
		{"non digit parameter", "\x1b[1qm", false},
	}

	for _, testCase := range cases {
		t.Run(testCase.name, func(t *testing.T) {
			if got := isSGRSequence([]byte(testCase.sequence)); got != testCase.want {
				t.Fatalf("isSGRSequence(%q)=%v want=%v", testCase.sequence, got, testCase.want)
			}
		})
	}
}
