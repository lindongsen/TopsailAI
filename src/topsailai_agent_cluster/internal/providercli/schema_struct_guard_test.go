package providercli

import (
	"reflect"
	"sort"
	"strings"
	"testing"
)

// schemaStructBinding ties one schema definition to the Go struct that produces
// it. The pair is the whole point of this guard: a schema that sets
// additionalProperties false while omitting a field the struct declares does not
// merely under-document the contract, it rejects a conforming producer, and the
// consumer then loses evidence it depends on. exit_confirmed was exactly that
// case, and it reproduced a known defect where every signal_sent operation stayed
// non-terminal.
type schemaStructBinding struct {
	document   string
	definition string
	value      reflect.Type
}

// schemaStructBindings lists every object definition that mirrors a Go struct.
// A definition that is absent here must appear in schemaDefinitionsWithoutStruct
// with a reason, so a new definition cannot slip past this guard unmapped.
var schemaStructBindings = []schemaStructBinding{
	{"request.schema.json", "budget", reflect.TypeOf(Budget{})},
	{"request.schema.json", "mutation_target", reflect.TypeOf(Target{})},
	{"request.schema.json", "named_contract", reflect.TypeOf(NamedContract{})},
	{"request.schema.json", "target", reflect.TypeOf(Target{})},
	{"response.schema.json", "budget", reflect.TypeOf(Budget{})},
	{"response.schema.json", "concurrency", reflect.TypeOf(ConcurrencyLimits{})},
	{"response.schema.json", "descriptor", reflect.TypeOf(Descriptor{})},
	{"response.schema.json", "discovery", reflect.TypeOf(DiscoveryResult{})},
	{"response.schema.json", "inspection", reflect.TypeOf(InspectionResult{})},
	{"response.schema.json", "named_contract", reflect.TypeOf(NamedContract{})},
	{"response.schema.json", "observation", reflect.TypeOf(ProviderObservation{})},
	{"response.schema.json", "operation_result", reflect.TypeOf(OperationResult{})},
	{"response.schema.json", "output", reflect.TypeOf(OutputSnapshot{})},
	{"response.schema.json", "protocol_range", reflect.TypeOf(ProtocolRange{})},
	{"response.schema.json", "provider_error", reflect.TypeOf(ProviderError{})},
	{"response.schema.json", "resolution", reflect.TypeOf(ResolutionResult{})},
	{"stream-frame.schema.json", "provider_error", reflect.TypeOf(ProviderError{})},
}

// schemaDocumentBindings ties each top-level document to its Go struct. The
// embedded Version is flattened, because the schema declares protocol, major and
// minor as ordinary properties rather than as a nested object.
var schemaDocumentBindings = []schemaStructBinding{
	{"request.schema.json", "", reflect.TypeOf(Request{})},
	{"response.schema.json", "", reflect.TypeOf(Response{})},
	{"stream-frame.schema.json", "", reflect.TypeOf(StreamFrame{})},
	// A per-query result document is a top-level object with no $defs, and it is
	// the document a provider actually produces. It belongs here for the same
	// reason the envelope does: the schema sets additionalProperties false, so a
	// property the schema omits rejects a conforming provider, and a property the
	// struct does not produce advertises a field nothing emits. This binding was
	// missing, so renaming a field in this document passed every test while the
	// contract and the decoder disagreed.
	{"session-detail-result.schema.json", "", reflect.TypeOf(SessionDetailResult{})},
}

// schemaDefinitionsWithoutStruct records the object definitions that deliberately
// have no Go DTO, with the reason. standard_query is the closed query registry:
// StandardQuery carries no json tags because it is never serialised directly, and
// its wire vocabulary is pinned by TestSchemaQueryVocabularyMatchesRegistry.
var schemaDefinitionsWithoutStruct = map[string]string{
	"request.schema.json/standard_query":  "the query registry entry is internal and carries no json tags; TestSchemaQueryVocabularyMatchesRegistry pins its wire vocabulary",
	"response.schema.json/standard_query": "the same registry entry echoed in the response envelope",
}

// TestSchemaDefinitionsMatchGoStructs compares every bound definition against the
// json tags of its struct in both directions, so a field added to a DTO without a
// schema change fails here instead of being silently rejected on the wire.
func TestSchemaDefinitionsMatchGoStructs(t *testing.T) {
	for _, binding := range schemaStructBindings {
		properties := schemaProperties(t, binding)
		fields := structJSONNames(binding.value)
		assertSameFieldSet(t, binding.document+"#/$defs/"+binding.definition, properties, fields)
	}
	for _, binding := range schemaDocumentBindings {
		properties := schemaProperties(t, binding)
		fields := structJSONNames(binding.value)
		assertSameFieldSet(t, binding.document, properties, fields)
	}
}

// TestSchemaDefinitionsAreAllBound fails when a schema gains an object definition
// that this guard does not map, because an unmapped definition is unchecked and
// would let the same omission recur unnoticed.
func TestSchemaDefinitionsAreAllBound(t *testing.T) {
	bound := map[string]bool{}
	for _, binding := range schemaStructBindings {
		bound[binding.document+"/"+binding.definition] = true
	}
	checked := 0
	for _, document := range requiredSchemaFiles {
		schema := loadSchema(t, document)
		definitions, ok := schema["$defs"].(map[string]any)
		if !ok {
			continue
		}
		for name, raw := range definitions {
			definition, ok := raw.(map[string]any)
			if !ok || definition["type"] != "object" {
				continue
			}
			key := document + "/" + name
			if bound[key] {
				checked++
				continue
			}
			if reason, exempt := schemaDefinitionsWithoutStruct[key]; exempt {
				if strings.TrimSpace(reason) == "" {
					t.Fatalf("%s is exempted from the struct comparison without a reason", key)
				}
				checked++
				continue
			}
			t.Fatalf("%s defines an object that no Go struct comparison covers, so a field omitted from it would go unnoticed", key)
		}
	}
	if checked == 0 {
		t.Fatal("no schema object definition was compared against a Go struct, so this guard checked nothing")
	}
}

