package providercli

import (
	"sort"
	"testing"

	"topsailai_agent_cluster/internal/protocol"
)

// boundedIdentifierFields are the fields row 38 requires to carry an explicit
// bound. Every occurrence in every schema must declare one, because an unbounded
// identifier is accepted by the contract and then rejected by the implementation,
// which turns a contract violation into a runtime failure the provider cannot
// predict.
var boundedIdentifierFields = []string{
	"adapter_id",
	"resource_kind",
	"provider_resource_key",
	"invocation_id",
	"expected_generation",
}

// canonicalIdentifier is the shape $defs.identifier must declare. maxLength is
// compared against MaxIdentifierBytes rather than against a literal, because a
// hand-copied number is exactly how a bound drifts: raising the constant would
// leave the schema stricter than the code and reject input the code accepts.
var canonicalIdentifierPattern = `^\S(?:.*\S)?$`

// fieldOccurrence is one place a bounded field is declared.
type fieldOccurrence struct {
	document   string
	field      string
	path       string
	definition map[string]any
}

// collectFieldOccurrences walks every schema and returns each declaration of the
// named fields, wherever it appears.
func collectFieldOccurrences(t *testing.T, fields []string) []fieldOccurrence {
	t.Helper()
	wanted := map[string]bool{}
	for _, field := range fields {
		wanted[field] = true
	}
	var occurrences []fieldOccurrence
	for _, document := range requiredSchemaFiles {
		schema := loadSchema(t, document)
		var walk func(node any, path string)
		walk = func(node any, path string) {
			switch typed := node.(type) {
			case map[string]any:
				if properties, ok := typed["properties"].(map[string]any); ok {
					names := make([]string, 0, len(properties))
					for name := range properties {
						names = append(names, name)
					}
					sort.Strings(names)
					for _, name := range names {
						if !wanted[name] {
							continue
						}
						definition, ok := properties[name].(map[string]any)
						if !ok {
							t.Fatalf("%s %s at %s is not an object, so this guard cannot judge its bound", document, name, path)
						}
						occurrences = append(occurrences, fieldOccurrence{
							document:   document,
							field:      name,
							path:       path,
							definition: definition,
						})
					}
				}
				for key, value := range typed {
					walk(value, path+"/"+key)
				}
			case []any:
				for index, item := range typed {
					walk(item, path+"/"+string(rune('0'+index%10)))
				}
			}
		}
		walk(schema, "")
	}
	return occurrences
}

// hasExplicitBound reports whether a declaration constrains its value at all.
func hasExplicitBound(definition map[string]any) bool {
	for _, key := range []string{"$ref", "enum", "const", "maxLength", "pattern"} {
		if _, ok := definition[key]; ok {
			return true
		}
	}
	return false
}

// TestEveryBoundedIdentifierFieldDeclaresABound fails when any occurrence of a
// required field is declared without a bound, because the contract would then
// accept a value the implementation rejects.
func TestEveryBoundedIdentifierFieldDeclaresABound(t *testing.T) {
	occurrences := collectFieldOccurrences(t, boundedIdentifierFields)
	if len(occurrences) == 0 {
		t.Fatal("no occurrence of the required identifier fields was found, so this guard checked nothing")
	}
	seen := map[string]bool{}
	for _, occurrence := range occurrences {
		seen[occurrence.field] = true
		if !hasExplicitBound(occurrence.definition) {
			t.Errorf("%s declares %s at %s without any bound, so the contract accepts a value the implementation rejects",
				occurrence.document, occurrence.field, occurrence.path)
		}
	}
	for _, field := range boundedIdentifierFields {
		if !seen[field] {
			t.Errorf("%s is not declared by any schema, so the bound this row requires cannot be verified", field)
		}
	}
}

