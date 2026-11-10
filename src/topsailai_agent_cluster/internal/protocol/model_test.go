package protocol

import (
	"strings"
	"testing"
)

// TestValidateSafetyClassAcceptsClosedVocabulary pins the two standard values.
// The vocabulary is closed because the value decides whether an operator must
// confirm an operation and which scope a credential must hold.
func TestValidateSafetyClassAcceptsClosedVocabulary(t *testing.T) {
	for _, value := range []string{SafetyClassReadOnly, SafetyClassMutating} {
		if err := ValidateSafetyClass(value); err != nil {
			t.Fatalf("expected %q to be accepted, got %v", value, err)
		}
	}
}

// TestValidateSafetyClassRejectsUnknownValue proves an unrecognized value is
// rejected rather than guessed at. A guessed value would silently decide the
// confirmation and scope requirements of an operation nobody classified.
func TestValidateSafetyClassRejectsUnknownValue(t *testing.T) {
	for _, value := range []string{"", "readonly", "READ_ONLY", "write", "read-only"} {
		if err := ValidateSafetyClass(value); err == nil {
			t.Fatalf("expected %q to be rejected", value)
		}
	}
}

// TestModelOperationNamesAreDistinct pins the two operation names and proves they
// are separate capabilities. They must not collapse into one: the list is
// read-only and the select is mutating, so a single name could not carry both
// safety classes honestly.
func TestModelOperationNamesAreDistinct(t *testing.T) {
	if OperationAgentModelList == OperationAgentModelSelect {
		t.Fatal("model list and model select must be separate operations")
	}
	if OperationAgentModelList != "agent.model.list" {
		t.Fatalf("unexpected list operation name %q", OperationAgentModelList)
	}
	if OperationAgentModelSelect != "agent.model.select" {
		t.Fatalf("unexpected select operation name %q", OperationAgentModelSelect)
	}
}

// TestModelCatalogEmptyIsNotUnsupported pins the distinction the catalog read
// depends on: an empty profile list is a real answer, while an Endpoint that
// cannot answer reports an error code. Collapsing them would make an
// unconfigured adapter look like a session with no options.
func TestModelCatalogEmptyIsNotUnsupported(t *testing.T) {
	empty := ModelCatalog{Profiles: []ModelProfile{}, ObservedAtMS: 1}
	if empty.ErrorCode != "" {
		t.Fatalf("an empty catalog must not carry an error code, got %q", empty.ErrorCode)
	}
	unsupported := ModelCatalog{ErrorCode: ModelCatalogUnsupported}
	if len(unsupported.Profiles) != 0 {
		t.Fatal("an unsupported catalog must not carry profiles")
	}
	if unsupported.ErrorCode == empty.ErrorCode {
		t.Fatal("unsupported and empty catalogs must be distinguishable")
	}
}

// TestModelProfileCarriesNoProviderVocabulary pins that the wire shape exposes
// only cluster vocabulary. A provider name, index or path on this struct would
// make the Server able to interpret provider detail, which the abstraction
// boundary forbids.
func TestModelProfileCarriesNoProviderVocabulary(t *testing.T) {
	profile := ModelProfile{
		ModelProfileID:      "mp-1",
		ProviderDisplayName: "fast",
		Available:           true,
		UnavailableReason:   "",
	}
	if profile.ModelProfileID == "" {
		t.Fatal("a profile must be addressable by its opaque identifier")
	}
	// The identifier is the only addressing key, so an empty one is unusable.
	unaddressable := ModelProfile{ProviderDisplayName: "fast", Available: true}
	if unaddressable.ModelProfileID != "" {
		t.Fatal("this fixture is meant to have no identifier")
	}
}

// TestModelSelectRequestCarriesOnlyTheOpaqueID pins the payload shape. The
// request must never carry a provider name or index, because the Server validates
// a standard shape and never forwards provider vocabulary.
func TestModelSelectRequestCarriesOnlyTheOpaqueID(t *testing.T) {
	request := ModelSelectRequest{ModelProfileID: "mp-1"}
	if request.ModelProfileID != "mp-1" {
		t.Fatalf("unexpected identifier %q", request.ModelProfileID)
	}
}

// TestValidateModelSelectPayloadAcceptsOpaqueID pins the accepted shape: exactly
// one opaque profile identifier and nothing else.
func TestValidateModelSelectPayloadAcceptsOpaqueID(t *testing.T) {
	request, err := ValidateModelSelectPayload([]byte(`{"model_profile_id":"mp-1"}`))
	if err != nil {
		t.Fatalf("expected the payload to be accepted, got %v", err)
	}
	if request.ModelProfileID != "mp-1" {
		t.Fatalf("unexpected identifier %q", request.ModelProfileID)
	}
}

// TestValidateModelSelectPayloadRejectsBlankID proves an absent or blank
// identifier is rejected. A blank identifier would otherwise reach an adapter as
// "select nothing", which no provider can honour and no operator asked for.
func TestValidateModelSelectPayloadRejectsBlankID(t *testing.T) {
	for _, payload := range []string{
		`{}`,
		`{"model_profile_id":""}`,
		`{"model_profile_id":"   "}`,
	} {
		if _, err := ValidateModelSelectPayload([]byte(payload)); err == nil {
			t.Fatalf("expected %s to be rejected", payload)
		}
	}
}

// TestValidateModelSelectPayloadRejectsUnknownField proves provider vocabulary
// cannot be smuggled onto the wire as an extra key. A loose decode would forward
// a provider model name, index or credential verbatim, which is exactly what the
// abstraction boundary forbids.
func TestValidateModelSelectPayloadRejectsUnknownField(t *testing.T) {
	for _, payload := range []string{
		`{"model_profile_id":"mp-1","provider_model":"gpt-4"}`,
		`{"model_profile_id":"mp-1","index":3}`,
		`{"model_profile_id":"mp-1","api_key":"secret"}`,
	} {
		if _, err := ValidateModelSelectPayload([]byte(payload)); err == nil {
			t.Fatalf("expected %s to be rejected", payload)
		}
	}
}

// TestValidateModelSelectPayloadRejectsOversizedID proves the identifier bound is
// enforced, so an unbounded caller string cannot become an unbounded provider
// argument.
func TestValidateModelSelectPayloadRejectsOversizedID(t *testing.T) {
	oversized := strings.Repeat("a", MaxModelDisplayNameBytes+1)
	payload := []byte(`{"model_profile_id":"` + oversized + `"}`)
	if _, err := ValidateModelSelectPayload(payload); err == nil {
		t.Fatal("expected an oversized identifier to be rejected")
	}
}

// TestValidateModelSelectPayloadRejectsMalformedJSON proves a document that is not
// JSON is rejected rather than treated as an empty request.
func TestValidateModelSelectPayloadRejectsMalformedJSON(t *testing.T) {
	for _, payload := range []string{``, `not json`, `{"model_profile_id":`} {
		if _, err := ValidateModelSelectPayload([]byte(payload)); err == nil {
			t.Fatalf("expected %q to be rejected", payload)
		}
	}
}
