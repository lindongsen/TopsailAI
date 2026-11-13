package tui

import (
	"strings"
	"testing"

	"topsailai_agent_cluster/internal/protocol"
)

// TestRenderReceiptDetailsPrintsProviderResponseSeparately proves the operator
// sees two distinct parts: this service's receipt fields and the provider's own
// return document, in that order.
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
	if !strings.Contains(rendered, "provider_response:\n") {
		t.Fatalf("provider section missing in %q", rendered)
	}
	if strings.Index(rendered, "command_id:") > strings.Index(rendered, "provider_response:") {
		t.Fatalf("receipt fields must precede the provider section in %q", rendered)
	}
	if strings.Contains(rendered, "provider_response_truncated") {
		t.Fatalf("a complete document must not be labelled truncated in %q", rendered)
	}
}

// TestRenderReceiptDetailsRendersProviderResponseAsText proves the provider
// document is rendered for a human instead of being printed as raw JSON.
//
// This is the defect the human reported: the document arrived as one line of
// braces and quotes, so a first-level value that was itself an object or a list
// was unreadable. The assertion forbids JSON punctuation in the section body,
// because the presence of braces is exactly what made it unreadable.
func TestRenderReceiptDetailsRendersProviderResponseAsText(t *testing.T) {
	document := `{"ok":true,"delivery_state":"submitted","request_id":"req-1"}`
	receipt := protocol.ExecutionReceipt{CommandID: "cli-1", ProviderResponse: document}

	var out strings.Builder
	if err := renderReceiptDetails(&out, receipt); err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	body := providerSectionBody(out.String())
	if body == "" {
		t.Fatalf("provider section body is empty in %q", out.String())
	}
	if strings.ContainsAny(body, "{}") {
		t.Fatalf("provider section body = %q, want no braces", body)
	}
	if strings.Contains(body, `"`) {
		t.Fatalf("provider section body = %q, want no quotes", body)
	}
	for _, want := range []string{"delivery_state: submitted", "ok: true", "request_id: req-1"} {
		if !strings.Contains(body, want) {
			t.Fatalf("provider section body = %q, want %q", body, want)
		}
	}
}

// TestRenderReceiptDetailsRendersNestedProviderValues proves a first-level value
// that is itself an object or a list is indented under its key.
//
// The human named this case explicitly: the first-level value may be a dict or a
// list. A renderer that only flattened the top level would still print the nested
// value as JSON, so the nested shape is asserted here rather than assumed.
func TestRenderReceiptDetailsRendersNestedProviderValues(t *testing.T) {
	document := `{"response":{"deleted":3,"items":["a","b"]},"counts":[1,2]}`
	receipt := protocol.ExecutionReceipt{CommandID: "cli-1", ProviderResponse: document}

	var out strings.Builder
	if err := renderReceiptDetails(&out, receipt); err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	body := providerSectionBody(out.String())
	if strings.ContainsAny(body, "{}") {
		t.Fatalf("provider section body = %q, want no braces", body)
	}
	if strings.Contains(body, `"`) {
		t.Fatalf("provider section body = %q, want no quotes", body)
	}
	lines := strings.Split(body, "\n")
	if !containsLine(lines, "response:") {
		t.Fatalf("provider section body = %q, want the nested object under its key", body)
	}
	if !containsLine(lines, "  deleted: 3") {
		t.Fatalf("provider section body = %q, want the nested pair indented", body)
	}
	if !containsLine(lines, "    - a") || !containsLine(lines, "    - b") {
		t.Fatalf("provider section body = %q, want the nested list as bullets", body)
	}
	if !containsLine(lines, "counts:") {
		t.Fatalf("provider section body = %q, want the nested list under its key", body)
	}
}

// TestRenderReceiptDetailsKeepsProviderNumbersLiteral proves a large integer is
// printed as its own digits.
//
// A provider document carries epoch-millisecond timestamps, byte counts and
// process identifiers. Decoding them as float64 would print 1794470400000 as
// 1.7944704e+12, which is the same value in a form the operator cannot compare
// against a timestamp anywhere else in the output.
func TestRenderReceiptDetailsKeepsProviderNumbersLiteral(t *testing.T) {
	document := `{"started_at_ms":1794470399900,"finished_at_ms":1794470400000,"bytes_written":1048576,"pid":12345}`
	receipt := protocol.ExecutionReceipt{CommandID: "cli-1", ProviderResponse: document}

	var out strings.Builder
	if err := renderReceiptDetails(&out, receipt); err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	body := providerSectionBody(out.String())
	for _, want := range []string{
		"started_at_ms: 1794470399900",
		"finished_at_ms: 1794470400000",
		"bytes_written: 1048576",
		"pid: 12345",
	} {
		if !strings.Contains(body, want) {
			t.Fatalf("provider section body = %q, want %q", body, want)
		}
	}
	if strings.Contains(body, "e+") {
		t.Fatalf("provider section body = %q, want no scientific notation", body)
	}
}

// TestRenderReceiptDetailsKeepsNonJSONProviderResponseVerbatim proves a document
// that is not one JSON value is printed unchanged.
//
// A failed invocation carries the provider's stderr, and a truncated answer is
// invalid JSON by construction. Re-encoding either would fail or drop the part
// that did not parse, and that part is the only diagnostic the operator has.
func TestRenderReceiptDetailsKeepsNonJSONProviderResponseVerbatim(t *testing.T) {
	for _, document := range []string{
		"fixture execution failure",
		`{"ok":true`,
		"{\"a\":1}\n{\"b\":2}",
	} {
		receipt := protocol.ExecutionReceipt{CommandID: "cli-1", ProviderResponse: document}

		var out strings.Builder
		if err := renderReceiptDetails(&out, receipt); err != nil {
			t.Fatalf("unexpected error: %v", err)
		}
		if !strings.Contains(out.String(), "provider_response:\n"+document+"\n") {
			t.Fatalf("document %q was not printed verbatim in %q", document, out.String())
		}
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
	body := providerSectionBody(rendered)
	if body == "" {
		t.Fatalf("provider section body is empty in %q", rendered)
	}
	if strings.ContainsAny(body, "{}") {
		t.Fatalf("provider section body = %q, want no braces", body)
	}
	for _, want := range []string{"exit_confirmed: false", "ok: true", "signal_sent: true"} {
		if !strings.Contains(body, want) {
			t.Fatalf("provider section body = %q, want %q", body, want)
		}
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

// providerSectionBody returns the text after the provider section label, with the
// truncation label removed so a body assertion is not satisfied by it.
func providerSectionBody(rendered string) string {
	const label = "provider_response:\n"
	index := strings.Index(rendered, label)
	if index < 0 {
		return ""
	}
	body := rendered[index+len(label):]
	if cut := strings.Index(body, "provider_response_truncated:"); cut >= 0 {
		body = body[:cut]
	}
	return strings.TrimSpace(body)
}

// containsLine reports whether one exact line is present.
//
// An exact line comparison is used instead of a substring match because the
// indentation is part of the assertion: a nested pair that is not indented is not
// rendered under its key, and a substring match would accept it anyway.
func containsLine(lines []string, want string) bool {
	for _, line := range lines {
		if line == want {
			return true
		}
	}
	return false
}