// TestIdentifierBoundsMatchCodeConstants ties the schema bound to the constant the
// validator enforces. The comparison is against MaxIdentifierBytes, never against
// a literal, so raising the constant cannot leave the schema silently stricter.
func TestIdentifierBoundsMatchCodeConstants(t *testing.T) {
	checked := 0
	for _, document := range requiredSchemaFiles {
		schema := loadSchema(t, document)
		definitions, ok := schema["$defs"].(map[string]any)
		if !ok {
			continue
		}
		raw, ok := definitions["identifier"]
		if !ok {
			continue
		}
		identifier, ok := raw.(map[string]any)
		if !ok {
			t.Fatalf("%s $defs.identifier is not an object", document)
		}
		checked++
		if identifier["type"] != "string" {
			t.Errorf("%s $defs.identifier must be a string, got %v", document, identifier["type"])
		}
		if identifier["minLength"] != float64(1) {
			t.Errorf("%s $defs.identifier minLength must be 1, got %v", document, identifier["minLength"])
		}
		if identifier["maxLength"] != float64(MaxIdentifierBytes) {
			t.Errorf("%s $defs.identifier maxLength is %v but MaxIdentifierBytes is %d, so the schema and the validator disagree",
				document, identifier["maxLength"], MaxIdentifierBytes)
		}
		if identifier["pattern"] != canonicalIdentifierPattern {
			t.Errorf("%s $defs.identifier pattern is %v, want %q", document, identifier["pattern"], canonicalIdentifierPattern)
		}
	}
	if checked == 0 {
		t.Fatal("no schema declares $defs.identifier, so this guard checked nothing")
	}
}

// TestInlineIdentifierCopiesMatchCanonical fails when a schema that has no $defs
// inlines the identifier shape with a different bound. Those copies cannot use a
// $ref, so they are the ones most likely to drift unnoticed.
func TestInlineIdentifierCopiesMatchCanonical(t *testing.T) {
	occurrences := collectFieldOccurrences(t, boundedIdentifierFields)
	checked := 0
	for _, occurrence := range occurrences {
		if _, ok := occurrence.definition["$ref"]; ok {
			continue
		}
		if _, ok := occurrence.definition["enum"]; ok {
			continue
		}
		if _, ok := occurrence.definition["const"]; ok {
			continue
		}
		checked++
		if occurrence.definition["type"] != "string" {
			t.Errorf("%s inlines %s at %s without type string", occurrence.document, occurrence.field, occurrence.path)
		}
		if occurrence.definition["maxLength"] != float64(MaxIdentifierBytes) {
			t.Errorf("%s inlines %s at %s with maxLength %v but MaxIdentifierBytes is %d",
				occurrence.document, occurrence.field, occurrence.path, occurrence.definition["maxLength"], MaxIdentifierBytes)
		}
		if occurrence.definition["minLength"] != float64(1) {
			t.Errorf("%s inlines %s at %s with minLength %v, want 1",
				occurrence.document, occurrence.field, occurrence.path, occurrence.definition["minLength"])
		}
		if occurrence.definition["pattern"] != canonicalIdentifierPattern {
			t.Errorf("%s inlines %s at %s with pattern %v, want %q",
				occurrence.document, occurrence.field, occurrence.path, occurrence.definition["pattern"], canonicalIdentifierPattern)
		}
	}
	if checked == 0 {
		t.Fatal("no schema inlines an identifier shape, so this guard checked nothing")
	}
}

// TestResourceKindBoundsMatchProtocolVocabulary ties every resource_kind bound to
// the closed vocabulary the validator enforces. A kind added to the protocol but
// missing from the schema would be rejected by the contract and accepted by the
// code, and a kind removed from the protocol but left in the schema would be
// advertised and then refused.
func TestResourceKindBoundsMatchProtocolVocabulary(t *testing.T) {
	occurrences := collectFieldOccurrences(t, []string{"resource_kind"})
	if len(occurrences) == 0 {
		t.Fatal("no schema declares resource_kind, so this guard checked nothing")
	}
	advertised := map[string]bool{}
	for _, occurrence := range occurrences {
		if constant, ok := occurrence.definition["const"].(string); ok {
			if !protocol.IsResourceKind(constant) {
				t.Errorf("%s pins resource_kind to %q at %s, which the protocol vocabulary does not contain",
					occurrence.document, constant, occurrence.path)
			}
			advertised[constant] = true
		}
		values, ok := occurrence.definition["enum"].([]any)
		if !ok {
			continue
		}
		for _, value := range values {
			kind, ok := value.(string)
			if !ok {
				t.Errorf("%s declares a non-string resource_kind at %s", occurrence.document, occurrence.path)
				continue
			}
			if !protocol.IsResourceKind(kind) {
				t.Errorf("%s advertises resource_kind %q at %s, which the protocol vocabulary does not contain",
					occurrence.document, kind, occurrence.path)
			}
			advertised[kind] = true
		}
	}
	for _, kind := range []string{
		protocol.ResourceAgent,
		protocol.ResourceSession,
		protocol.ResourceTask,
		protocol.ResourceLaunchProfile,
		protocol.ResourceModelProfile,
	} {
		if !advertised[kind] {
			t.Errorf("resource_kind %q belongs to the protocol vocabulary but no schema advertises it, so a provider cannot declare it", kind)
		}
	}
}
