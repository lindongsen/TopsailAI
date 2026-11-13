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

	"topsailai_agent_cluster/internal/protocol"
)

var requiredSchemaFiles = []string{
	"request.schema.json",
	"response.schema.json",
	"stream-frame.schema.json",
	"launch-options-request.schema.json",
	"launch-options-result.schema.json",
	"history-messages-request.schema.json",
	"history-messages-result.schema.json",
	"model-catalog-request.schema.json",
	"model-catalog-result.schema.json",
	"session-messages-request.schema.json",
	"session-messages-result.schema.json",
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

func TestSchemaGenerationExceptionsMatchValidation(t *testing.T) {
	request := loadSchema(t, "request.schema.json")
	branches := request["allOf"].([]any)
	if len(branches) < 2 {
		t.Fatalf("request branch count = %d, want at least 2", len(branches))
	}
	generationBranch := branches[1].(map[string]any)
	condition := generationBranch["if"].(map[string]any)
	properties := condition["properties"].(map[string]any)
	operation := properties["operation"].(map[string]any)
	operationProperties := operation["properties"].(map[string]any)
	name := operationProperties["name"].(map[string]any)
	not := name["not"].(map[string]any)
	values := not["enum"].([]any)

	var schemaExceptions []string
	for _, value := range values {
		schemaExceptions = append(schemaExceptions, value.(string))
	}
	goExceptions := append([]string(nil), nonLiveAuthorityOperations[:]...)
	sort.Strings(schemaExceptions)
	sort.Strings(goExceptions)
	if !reflect.DeepEqual(schemaExceptions, goExceptions) {
		t.Fatalf("schema generation exceptions = %v, Go exceptions = %v", schemaExceptions, goExceptions)
	}
	for _, operation := range goExceptions {
		if operationNeedsLiveGeneration(operation) {
			t.Errorf("frozen exception %q requires generation", operation)
		}
	}
	for _, operation := range []string{protocol.OperationAgentStart, "future.mutation"} {
		if !operationNeedsLiveGeneration(operation) {
			t.Errorf("generation-required operation %q was treated as an exception", operation)
		}
	}

	then := generationBranch["then"].(map[string]any)
	target := then["properties"].(map[string]any)["target"].(map[string]any)
	if !reflect.DeepEqual(target["required"], []any{"expected_generation"}) {
		t.Fatalf("generation branch target requirement = %v", target["required"])
	}
	definitions := request["$defs"].(map[string]any)
	mutationTarget := definitions["mutation_target"].(map[string]any)
	if !reflect.DeepEqual(mutationTarget["required"], []any{"resource_kind", "provider_resource_key"}) {
		t.Fatalf("mutation target required fields = %v", mutationTarget["required"])
	}

	exceptionSet := make(map[string]struct{}, len(schemaExceptions))
	for _, operation := range schemaExceptions {
		exceptionSet[operation] = struct{}{}
	}
	tests := []struct {
		name               string
		operation          string
		expectedGeneration string
		wantValid          bool
	}{
		{name: "exception omits generation", operation: protocol.OperationAgentResume, wantValid: true},
		{name: "non-exception omits generation", operation: protocol.OperationMessageSend, wantValid: false},
		{name: "unknown omits generation", operation: "future.mutation", wantValid: false},
		{name: "exception supplies generation", operation: protocol.OperationAgentResume, expectedGeneration: "generation-1", wantValid: true},
	}
	for _, test := range tests {
		t.Run(test.name, func(t *testing.T) {
			_, exception := exceptionSet[test.operation]
			requiresGeneration := !exception
			valid := !requiresGeneration || test.expectedGeneration != ""
			if valid != test.wantValid {
				t.Fatalf("schema operation %q generation %q valid = %t, want %t", test.operation, test.expectedGeneration, valid, test.wantValid)
			}
		})
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

func TestTypedQuerySchemasUseEnvelopeCorrelation(t *testing.T) {
	request := loadSchema(t, "request.schema.json")
	encodedRequest, err := json.Marshal(request)
	if err != nil {
		t.Fatal(err)
	}
	for _, stem := range []string{"launch-options", "history-messages", "model-catalog", "session-messages"} {
		ref := stem + "-request.schema.json"
		if !strings.Contains(string(encodedRequest), `"$ref":"`+ref+`"`) {
			t.Errorf("request envelope does not reference %s", ref)
		}
		result := loadSchema(t, stem+"-result.schema.json")
		properties := result["properties"].(map[string]any)
		if _, ok := properties["query"]; ok {
			t.Errorf("%s result duplicates envelope query", stem)
		}
		if _, ok := properties["version"]; ok {
			t.Errorf("%s result duplicates envelope version", stem)
		}
	}
}
