package providercli

import (
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

// presenceDocumentPath is the contract document that must state the three presence outcomes.
const presenceDocumentPath = "../../docs/agent-cluster-protocol.md"

// presenceDocumentSection is the heading whose body must carry the documented outcomes.
const presenceDocumentSection = "### Missing, null and empty values"

// readPresenceDocumentSection returns the body of the presence section, excluding the heading.
func readPresenceDocumentSection(t *testing.T) string {
	t.Helper()
	content, err := os.ReadFile(filepath.Clean(presenceDocumentPath))
	if err != nil {
		t.Fatalf("read %s: %v", presenceDocumentPath, err)
	}
	text := string(content)
	start := strings.Index(text, presenceDocumentSection)
	if start < 0 {
		t.Fatalf("%s has no %q section, so the three presence outcomes are undocumented", presenceDocumentPath, presenceDocumentSection)
	}
	body := text[start+len(presenceDocumentSection):]
	if end := strings.Index(body, "\n### "); end >= 0 {
		body = body[:end]
	}
	return body
}

// basePresenceRequest returns a complete describe request that the decoder accepts.
func basePresenceRequest() map[string]any {
	return map[string]any{
		"protocol": "agent-cluster-adapter", "major": 1, "minor": 0,
		"request_id": "request-1", "function": "describe", "adapter_id": "adapter-1",
		"deadline_at_ms": 1,
		"budget":         map[string]any{"max_stdout_bytes": 1, "max_stderr_bytes": 1, "max_records": 1},
		"payload":        map[string]any{},
	}
}

// decodeRequestError returns the decoder error text for one mutated request.
func decodeRequestError(t *testing.T, mutate func(map[string]any)) string {
	t.Helper()
	document := basePresenceRequest()
	mutate(document)
	encoded, err := json.Marshal(document)
	if err != nil {
		t.Fatalf("encode request: %v", err)
	}
	if _, err := DecodeRequest(encoded); err != nil {
		return err.Error()
	}
	return ""
}

// decodeFrameError returns the decoder error text for one mutated stream frame.
func decodeFrameError(t *testing.T, frameType string, mutate func(map[string]any)) string {
	t.Helper()
	document := map[string]any{
		"protocol": "agent-cluster-adapter", "major": 1, "minor": 0,
		"request_id": "request-1", "type": frameType, "sequence": 1,
	}
	if frameType == FrameRecord {
		document["observed_at_ms"] = 1
	}
	mutate(document)
	encoded, err := json.Marshal(document)
	if err != nil {
		t.Fatalf("encode frame: %v", err)
	}
	if _, err := DecodeStreamFrame(encoded); err != nil {
		return err.Error()
	}
	return ""
}

// TestPresenceDocumentQuotesTheMeasuredMessages pins every message the document quotes to the decoder.
func TestPresenceDocumentQuotesTheMeasuredMessages(t *testing.T) {
	body := readPresenceDocumentSection(t)
	cases := []struct {
		label  string
		actual string
	}{
		{"absent required field", decodeRequestError(t, func(d map[string]any) { delete(d, "payload") })},
		{"null payload", decodeRequestError(t, func(d map[string]any) { d["payload"] = nil })},
		{"absent identifier", decodeRequestError(t, func(d map[string]any) { delete(d, "adapter_id") })},
		{"null identifier", decodeRequestError(t, func(d map[string]any) { d["adapter_id"] = nil })},
		{"empty identifier", decodeRequestError(t, func(d map[string]any) { d["adapter_id"] = "" })},
		{"absent record", decodeFrameError(t, FrameRecord, func(d map[string]any) { delete(d, "record") })},
		{"null record", decodeFrameError(t, FrameRecord, func(d map[string]any) { d["record"] = nil })},
		{"forbidden null record", decodeFrameError(t, FrameStarted, func(d map[string]any) { d["record"] = nil })},
	}
	for _, c := range cases {
		if c.actual == "" {
			t.Fatalf("%s is accepted, so the document cannot describe a rejection for it", c.label)
		}
		if !strings.Contains(body, "`"+c.actual+"`") {
			t.Errorf("the presence section does not quote %q as a complete phrase, which the decoder returns for %s", c.actual, c.label)
		}
	}
}

// TestPresenceDocumentDistinguishesTheThreeOutcomes proves the document separates the outcomes it claims.
func TestPresenceDocumentDistinguishesTheThreeOutcomes(t *testing.T) {
	body := readPresenceDocumentSection(t)
	absent := decodeRequestError(t, func(d map[string]any) { delete(d, "payload") })
	null := decodeRequestError(t, func(d map[string]any) { d["payload"] = nil })
	empty := decodeRequestError(t, func(d map[string]any) { d["payload"] = map[string]any{} })
	if absent == null {
		t.Fatalf("the decoder reports the same error for an absent and a null payload, so the document cannot claim they differ")
	}
	if empty != "" {
		t.Fatalf("an empty payload is rejected with %q, so the document cannot claim an empty value is accepted", empty)
	}
	for _, phrase := range []string{"absent", "null", "empty"} {
		if !strings.Contains(body, phrase) {
			t.Errorf("the presence section never uses the word %q, so it does not state that outcome", phrase)
		}
	}
}

// TestPresenceDocumentStatesIdentifierRejection records how identifiers reject the three states.
func TestPresenceDocumentStatesIdentifierRejection(t *testing.T) {
	body := readPresenceDocumentSection(t)
	absent := decodeRequestError(t, func(d map[string]any) { delete(d, "adapter_id") })
	null := decodeRequestError(t, func(d map[string]any) { d["adapter_id"] = nil })
	empty := decodeRequestError(t, func(d map[string]any) { d["adapter_id"] = "" })
	if absent == "" || null == "" || empty == "" {
		t.Fatalf("an identifier state is accepted: absent=%q null=%q empty=%q", absent, null, empty)
	}
	if null != empty {
		t.Fatalf("a null and an empty identifier no longer share one message: null=%q empty=%q", null, empty)
	}
	if absent == null {
		t.Fatalf("an absent identifier now shares the message of a null one, so the document must stop separating them")
	}
	for _, message := range []string{absent, null} {
		if !strings.Contains(body, "`"+message+"`") {
			t.Errorf("the presence section does not quote %q as a complete phrase, which the decoder returns for an identifier", message)
		}
	}
}
