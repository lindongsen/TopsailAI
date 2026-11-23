package providercli

import (
	"encoding/json"
	"reflect"
	"sort"
	"strings"
	"testing"
)

// responseWithField returns a valid response document carrying one extra root
// field, so a rejection can only come from that field.
func responseWithField(t *testing.T, field string, value any) []byte {
	t.Helper()
	base := Response{
		Version:    validVersion(),
		RequestID:  "request-1",
		OK:         true,
		Descriptor: func() *Descriptor { value := validDescriptor(); return &value }(),
	}
	encoded, err := json.Marshal(base)
	if err != nil {
		t.Fatalf("marshal the base response: %v", err)
	}
	var document map[string]any
	if err := json.Unmarshal(encoded, &document); err != nil {
		t.Fatalf("unmarshal the base response: %v", err)
	}
	document[field] = value
	withField, err := json.Marshal(document)
	if err != nil {
		t.Fatalf("marshal the response with %q: %v", field, err)
	}
	return withField
}

// TestExecutionReceiptFieldsAreRejectedAtResponseRoot fails when a field that
// belongs to a Cluster ExecutionReceipt is accepted on the provider response.
//
// The contract states that the Adapter must not serialize a complete Cluster
// ExecutionReceipt onto the provider process boundary. The response therefore
// carries provider evidence, not Cluster journal state. Eight receipt names do
// appear inside operation_result, but they carry provider-side evidence rather
// than Cluster authority, and they are legal only there: at the response root
// every receipt name must be refused.
//
// The field set is read from the struct rather than listed here, so a field
// added to ExecutionReceipt is covered without editing this guard.
func TestExecutionReceiptFieldsAreRejectedAtResponseRoot(t *testing.T) {
	receiptFields := structJSONTags(t, "internal/protocol/command.go", "ExecutionReceipt")
	if len(receiptFields) == 0 {
		t.Fatal("ExecutionReceipt declares no JSON field, so this guard checked nothing")
	}
	for _, field := range receiptFields {
		_, err := DecodeResponse(responseWithField(t, field, "cluster-owned"))
		if err == nil {
			t.Errorf("the response accepts the ExecutionReceipt field %q at the root, so Cluster journal state can cross into provider evidence", field)
			continue
		}
		if !strings.Contains(err.Error(), "unknown field") {
			t.Errorf("the response rejects the ExecutionReceipt field %q for an unrelated reason (%v), so the rejection is not the one this row requires", field, err)
		}
	}
}

// responseWithResultField returns a valid response whose operation_result
// carries one extra field, so a rejection can only come from that field.
func responseWithResultField(t *testing.T, field string, value any) []byte {
	t.Helper()
	base := Response{
		Version:   validVersion(),
		RequestID: "request-1",
		OK:        true,
		Result: &OperationResult{
			DeliveryBoundary: DeliverySubmitted,
			EffectCertainty:  EffectAcknowledged,
			ProviderOutcome:  "submitted",
		},
	}
	encoded, err := json.Marshal(base)
	if err != nil {
		t.Fatalf("marshal the base result response: %v", err)
	}
	var document map[string]any
	if err := json.Unmarshal(encoded, &document); err != nil {
		t.Fatalf("unmarshal the base result response: %v", err)
	}
	result, ok := document["result"].(map[string]any)
	if !ok {
		t.Fatal("the base response carries no result object, so this guard checked nothing")
	}
	result[field] = value
	withField, err := json.Marshal(document)
	if err != nil {
		t.Fatalf("marshal the result with %q: %v", field, err)
	}
	return withField
}

// TestJournalPhaseAndCommandRevisionAreRejected fails when the two names this
// row calls out are accepted. command_revision is an ExecutionReceipt field and
// is covered above; journal_phase is not, because it names a Cluster journal
// concept rather than a receipt field, so it needs its own check.
//
// Both names are probed at the response root and inside operation_result. A
// root-only check misses the case where the field becomes legal inside the
// result object, which is where provider evidence actually lives.
func TestJournalPhaseAndCommandRevisionAreRejected(t *testing.T) {
	names := []string{"journal_phase", "command_revision"}
	if len(names) == 0 {
		t.Fatal("no name was enumerated, so this guard checked nothing")
	}
	for _, name := range names {
		_, rootErr := DecodeResponse(responseWithField(t, name, "cluster-owned"))
		if rootErr == nil {
			t.Errorf("the response accepts %q at the root, so Cluster journal state can cross into provider evidence", name)
		} else if !strings.Contains(rootErr.Error(), "unknown field") {
			t.Errorf("the response rejects %q at the root for an unrelated reason (%v), so the rejection is not the one this row requires", name, rootErr)
		}
		_, resultErr := DecodeResponse(responseWithResultField(t, name, "cluster-owned"))
		if resultErr == nil {
			t.Errorf("operation_result accepts %q, so Cluster journal state can cross into provider evidence", name)
		} else if !strings.Contains(resultErr.Error(), "unknown field") {
			t.Errorf("operation_result rejects %q for an unrelated reason (%v), so the rejection is not the one this row requires", name, resultErr)
		}
	}
}

