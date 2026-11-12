package providercli

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"reflect"
	"runtime"
	"sort"
	"strings"
	"testing"
)

var requiredSchemaFiles = []string{
	"request.schema.json",
	"response.schema.json",
	"stream-frame.schema.json",
}

func schemaDirectory(t *testing.T) string {
	t.Helper()
	_, source, _, ok := runtime.Caller(0)
	if !ok {
		t.Fatal("locate schema test source")
	}
	return filepath.Join(filepath.Dir(source), "..", "..", "protocol", "provider-cli", "v1")
}

func loadSchema(t *testing.T, name string) map[string]any {
	t.Helper()
	content, err := os.ReadFile(filepath.Join(schemaDirectory(t), name))
	if err != nil {
		t.Fatal(err)
	}
	var schema map[string]any
	if err := json.Unmarshal(content, &schema); err != nil {
		t.Fatalf("parse %s: %v", name, err)
	}
	return schema
}

func TestSchemaInventoryAndMetadata(t *testing.T) {
	entries, err := os.ReadDir(schemaDirectory(t))
	if err != nil {
		t.Fatal(err)
	}
	var actual []string
	for _, entry := range entries {
		if !entry.IsDir() && strings.HasSuffix(entry.Name(), ".schema.json") {
			actual = append(actual, entry.Name())
		}
	}
	sort.Strings(actual)
	expected := append([]string(nil), requiredSchemaFiles...)
	sort.Strings(expected)
	if !reflect.DeepEqual(actual, expected) {
		t.Fatalf("schema inventory = %v, want %v", actual, expected)
	}
	for _, name := range requiredSchemaFiles {
		schema := loadSchema(t, name)
		if schema["$schema"] != "https://json-schema.org/draft/2020-12/schema" {
			t.Errorf("%s has draft %v", name, schema["$schema"])
		}
		identifier, ok := schema["$id"].(string)
		if !ok || !strings.HasPrefix(identifier, "https://") {
			t.Errorf("%s has non-absolute ID %v", name, schema["$id"])
		}
		assertClosedObjects(t, name, schema, "#")
	}
}

func assertClosedObjects(t *testing.T, name string, value any, path string) {
	t.Helper()
	switch node := value.(type) {
	case map[string]any:
		if node["type"] == "object" && node["additionalProperties"] != false {
			t.Errorf("%s %s does not set additionalProperties=false", name, path)
		}
		for key, child := range node {
			assertClosedObjects(t, name, child, path+"/"+key)
		}
	case []any:
		for index, child := range node {
			assertClosedObjects(t, name, child, fmt.Sprintf("%s/%d", path, index))
		}
	}
}

func TestSchemaQueryVocabularyMatchesRegistry(t *testing.T) {
	request := loadSchema(t, "request.schema.json")
	definitions := request["$defs"].(map[string]any)
	query := definitions["standard_query"].(map[string]any)
	properties := query["properties"].(map[string]any)
	name := properties["name"].(map[string]any)
	values := name["enum"].([]any)
	var schemaQueries []string
	for _, value := range values {
		schemaQueries = append(schemaQueries, value.(string))
	}
	var registryQueries []string
	for _, query := range StandardQueries() {
		if query.Version != "v1" {
			t.Fatalf("unexpected registry version %q", query.Version)
		}
		registryQueries = append(registryQueries, query.Name)
	}
	sort.Strings(schemaQueries)
	sort.Strings(registryQueries)
	if !reflect.DeepEqual(schemaQueries, registryQueries) {
		t.Fatalf("schema queries = %v, registry queries = %v", schemaQueries, registryQueries)
	}
}

func TestProviderSchemasExcludeClusterAuthority(t *testing.T) {
	forbidden := []string{
		"cluster_session_id",
		"command_id",
		"command_revision",
		"journal_phase",
		"request_hash",
	}
	for _, name := range requiredSchemaFiles {
		content, err := os.ReadFile(filepath.Join(schemaDirectory(t), name))
		if err != nil {
			t.Fatal(err)
		}
		for _, field := range forbidden {
			if strings.Contains(string(content), `"`+field+`"`) {
				t.Errorf("%s contains Cluster authority field %q", name, field)
			}
		}
	}
}

func TestSchemaCriticalBranches(t *testing.T) {
	request := loadSchema(t, "request.schema.json")
	requestBranches := request["allOf"].([]any)
	execute := requestBranches[0].(map[string]any)["then"].(map[string]any)
	target := execute["properties"].(map[string]any)["target"].(map[string]any)
	if target["$ref"] != "#/$defs/mutation_target" {
		t.Fatalf("execute target schema = %v", target["$ref"])
	}

	response := loadSchema(t, "response.schema.json")
	responseBranches := response["allOf"].([]any)
	if len(responseBranches) != 1 {
		t.Fatalf("response branch count = %d, want 1", len(responseBranches))
	}
	responseBranch := responseBranches[0].(map[string]any)
	success := responseBranch["then"].(map[string]any)
	if len(success["oneOf"].([]any)) != 6 {
		t.Fatalf("success payload branch count = %d, want 6", len(success["oneOf"].([]any)))
	}
	failure := responseBranch["else"].(map[string]any)
	if !reflect.DeepEqual(failure["required"], []any{"error"}) {
		t.Fatalf("failure required fields = %v", failure["required"])
	}

	stream := loadSchema(t, "stream-frame.schema.json")
	if len(stream["oneOf"].([]any)) != 3 {
		t.Fatalf("stream frame branch count = %d, want 3", len(stream["oneOf"].([]any)))
	}
}
