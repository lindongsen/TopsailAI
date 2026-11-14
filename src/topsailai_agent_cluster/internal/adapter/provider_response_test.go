package adapter

import (
	"errors"
	"os/exec"
	"strings"
	"testing"

	"topsailai_agent_cluster/internal/protocol"
)

// TestBoundedProviderResponseKeepsSmallDocument proves a document within the
// bound is carried unchanged and is not labelled truncated.
func TestBoundedProviderResponseKeepsSmallDocument(t *testing.T) {
	document := `{"outcome":"accepted"}`
	got, truncated := BoundedProviderResponse(document)
	if got != document {
		t.Fatalf("document=%q want %q", got, document)
	}
	if truncated {
		t.Fatal("small document must not be labelled truncated")
	}
}

// TestBoundedProviderResponseTruncatesAtRuneBoundary proves an oversized
// document is bounded, labelled, and never split inside a multi-byte rune.
func TestBoundedProviderResponseTruncatesAtRuneBoundary(t *testing.T) {
	// A three-byte rune straddling the bound would leave invalid UTF-8 if the
	// document were cut at the byte limit.
	document := strings.Repeat("a", protocol.MaxProviderResponseBytes-1) + "世" + "tail"
	got, truncated := BoundedProviderResponse(document)
	if !truncated {
		t.Fatal("oversized document must be labelled truncated")
	}
	if len(got) > protocol.MaxProviderResponseBytes {
		t.Fatalf("bounded length=%d exceeds limit=%d", len(got), protocol.MaxProviderResponseBytes)
	}
	if strings.ContainsRune(got, '\uFFFD') {
		t.Fatal("truncation split a rune and produced invalid UTF-8")
	}
	if !strings.HasPrefix(got, "aaaa") {
		t.Fatalf("bounded document lost its prefix: %q", got[:8])
	}
}

// TestProviderFailureTextReadsExitErrorStderr proves the provider's own stderr
// is recovered through a wrapped exit error.
func TestProviderFailureTextReadsExitErrorStderr(t *testing.T) {
	exitErr := &exec.ExitError{Stderr: []byte("provider diagnostic")}
	wrapped := errors.Join(errors.New("execute adapter"), exitErr)
	if got := ProviderFailureText(wrapped); got != "provider diagnostic" {
		t.Fatalf("failure text=%q want %q", got, "provider diagnostic")
	}
}

// TestProviderFailureTextIgnoresNonExitError proves a failure without captured
// stderr yields no fabricated diagnostic.
func TestProviderFailureTextIgnoresNonExitError(t *testing.T) {
	if got := ProviderFailureText(errors.New("no exit error")); got != "" {
		t.Fatalf("failure text=%q want empty", got)
	}
}
