package topsailai

import (
	"context"
	"os/exec"
	"strings"
	"testing"
	"unicode/utf8"

	"topsailai_agent_cluster/internal/adapter"
	"topsailai_agent_cluster/internal/protocol"
)

// TestExecuteCarriesProviderResponseOnSuccess proves the provider's own return
// document survives the adapter instead of being reduced to normalized fields.
func TestExecuteCarriesProviderResponseOnSuccess(t *testing.T) {
	runner := &fakeRunner{out: []byte(`{"items":[{"session_id":"provider-secret","process_generation":"g1"}]}`)}
	a := newTestAdapter(t, runner)
	if _, err := a.Discover(context.Background(), adapter.DiscoverRequest{}); err != nil {
		t.Fatal(err)
	}
	document := `{"ok":true,"delivery_state":"submitted","request_id":"req-1"}`
	runner.out = []byte(document)
	result, err := a.Execute(context.Background(), adapter.ExecuteRequest{Intent: protocol.ImmutableIntent{
		CommandID: "c1", Operation: protocol.OperationMessageSend,
		Target: &protocol.CommandTarget{ResourceID: "res_provider-secret", Generation: "g1"}, Payload: []byte(`{"text":"hi"}`),
	}})
	if err != nil {
		t.Fatal(err)
	}
	if result.Receipt.ProviderResponse != document {
		t.Fatalf("provider response = %q, want %q", result.Receipt.ProviderResponse, document)
	}
	if result.Receipt.ProviderResponseTruncated {
		t.Fatal("a document within the bound must not be marked truncated")
	}
}

// TestExecuteCarriesProviderStderrOnFailure proves a failed invocation keeps the
// provider's own diagnostic, which is the only evidence of why it failed.
func TestExecuteCarriesProviderStderrOnFailure(t *testing.T) {
	runner := &fakeRunner{out: []byte(`{"items":[{"session_id":"provider-secret","process_generation":"g1"}]}`)}
	a := newTestAdapter(t, runner)
	if _, err := a.Discover(context.Background(), adapter.DiscoverRequest{}); err != nil {
		t.Fatal(err)
	}
	runner.out = nil
	runner.err = &exec.ExitError{Stderr: []byte("provider: session not found\n")}
	result, err := a.Execute(context.Background(), adapter.ExecuteRequest{Intent: protocol.ImmutableIntent{
		CommandID: "c1", Operation: protocol.OperationMessageSend,
		Target: &protocol.CommandTarget{ResourceID: "res_provider-secret", Generation: "g1"}, Payload: []byte(`{"text":"hi"}`),
	}})
	if err == nil {
		t.Fatal("a failed provider invocation must return an error")
	}
	if result.Receipt.ProviderResponse != "provider: session not found\n" {
		t.Fatalf("provider response = %q", result.Receipt.ProviderResponse)
	}
	if result.Receipt.EffectCertainty != protocol.EffectUnknown {
		t.Fatalf("effect certainty = %q, want unknown", result.Receipt.EffectCertainty)
	}
}

// TestExecuteOmitsProviderResponseWhenProviderReturnsNothing keeps the previous
// output byte-identical for a provider that returns no document.
func TestExecuteOmitsProviderResponseWhenProviderReturnsNothing(t *testing.T) {
	runner := &fakeRunner{out: []byte(`{"items":[{"session_id":"provider-secret","process_generation":"g1"}]}`)}
	a := newTestAdapter(t, runner)
	if _, err := a.Discover(context.Background(), adapter.DiscoverRequest{}); err != nil {
		t.Fatal(err)
	}
	runner.out = nil
	runner.err = &exec.ExitError{}
	result, _ := a.Execute(context.Background(), adapter.ExecuteRequest{Intent: protocol.ImmutableIntent{
		CommandID: "c1", Operation: protocol.OperationMessageSend,
		Target: &protocol.CommandTarget{ResourceID: "res_provider-secret", Generation: "g1"}, Payload: []byte(`{"text":"hi"}`),
	}})
	if result.Receipt.ProviderResponse != "" {
		t.Fatalf("provider response = %q, want empty", result.Receipt.ProviderResponse)
	}
	if result.Receipt.ProviderResponseTruncated {
		t.Fatal("an absent document must not be marked truncated")
	}
}

// TestBoundedProviderResponseTruncatesOnRuneBoundary proves an oversized document
// is bounded, labelled, and still valid UTF-8 rather than split mid-rune.
func TestBoundedProviderResponseTruncatesOnRuneBoundary(t *testing.T) {
	exact := strings.Repeat("a", protocol.MaxProviderResponseBytes)
	if got, truncated := boundedProviderResponse(exact); got != exact || truncated {
		t.Fatalf("a document at the bound must pass through unchanged (len=%d, truncated=%t)", len(got), truncated)
	}
	// A three-byte rune straddling the bound must not be cut in half.
	oversized := strings.Repeat("a", protocol.MaxProviderResponseBytes-1) + "世" + strings.Repeat("b", 10)
	got, truncated := boundedProviderResponse(oversized)
	if !truncated {
		t.Fatal("an oversized document must be marked truncated")
	}
	if len(got) > protocol.MaxProviderResponseBytes {
		t.Fatalf("bounded length = %d, want at most %d", len(got), protocol.MaxProviderResponseBytes)
	}
	if !utf8.ValidString(got) {
		t.Fatal("truncation must not split a rune")
	}
	if got != strings.Repeat("a", protocol.MaxProviderResponseBytes-1) {
		t.Fatalf("unexpected truncation result of length %d", len(got))
	}
}
