package tui

import (
	"bytes"
	"strings"
	"testing"
)

// TestRenderWarningsPrintsOneBulletPerWarning proves the operator sees the
// provider's warning instead of only the provider's own document.
//
// The warning is the only evidence that a message was dropped, so a renderer that
// silently ignored it would leave the operator believing the text was delivered.
func TestRenderWarningsPrintsOneBulletPerWarning(t *testing.T) {
	var out bytes.Buffer
	warnings := []string{"first finding", "second finding"}
	if err := renderWarnings(&out, warnings); err != nil {
		t.Fatalf("renderWarnings returned %v", err)
	}
	got := out.String()
	if !strings.Contains(got, "warnings:") {
		t.Fatalf("output %q has no warnings section", got)
	}
	for _, warning := range warnings {
		if !strings.Contains(got, "  - "+warning) {
			t.Fatalf("output %q does not print %q as a bullet", got, warning)
		}
	}
}

// TestRenderWarningsPrintsNothingForAnEmptyList proves a provider that reports no
// warning keeps the previous output byte-identical.
//
// Without this, every receipt would gain an empty section and the output of a
// provider that never warns would change for no reason.
func TestRenderWarningsPrintsNothingForAnEmptyList(t *testing.T) {
	var out bytes.Buffer
	if err := renderWarnings(&out, nil); err != nil {
		t.Fatalf("renderWarnings returned %v", err)
	}
	if out.Len() != 0 {
		t.Fatalf("output %q is not empty", out.String())
	}
}

// TestRenderProviderResponsePrintsWarningsBeforeTheDocument proves the warning
// section precedes the provider document.
//
// The warning describes what this invocation could not honour, so the operator
// must read it before the provider's own answer. Printing it after would let the
// document look complete while the loss was reported below it.
func TestRenderProviderResponsePrintsWarningsBeforeTheDocument(t *testing.T) {
	var out bytes.Buffer
	if err := renderProviderResponse(&out, `{"ok":true}`, false, []string{"message was not delivered"}); err != nil {
		t.Fatalf("renderProviderResponse returned %v", err)
	}
	got := out.String()
	warningIndex := strings.Index(got, "warnings:")
	documentIndex := strings.Index(got, "provider_response:")
	if warningIndex < 0 || documentIndex < 0 {
		t.Fatalf("output %q is missing a section", got)
	}
	if warningIndex > documentIndex {
		t.Fatalf("warnings printed after the provider document in %q", got)
	}
}