// TestOperationResultAcceptsOnlyProviderEvidence fails when operation_result
// grows a field that is not provider evidence. The eight receipt names it does
// carry are provider-side values, so the check is that the result field set is
// exactly the OperationResult struct and nothing else.
func TestOperationResultAcceptsOnlyProviderEvidence(t *testing.T) {
	resultFields := structJSONTags(t, "internal/providercli/types.go", "OperationResult")
	if len(resultFields) == 0 {
		t.Fatal("OperationResult declares no JSON field, so this guard checked nothing")
	}
	allowed := make(map[string]bool, len(resultFields))
	for _, field := range resultFields {
		allowed[field] = true
	}
	receiptFields := structJSONTags(t, "internal/protocol/command.go", "ExecutionReceipt")
	// The names that legitimately carry provider-side evidence. They are listed
	// here rather than derived from the struct, because deriving them would make
	// the check circular: any field added to OperationResult would immediately
	// count as provider evidence, including a Cluster journal field such as
	// "phase". A shared name outside this set is a Cluster field that became
	// legal, which is exactly what this row forbids.
	providerEvidence := []string{
		"delivery_boundary",
		"effect_certainty",
		"exit_confirmed",
		"finished_at_ms",
		"provider_request_ref",
		"provider_response",
		"provider_response_truncated",
		"started_at_ms",
		// A warning is provider evidence: only the Provider knows what it could
		// not honour, and the Cluster forwards the list unchanged. It is not a
		// Cluster journal field, so it belongs in this set.
		"warnings",
	}
	if len(providerEvidence) == 0 {
		t.Fatal("no provider-evidence name was enumerated, so this guard checked nothing")
	}
	allowedEvidence := make(map[string]bool, len(providerEvidence))
	for _, field := range providerEvidence {
		allowedEvidence[field] = true
	}
	shared := make([]string, 0, len(providerEvidence))
	for _, field := range receiptFields {
		if allowed[field] {
			shared = append(shared, field)
		}
	}
	sort.Strings(shared)
	expected := append([]string(nil), providerEvidence...)
	sort.Strings(expected)
	if !reflect.DeepEqual(shared, expected) {
		t.Fatalf("operation_result and ExecutionReceipt share %v, but the provider-evidence set is %v, so a Cluster journal field is accepted as provider evidence", shared, expected)
	}
	// A receipt field that is not provider evidence must not be accepted inside
	// the result either. The shared set is the provider-evidence subset, and it
	// is bounded by the OperationResult struct itself.
	for _, field := range receiptFields {
		if allowed[field] {
			continue
		}
		base := Response{
			Version:   validVersion(),
			RequestID: "request-1",
			OK:        true,
			Result:    &OperationResult{DeliveryBoundary: DeliverySubmitted, EffectCertainty: EffectAcknowledged, ProviderOutcome: "submitted"},
		}
		encoded, err := json.Marshal(base)
		if err != nil {
			t.Fatalf("marshal the base result response: %v", err)
		}
		var document map[string]any
		if err := json.Unmarshal(encoded, &document); err != nil {
			t.Fatalf("unmarshal the base result response: %v", err)
		}
		result := document["result"].(map[string]any)
		result[field] = "cluster-owned"
		withField, err := json.Marshal(document)
		if err != nil {
			t.Fatalf("marshal the result with %q: %v", field, err)
		}
		_, err = DecodeResponse(withField)
		if err == nil {
			t.Errorf("operation_result accepts the ExecutionReceipt field %q, so Cluster journal state can cross into provider evidence", field)
			continue
		}
		if !strings.Contains(err.Error(), "unknown field") {
			t.Errorf("operation_result rejects the ExecutionReceipt field %q for an unrelated reason (%v), so the rejection is not the one this row requires", field, err)
		}
	}
}
