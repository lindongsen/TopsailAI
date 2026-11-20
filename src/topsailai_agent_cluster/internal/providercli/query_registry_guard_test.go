package providercli

import (
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"topsailai_agent_cluster/internal/protocol"
)

// querySchemaSuffixes are the two schema documents every registered query owns.
var querySchemaSuffixes = []string{"-request.schema.json", "-result.schema.json"}

// queryFixture is one valid payload and result for a registered query, so the
// decoder can be driven past its switch instead of stopping at the entry check.
type queryFixture struct {
	target  *Target
	payload string
	result  string
}

// queryFixtures holds one valid document pair per registered query. A query that
// is registered but has no fixture here fails the coverage test, which is the
// point: a new registry entry must come with a decodable payload and result.
var queryFixtures = map[string]queryFixture{
	QueryLaunchOptions: {
		payload: `{}`,
		result:  `{"profile":{"resource_kind":"launch_profile","provider_resource_key":"provider-launch","display_name":"default","revision":"launch-r1"}}`,
	},
	QueryHistoryMessages: {
		payload: `{"limit":10}`,
		result:  `{"rows":[],"observed_at_ms":1,"truncated":false}`,
	},
	QueryModelCatalog: {
		target:  &Target{ResourceKind: ResourceSession, ProviderResourceKey: "provider-session"},
		payload: `{}`,
		result:  `{"profiles":[],"observed_at_ms":1,"truncated":false}`,
	},
	QueryProjectCatalog: {
		payload: `{}`,
		result:  `{"projects":[],"observed_at_ms":1,"truncated":false}`,
	},
	QuerySessionMessages: {
		target:  &Target{ResourceKind: ResourceSession, ProviderResourceKey: "provider-session"},
		payload: `{"max_chars":100,"max_tokens":100}`,
		result:  `{"provider_session_id":"provider-session","messages":[],"message_count":0,"observed_at_ms":1,"truncated":false}`,
	},
	QuerySessionMetrics: {
		target:  &Target{ResourceKind: ResourceSession, ProviderResourceKey: "provider-session"},
		payload: `{}`,
		result:  `{"provider_session_id":"provider-session","messages":{"inbound":2,"outbound":68},"observed_at_ms":1}`,
	},
	QuerySessionDetail: {
		target:  &Target{ResourceKind: ResourceSession, ProviderResourceKey: "provider-session"},
		payload: `{}`,
		result:  `{"provider_session_id":"provider-session","provider_metadata":"{\"session_id\":\"provider-session\"}","observed_at_ms":1}`,
	},
	QueryModelRegistry: {
		payload: `{}`,
		result:  `{"entries":[],"current_source":"inherited","observed_at_ms":1,"truncated":false}`,
	},
	QuerySessionMetricsBatch: {
		payload: `{"provider_session_ids":["provider-session"]}`,
		result:  `{"results":[{"provider_session_id":"provider-session","messages":{"inbound":2,"outbound":68},"observed_at_ms":1}],"observed_at_ms":1}`,
	},
}

// querySchemaStem converts a registered query name into the file-name stem its
// schema documents use. The mapping is implicit in the repository layout, so the
// guard derives it from the registry instead of restating a file list.
func querySchemaStem(name string) string {
	return strings.ReplaceAll(name, ".", "-")
}

