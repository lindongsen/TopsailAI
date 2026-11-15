package providercli

import (
	"encoding/json"
	"strings"
	"testing"
)

// resolveRequest builds one valid resolve request carrying a session identifier.
func resolveRequest(handle string) Request {
	request := validRequest(FunctionResolve)
	request.Payload = json.RawMessage(`{"handle":"` + handle + `"}`)
	return request
}

// TestResolveIsAnAcceptedFunction pins the name in the accepted set. Without this
// assertion a request naming resolve is rejected as an unknown function, and the
// Provider handler that mints the key can never be reached over the wire.
func TestResolveIsAnAcceptedFunction(t *testing.T) {
	if !isFunction(FunctionResolve) {
		t.Fatalf("isFunction(%q) = false, so a resolve request is rejected as unknown", FunctionResolve)
	}
	if err := resolveRequest("session-1").Validate(); err != nil {
		t.Fatalf("valid resolve request rejected: %v", err)
	}
}

// TestResolveRequestCarriesNoClusterAuthority proves a resolve request cannot
// smuggle a target, an invocation or a named contract. The Provider mints the key
// from the identifier alone, so any of those fields would let a caller address a
// resource the Endpoint never mapped.
func TestResolveRequestCarriesNoClusterAuthority(t *testing.T) {
	cases := map[string]func(*Request){
		"target": func(r *Request) {
			r.Target = &Target{ResourceKind: ResourceSession, ProviderResourceKey: "provider-session-1"}
		},
		"invocation_id": func(r *Request) { r.InvocationID = "invocation-1" },
		"operation": func(r *Request) {
			r.Operation = &NamedContract{Name: "message.send", Version: "v1"}
		},
		"query": func(r *Request) {
			r.Query = &NamedContract{Name: QueryModelCatalog, Version: "v1"}
		},
	}
	for name, mutate := range cases {
		t.Run(name, func(t *testing.T) {
			request := resolveRequest("session-1")
			mutate(&request)
			if err := request.Validate(); err == nil {
				t.Fatalf("resolve request carrying %s accepted", name)
			}
		})
	}
}

// TestResolutionResponseValidates proves the resolution document is a legal
// success payload and that a malformed one is rejected. A resolution reports only
// the minted key and the resource kind, so a missing key or an unknown kind must
// fail rather than reach the Endpoint as an addressable identity.
func TestResolutionResponseValidates(t *testing.T) {
	valid := Response{
		Version:    validVersion(),
		RequestID:  "request-1",
		OK:         true,
		Resolution: &ResolutionResult{ProviderResourceKey: "session:v1:abc", ResourceKind: ResourceSession},
	}
	if err := valid.Validate(); err != nil {
		t.Fatalf("valid resolution response rejected: %v", err)
	}

	missingKey := valid
	missingKey.Resolution = &ResolutionResult{ResourceKind: ResourceSession}
	if err := missingKey.Validate(); err == nil || !strings.Contains(err.Error(), "provider_resource_key") {
		t.Fatalf("resolution without a key accepted: %v", err)
	}

	unknownKind := valid
	unknownKind.Resolution = &ResolutionResult{ProviderResourceKey: "session:v1:abc", ResourceKind: "planet"}
	if err := unknownKind.Validate(); err == nil || !strings.Contains(err.Error(), "resource_kind") {
		t.Fatalf("resolution with an unknown kind accepted: %v", err)
	}

	both := valid
	both.Inspection = &InspectionResult{Found: true, Observation: observationPointer()}
	if err := both.Validate(); err == nil {
		t.Fatal("response carrying both inspection and resolution accepted")
	}
}

// observationPointer returns one valid observation for the exclusivity case.
func observationPointer() *ProviderObservation {
	observation := validObservation()
	return &observation
}

// TestResolvePresenceRejectsTarget proves the raw presence layer, which runs before
// the typed decoder, also refuses a target on a resolve request. A field the typed
// layer rejects but the presence layer tolerates would still be read off the wire.
func TestResolvePresenceRejectsTarget(t *testing.T) {
	document := map[string]any{
		"protocol":       ProtocolName,
		"major":          ProtocolMajor,
		"minor":          ProtocolMinor,
		"request_id":     "request-1",
		"function":       FunctionResolve,
		"adapter_id":     "adapter-1",
		"deadline_at_ms": 1000,
		"budget": map[string]any{
			"max_stdout_bytes": 1024,
			"max_stderr_bytes": 1024,
			"max_records":      10,
		},
		"payload": map[string]any{"handle": "session-1"},
		"target": map[string]any{
			"resource_kind":         ResourceSession,
			"provider_resource_key": "provider-session-1",
		},
	}
	encoded, err := json.Marshal(document)
	if err != nil {
		t.Fatal(err)
	}
	if err := validateRequestPresence(encoded); err == nil {
		t.Fatal("resolve request carrying a target passed the presence check")
	}
	delete(document, "target")
	encoded, err = json.Marshal(document)
	if err != nil {
		t.Fatal(err)
	}
	if err := validateRequestPresence(encoded); err != nil {
		t.Fatalf("valid resolve request rejected by the presence check: %v", err)
	}
}