// schemaProperties returns the property names of one bound definition, or of the
// document root when the binding names no definition.
func schemaProperties(t *testing.T, binding schemaStructBinding) []string {
	t.Helper()
	schema := loadSchema(t, binding.document)
	target := schema
	if binding.definition != "" {
		definitions, ok := schema["$defs"].(map[string]any)
		if !ok {
			t.Fatalf("%s has no $defs, so %s cannot be compared", binding.document, binding.definition)
		}
		definition, ok := definitions[binding.definition].(map[string]any)
		if !ok {
			t.Fatalf("%s has no $defs.%s, so this guard checked nothing", binding.document, binding.definition)
		}
		target = definition
	}
	properties, ok := target["properties"].(map[string]any)
	if !ok {
		t.Fatalf("%s has no properties object, so this guard checked nothing", binding.document)
	}
	names := make([]string, 0, len(properties))
	for name := range properties {
		names = append(names, name)
	}
	sort.Strings(names)
	return names
}

// structJSONNames returns the wire names of a struct, flattening embedded structs
// so the embedded Version contributes protocol, major and minor as the schema
// declares them.
func structJSONNames(value reflect.Type) []string {
	var names []string
	for index := 0; index < value.NumField(); index++ {
		field := value.Field(index)
		if field.Anonymous && field.Type.Kind() == reflect.Struct {
			names = append(names, structJSONNames(field.Type)...)
			continue
		}
		if !field.IsExported() {
			continue
		}
		name := strings.Split(field.Tag.Get("json"), ",")[0]
		if name == "-" {
			continue
		}
		if name == "" {
			name = field.Name
		}
		names = append(names, name)
	}
	sort.Strings(names)
	return names
}

// assertSameFieldSet reports both directions of a mismatch, because a field the
// schema omits and a field the struct omits are different defects with different
// fixes.
func assertSameFieldSet(t *testing.T, label string, schemaFields, structFields []string) {
	t.Helper()
	if len(schemaFields) == 0 || len(structFields) == 0 {
		t.Fatalf("%s compared an empty field set (schema=%v struct=%v), so this guard checked nothing", label, schemaFields, structFields)
	}
	schemaSet := map[string]bool{}
	for _, name := range schemaFields {
		schemaSet[name] = true
	}
	structSet := map[string]bool{}
	for _, name := range structFields {
		structSet[name] = true
	}
	var schemaOnly, structOnly []string
	for _, name := range schemaFields {
		if !structSet[name] {
			schemaOnly = append(schemaOnly, name)
		}
	}
	for _, name := range structFields {
		if !schemaSet[name] {
			structOnly = append(structOnly, name)
		}
	}
	if len(structOnly) > 0 {
		t.Errorf("%s omits %v, which the Go struct declares, so a conforming producer must drop the field and the consumer loses it", label, structOnly)
	}
	if len(schemaOnly) > 0 {
		t.Errorf("%s declares %v, which the Go struct does not produce, so the contract advertises a field nothing emits", label, schemaOnly)
	}
}

// survivalFieldMarkers are the substrings that would indicate a schema field
// claiming a process outlives the Provider CLI. The protocol cannot carry such a
// claim: custody survival is a provider-runtime property, so a field here would
// advertise evidence no Provider can produce.
var survivalFieldMarkers = []string{"surviv", "durab", "liveness", "alive", "outliv", "persist"}

// TestOperationResultDeclaresNoSurvivalField pins the boundary that keeps the
// live custody smoke open. operation_result is the only place a Provider could
// report custody survival, and it must stay closed: additionalProperties false
// plus a fixed property set means a Provider cannot smuggle a survival claim past
// the contract, and a future field cannot be added without this guard failing.
func TestOperationResultDeclaresNoSurvivalField(t *testing.T) {
	schema := loadSchema(t, "response.schema.json")
	definitions, ok := schema["$defs"].(map[string]any)
	if !ok {
		t.Fatal("response.schema.json has no $defs, so this guard checked nothing")
	}
	definition, ok := definitions["operation_result"].(map[string]any)
	if !ok {
		t.Fatal("response.schema.json has no $defs.operation_result, so this guard checked nothing")
	}
	if definition["additionalProperties"] != false {
		t.Fatalf("operation_result additionalProperties = %v, want false, so an undeclared survival field would be accepted", definition["additionalProperties"])
	}
	properties, ok := definition["properties"].(map[string]any)
	if !ok || len(properties) == 0 {
		t.Fatal("operation_result has no properties, so this guard checked nothing")
	}
	want := []string{
		"delivery_boundary",
		"effect_certainty",
		"exit_confirmed",
		"finished_at_ms",
		"provider_outcome",
		"provider_request_ref",
		"provider_response",
		"provider_response_truncated",
		"started_at_ms",
	}
	actual := make([]string, 0, len(properties))
	for name := range properties {
		actual = append(actual, name)
	}
	sort.Strings(actual)
	if !reflect.DeepEqual(actual, want) {
		t.Fatalf("operation_result properties = %v, want %v", actual, want)
	}
	for _, name := range actual {
		lowered := strings.ToLower(name)
		for _, marker := range survivalFieldMarkers {
			if strings.Contains(lowered, marker) {
				t.Fatalf("operation_result declares %q, which claims a custody property the protocol cannot carry", name)
			}
		}
	}
}
