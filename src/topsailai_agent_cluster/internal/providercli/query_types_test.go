package providercli

import (
	"encoding/json"
	"errors"
	"strings"
	"testing"

	"topsailai_agent_cluster/internal/protocol"
)

func queryContract(name string) NamedContract {
	return NamedContract{Name: name, Version: "v1"}
}

func sessionQueryTarget() *Target {
	return &Target{ResourceKind: ResourceSession, ProviderResourceKey: "session-provider-1"}
}

func TestDecodeQueryPayloadStrictContract(t *testing.T) {
	tests := []struct {
		name    string
		query   string
		target  *Target
		payload string
		match   string
	}{
		{name: "unknown field", query: QueryLaunchOptions, payload: `{"include_projects":true,"cluster_session_id":"forbidden"}`, match: "unknown field"},
		{name: "null", query: QueryLaunchOptions, payload: `null`, match: "must not be null"},
		{name: "wrong target kind", query: QueryModelCatalog, target: &Target{ResourceKind: ResourceTask, ProviderResourceKey: "task-1"}, payload: `{}`, match: "session"},
		{name: "target on endpoint query", query: QueryHistoryMessages, target: sessionQueryTarget(), payload: `{"limit":10}`, match: "must not contain target"},
		{name: "wrong version", query: QueryHistoryMessages, payload: `{"limit":10}`, match: "unregistered"},
	}
	for _, test := range tests {
		t.Run(test.name, func(t *testing.T) {
			contract := queryContract(test.query)
			if test.name == "wrong version" {
				contract.Version = "v2"
			}
			_, err := DecodeQueryPayload(contract, test.target, json.RawMessage(test.payload))
			if err == nil || !strings.Contains(err.Error(), test.match) {
				t.Fatalf("error = %v, want match %q", err, test.match)
			}
		})
	}
}

func TestDecodeQueryResultRejectsInvalidProviderIdentity(t *testing.T) {
	tests := []struct {
		name  string
		query string
		doc   string
		match string
	}{
		{name: "missing key", query: QueryHistoryMessages, doc: `{"rows":[{"resource_kind":"session","provider_session_id":"s1","resumable":true}],"observed_at_ms":1,"truncated":false}`, match: "provider_resource_key"},
		{name: "duplicate key", query: QueryHistoryMessages, doc: `{"rows":[{"resource_kind":"session","provider_resource_key":"same","provider_session_id":"s1","resumable":true},{"resource_kind":"session","provider_resource_key":"same","provider_session_id":"s2","resumable":true}],"observed_at_ms":1,"truncated":false}`, match: "duplicate"},
		{name: "wrong kind", query: QueryModelCatalog, doc: `{"profiles":[{"resource_kind":"task","provider_resource_key":"m1","current_state":"no","available":true}],"observed_at_ms":1,"truncated":false}`, match: "model_profile"},
		{name: "Cluster ID field", query: QueryLaunchOptions, doc: `{"profile":{"resource_kind":"launch_profile","provider_resource_key":"p1","launch_profile_id":"cluster-owned","display_name":"default","revision":"r1"},"projects":[]}`, match: "unknown field"},
		{name: "null collection", query: QueryModelCatalog, doc: `{"profiles":null,"observed_at_ms":1,"truncated":false}`, match: "required"},
	}
	for _, test := range tests {
		t.Run(test.name, func(t *testing.T) {
			_, err := DecodeQueryResult(queryContract(test.query), json.RawMessage(test.doc), protocol.DefaultMaxDetailBytes)
			if err == nil || !strings.Contains(err.Error(), test.match) {
				t.Fatalf("error = %v, want match %q", err, test.match)
			}
		})
	}
}

func TestDecodeQueryResultRejectsUnknownVersion(t *testing.T) {
	_, err := DecodeQueryResult(
		NamedContract{Name: QueryLaunchOptions, Version: "v2"},
		json.RawMessage(`{"profile":{"resource_kind":"launch_profile","provider_resource_key":"p1","display_name":"default","revision":"r1"},"projects":[]}`),
		protocol.DefaultMaxDetailBytes,
	)
	if err == nil || !strings.Contains(err.Error(), "unregistered standard query") {
		t.Fatalf("error = %v, want unregistered standard query", err)
	}
}

// TestDecodeQueryResultRejectsOversizedDetailDocument proves the detail bound is
// a hard rejection rather than a truncation, and that the rejection carries the
// code the Server maps to its own response.
//
// The assertion is on the error code, not only on the message, because the code
// is what the Endpoint forwards and the Server switches on. A message-only
// assertion would stay green while the code silently degraded to the generic
// provider error, which is exactly the defect this test exists to catch.
func TestDecodeQueryResultRejectsOversizedDetailDocument(t *testing.T) {
	const bound = 64
	oversized := strings.Repeat("x", bound+1)
	tests := []struct {
		name string
		doc  string
	}{
		{
			name: "provider_metadata",
			doc:  `{"provider_session_id":"s1","provider_metadata":"` + oversized + `","observed_at_ms":1}`,
		},
		{
			name: "provider_runtime",
			doc:  `{"provider_session_id":"s1","provider_runtime":"` + oversized + `","observed_at_ms":1}`,
		},
	}
	for _, test := range tests {
		t.Run(test.name, func(t *testing.T) {
			_, err := DecodeQueryResult(queryContract(QuerySessionDetail), json.RawMessage(test.doc), bound)
			if err == nil {
				t.Fatalf("oversized %s was accepted, want rejection", test.name)
			}
			var coded interface{ ErrorCode() string }
			if !errors.As(err, &coded) {
				t.Fatalf("error %v carries no code, want %s", err, protocol.DetailResponseTooLarge)
			}
			if coded.ErrorCode() != protocol.DetailResponseTooLarge {
				t.Fatalf("error code = %q, want %q", coded.ErrorCode(), protocol.DetailResponseTooLarge)
			}
		})
	}
}

// TestDecodeQueryResultAcceptsDetailDocumentAtBound proves the bound is
// inclusive, so a document exactly at the configured size is not refused. A
// bound that rejected its own limit would make the configured value mean one
// byte less than the operator set.
func TestDecodeQueryResultAcceptsDetailDocumentAtBound(t *testing.T) {
	const bound = 64
	atBound := strings.Repeat("x", bound)
	doc := `{"provider_session_id":"s1","provider_metadata":"` + atBound + `","observed_at_ms":1}`
	if _, err := DecodeQueryResult(queryContract(QuerySessionDetail), json.RawMessage(doc), bound); err != nil {
		t.Fatalf("document at the bound was refused: %v", err)
	}
}