// TestRegisteredQueriesOwnTheirSchemaDocuments pins the layer the vocabulary test
// does not cover: the registry and the per-query schema files must agree in both
// directions. Adding a query to the registry and to the schema enum while
// forgetting its request or result document leaves the vocabulary test green,
// because that test only compares names.
func TestRegisteredQueriesOwnTheirSchemaDocuments(t *testing.T) {
	directory := schemaDirectory(t)
	registered := make(map[string]struct{})
	for _, query := range StandardQueries() {
		registered[querySchemaStem(query.Name)] = struct{}{}
		for _, suffix := range querySchemaSuffixes {
			name := querySchemaStem(query.Name) + suffix
			if _, err := os.Stat(filepath.Join(directory, name)); err != nil {
				t.Fatalf("registered query %q has no %s, so the registry names a query whose contract is missing", query.Name, name)
			}
		}
	}

	entries, err := os.ReadDir(directory)
	if err != nil {
		t.Fatal(err)
	}
	for _, entry := range entries {
		if entry.IsDir() {
			continue
		}
		for _, suffix := range querySchemaSuffixes {
			if !strings.HasSuffix(entry.Name(), suffix) {
				continue
			}
			stem := strings.TrimSuffix(entry.Name(), suffix)
			if _, ok := registered[stem]; !ok {
				t.Fatalf("%s describes query %q, which the registry does not name, so a schema exists for a query no caller can request", entry.Name(), stem)
			}
		}
	}
}

// TestRegisteredQueriesDecodeThroughTheSwitch pins the other uncovered layer: a
// registered query must be decodable, not merely accepted at the entry check. A
// registry entry without a switch case falls through to "unsupported query",
// which the vocabulary test cannot see.
func TestRegisteredQueriesDecodeThroughTheSwitch(t *testing.T) {
	for _, query := range StandardQueries() {
		fixture, ok := queryFixtures[query.Name]
		if !ok {
			t.Fatalf("registered query %q has no fixture, so this guard cannot prove it decodes", query.Name)
		}
		contract := NamedContract{Name: query.Name, Version: query.Version}
		if _, err := DecodeQueryPayload(contract, fixture.target, json.RawMessage(fixture.payload)); err != nil {
			t.Fatalf("registered query %q payload did not decode: %v", query.Name, err)
		}
		if _, err := DecodeQueryResult(contract, json.RawMessage(fixture.result), protocol.DefaultMaxDetailBytes); err != nil {
			t.Fatalf("registered query %q result did not decode: %v", query.Name, err)
		}
	}
}

// TestUnregisteredQueryIsRejectedBeforeTheSwitch proves the registry is closed at
// the entry rather than after the switch. If the entry check moved behind the
// switch, an unknown name would report "unsupported query" instead of naming the
// registry, and a caller could not tell a typo from a missing implementation.
func TestUnregisteredQueryIsRejectedBeforeTheSwitch(t *testing.T) {
	contract := NamedContract{Name: "future.query", Version: "v1"}
	_, payloadErr := DecodeQueryPayload(contract, nil, json.RawMessage(`{}`))
	if payloadErr == nil || !strings.Contains(payloadErr.Error(), "unregistered standard query") {
		t.Fatalf("payload error = %v, want the registry to reject the name before the switch", payloadErr)
	}
	_, resultErr := DecodeQueryResult(contract, json.RawMessage(`{}`), protocol.DefaultMaxDetailBytes)
	if resultErr == nil || !strings.Contains(resultErr.Error(), "unregistered standard query") {
		t.Fatalf("result error = %v, want the registry to reject the name before the switch", resultErr)
	}
}

// TestRegisteredQueryVersionIsTheQueryContractVersion records that the registry
// version is the query contract version, not the protocol directory name. The
// two currently coincide at v1, so this test states the distinction instead of
// letting the coincidence imply that they are the same field.
func TestRegisteredQueryVersionIsTheQueryContractVersion(t *testing.T) {
	for _, query := range StandardQueries() {
		if query.Version != "v1" {
			t.Fatalf("registered query %q carries version %q, so the registry version is no longer the query contract version this guard documents", query.Name, query.Version)
		}
		if !IsStandardQuery(query.Name, query.Version) {
			t.Fatalf("registered query %q version %q is not recognised by IsStandardQuery", query.Name, query.Version)
		}
		if IsStandardQuery(query.Name, "v2") {
			t.Fatalf("registered query %q accepts version v2, so the version match is not exact", query.Name)
		}
	}
}
