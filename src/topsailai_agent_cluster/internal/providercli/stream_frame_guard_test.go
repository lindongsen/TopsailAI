package providercli

import (
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

// streamFrameWithField returns a valid started frame carrying one extra root
// field, so a rejection can only come from that field.
func streamFrameWithField(t *testing.T, field string, value any) []byte {
	t.Helper()
	document := map[string]any{
		"protocol":   "agent-cluster-adapter",
		"major":      1,
		"minor":      0,
		"request_id": "request-1",
		"type":       FrameStarted,
		"sequence":   1,
	}
	document[field] = value
	encoded, err := json.Marshal(document)
	if err != nil {
		t.Fatalf("marshal the stream frame with %q: %v", field, err)
	}
	return encoded
}

// TestExecutionReceiptFieldsAreRejectedAtStreamFrameRoot fails when a field that
// belongs to a Cluster ExecutionReceipt is accepted on a provider stream frame.
//
// The contract states that the Adapter must not serialize a complete Cluster
// ExecutionReceipt onto the provider process boundary. A stream frame carries
// provider output, not Cluster journal state, so every receipt field must be
// refused at the frame root.
//
// The field set is read from the struct rather than listed here, so a field
// added to ExecutionReceipt is covered without editing this guard.
func TestExecutionReceiptFieldsAreRejectedAtStreamFrameRoot(t *testing.T) {
	receiptFields := structJSONTags(t, "internal/protocol/command.go", "ExecutionReceipt")
	if len(receiptFields) == 0 {
		t.Fatal("ExecutionReceipt declares no JSON field, so this guard checked nothing")
	}
	for _, field := range receiptFields {
		_, err := DecodeStreamFrame(streamFrameWithField(t, field, "cluster-owned"))
		if err == nil {
			t.Errorf("the stream frame accepts the ExecutionReceipt field %q at the root, so Cluster journal state can cross into provider output", field)
			continue
		}
		if !strings.Contains(err.Error(), "unknown field") {
			t.Errorf("the stream frame rejects the ExecutionReceipt field %q for an unrelated reason (%v), so the rejection is not the one this row requires", field, err)
		}
	}
}

// TestJournalPhaseAndCommandRevisionAreRejectedInStreamFrames fails when the two
// names this row calls out are accepted. command_revision is an ExecutionReceipt
// field and is covered above; journal_phase is not, because it names a Cluster
// journal concept rather than a receipt field, so it needs its own check.
func TestJournalPhaseAndCommandRevisionAreRejectedInStreamFrames(t *testing.T) {
	names := []string{"journal_phase", "command_revision"}
	if len(names) == 0 {
		t.Fatal("no name was enumerated, so this guard checked nothing")
	}
	for _, name := range names {
		_, err := DecodeStreamFrame(streamFrameWithField(t, name, "cluster-owned"))
		if err == nil {
			t.Errorf("the stream frame accepts %q at the root, so Cluster journal state can cross into provider output", name)
			continue
		}
		if !strings.Contains(err.Error(), "unknown field") {
			t.Errorf("the stream frame rejects %q for an unrelated reason (%v), so the rejection is not the one this row requires", name, err)
		}
	}
}

// TestStreamFrameRecordIsProviderOwned fails when the record container stops
// being provider output.
//
// record is a json.RawMessage, so the frame root check cannot see inside it. It
// is not a hole: the schema constrains it to a non-null JSON value, and the
// Adapter decodes it strictly into a shape of its own, so a Cluster receipt
// cannot ride inside it. This test pins that second half, because a container
// that is only bounded by "valid JSON" would accept anything.
func TestStreamFrameRecordIsProviderOwned(t *testing.T) {
	root := filepath.Join(schemaDirectory(t), "..", "..", "..")
	source, err := os.ReadFile(filepath.Join(root, "internal/adapter/genericcli/adapter.go"))
	if err != nil {
		t.Fatalf("read the adapter: %v", err)
	}
	text := string(source)
	anchor := "decodeStrictJSON(frame.Record, &record)"
	if !strings.Contains(text, anchor) {
		t.Fatalf("the adapter no longer decodes frame.Record strictly into its own shape, so the record container accepts arbitrary JSON and a Cluster receipt could ride inside it")
	}
	// The decoded shape must be provider output, not Cluster journal state.
	start := strings.Index(text, "var record struct {")
	if start < 0 {
		t.Fatal("the adapter declares no record shape, so this guard checked nothing")
	}
	body := text[start:]
	if end := strings.Index(body, "\n\t\t}"); end >= 0 {
		body = body[:end]
	}
	// Match the json tag rather than the bare word, because "phase" is a
	// substring of "journal_phase" and a bare-word match would report a field
	// that is not there.
	for _, forbidden := range []string{"command_id", "journal_phase", "command_revision", "phase", "receipt"} {
		if strings.Contains(body, `json:"`+forbidden+`"`) {
			t.Errorf("the adapter record shape carries the Cluster journal field %q, so Cluster state can ride inside a stream frame record", forbidden)
		}
	}
	if !strings.Contains(body, `json:"lines"`) {
		t.Errorf("the adapter record shape no longer carries provider output lines, so this guard checked the wrong shape")
	}
}
