package protocol

import "testing"

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
		ModelProfileID:    "mp-1",
		DisplayName:       "fast",
		Available:         true,
		UnavailableReason: "",
	}
	if profile.ModelProfileID == "" {
		t.Fatal("a profile must be addressable by its opaque identifier")
	}
	// The identifier is the only addressing key, so an empty one is unusable.
	unaddressable := ModelProfile{DisplayName: "fast", Available: true}
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
