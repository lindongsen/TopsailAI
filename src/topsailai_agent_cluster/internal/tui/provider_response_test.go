package tui

import (
	"strings"
	"testing"

	"topsailai_agent_cluster/internal/protocol"
)

// TestRenderReceiptDetailsPrintsProviderResponseSeparately proves the operator
// sees two distinct parts: this service's receipt fields and the provider's own
// raw return document, in that order.
func TestRenderReceiptDetailsPrintsProviderResponseSeparately(t *testing.T) {
	document := `{"ok":true,"delivery_state":"submitted","request_id":"req-1"}`
	receipt := protocol.ExecutionReceipt{
		CommandID:        "cli-1",
		Phase:            protocol.PhaseReceiptRecorded,
		DeliveryBoundary: protocol.DeliverySubmitted,
		EffectCertainty:  protocol.EffectAcknowledged,
		Outcome:          "not_reported",
		ProviderResponse: document,
	}

	var out strings.Builder
	if err := renderReceiptDetails(&out, receipt); err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	rendered := out.String()
	if !strings.Contains(rendered, "provider_response:\n"+document+"\n") {
		t.Fatalf("provider document missing or not verbatim in %q", rendered)
	}
	if strings.Index(rendered, "command_id:") > strings.Index(rendered, "provider_response:") {
		t.Fatalf("receipt fields must precede the provider section in %q", rendered)
	}
	if strings.Contains(rendered, "provider_response_truncated") {
		t.Fatalf("a complete document must not be labelled truncated in %q", rendered)
	}
}

// TestRenderReceiptDetailsLabelsTruncatedProviderResponse proves a bounded
// document is never presented as complete.
func TestRenderReceiptDetailsLabelsTruncatedProviderResponse(t *testing.T) {
	receipt := protocol.ExecutionReceipt{CommandID: "cli-1", ProviderResponse: `{"ok":true`, ProviderResponseTruncated: true}

	var out strings.Builder
	if err := renderReceiptDetails(&out, receipt); err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if !strings.Contains(out.String(), "provider_response_truncated: true") {
		t.Fatalf("missing truncation label in %q", out.String())
	}
}

// TestRenderReceiptDetailsOmitsAbsentProviderResponse keeps the previous output
// byte-identical when the provider returns no document.
func TestRenderReceiptDetailsOmitsAbsentProviderResponse(t *testing.T) {
	receipt := protocol.ExecutionReceipt{CommandID: "cli-1", Outcome: "not_reported"}

	var out strings.Builder
	if err := renderReceiptDetails(&out, receipt); err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if strings.Contains(out.String(), "provider_response") {
		t.Fatalf("absent document must print no section, got %q", out.String())
	}
}

// TestRenderInteractiveStartResultPrintsProviderResponse proves the session-scope
// lifecycle surface shows the provider document too, so both session-scope
// renderers cannot drift apart.
func TestRenderInteractiveStartResultPrintsProviderResponse(t *testing.T) {
	document := `{"ok":true,"signal_sent":true,"exit_confirmed":false}`
	result := map[string]any{
		"status":            string(protocol.StatusFinished),
		"delivery_boundary": string(protocol.DeliverySignalSent),
		"effect_certainty":  string(protocol.EffectAcknowledged),
		"provider_response": document,
	}

	var out strings.Builder
	if err := renderInteractiveStartResult(&out, "cli-2", result); err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	rendered := out.String()
	if !strings.Contains(rendered, "CommandID: cli-2") {
		t.Fatalf("missing receipt line in %q", rendered)
	}
	if !strings.Contains(rendered, "provider_response:\n"+document+"\n") {
		t.Fatalf("provider document missing or not verbatim in %q", rendered)
	}
}

// TestRenderInteractiveStartResultOmitsAbsentProviderResponse keeps the previous
// lifecycle output unchanged when no provider document exists.
func TestRenderInteractiveStartResultOmitsAbsentProviderResponse(t *testing.T) {
	result := map[string]any{"status": string(protocol.StatusFinished)}

	var out strings.Builder
	if err := renderInteractiveStartResult(&out, "cli-3", result); err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if strings.Contains(out.String(), "provider_response") {
		t.Fatalf("absent document must print no section, got %q", out.String())
	}
}
