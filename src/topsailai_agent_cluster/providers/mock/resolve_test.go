package main

import (
	"encoding/json"
	"testing"
)

// TestResolveAnswersWithTheHandleItWasGiven pins the mock's resolve contract.
//
// The mock's provider resource key IS the provider session identifier, which is
// what its own observations publish. A digest minted here would give one session
// two identities, so a resume by handle would address a resource discovery never
// reported.
func TestResolveAnswersWithTheHandleItWasGiven(t *testing.T) {
	request := request{
		RequestID: "req-resolve",
		Function:  functionResolve,
		Payload:   json.RawMessage(`{"handle":"session:stable"}`),
	}
	response := handleUnary(request, "", mockOptions{})
	if !response.OK {
		t.Fatalf("resolve rejected: %#v", response.Error)
	}
	if response.Resolution == nil {
		t.Fatal("resolve returned no resolution")
	}
	if response.Resolution.ProviderResourceKey != "session:stable" {
		t.Fatalf("provider_resource_key = %q, want %q", response.Resolution.ProviderResourceKey, "session:stable")
	}
	if response.Resolution.ResourceKind != resourceSession {
		t.Fatalf("resource_kind = %q, want %q", response.Resolution.ResourceKind, resourceSession)
	}
}

// TestResolveDoesNotDecideExistence pins the property that makes resolve useful.
//
// Resolve translates a name the operator already chose. Deciding existence here
// would reject exactly the case the function exists for: a session the Endpoint
// has not discovered yet. A handle the mock has never advertised must therefore
// still resolve.
func TestResolveDoesNotDecideExistence(t *testing.T) {
	request := request{
		RequestID: "req-resolve-unknown",
		Function:  functionResolve,
		Payload:   json.RawMessage(`{"handle":"session:never-discovered"}`),
	}
	response := handleUnary(request, "", mockOptions{})
	if !response.OK {
		t.Fatalf("resolve refused an undiscovered handle: %#v", response.Error)
	}
	if response.Resolution == nil || response.Resolution.ProviderResourceKey != "session:never-discovered" {
		t.Fatalf("resolution = %#v, want the handle verbatim", response.Resolution)
	}
}

// TestResolveRejectsAnEmptyHandle pins the one rejection resolve performs.
func TestResolveRejectsAnEmptyHandle(t *testing.T) {
	for _, payload := range []string{`{"handle":""}`, `{"handle":"   "}`, `{}`} {
		request := request{RequestID: "req-resolve-empty", Function: functionResolve, Payload: json.RawMessage(payload)}
		response := handleUnary(request, "", mockOptions{})
		if response.OK {
			t.Fatalf("payload %s was accepted", payload)
		}
		if response.Error == nil || response.Error.Code != "invalid_request" {
			t.Fatalf("payload %s error = %#v, want invalid_request", payload, response.Error)
		}
	}
}

// TestResolveIsAdvertised pins that the descriptor names the function it serves.
//
// A descriptor that omits a served function hides it from every caller that reads
// the descriptor before calling, so the function would exist and be unreachable.
func TestResolveIsAdvertised(t *testing.T) {
	descriptor := mockDescriptor("")
	found := false
	for _, name := range descriptor.Functions {
		if name == functionResolve {
			found = true
		}
	}
	if !found {
		t.Fatalf("functions = %#v, want %q", descriptor.Functions, functionResolve)
	}
}
