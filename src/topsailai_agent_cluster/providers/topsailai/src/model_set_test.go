package main

import (
	"context"
	"encoding/json"
	"strings"
	"testing"
)

// modelSetRequest builds one agent.model.set execute request.
//
// The request carries no target, because the operation declares a machine-wide
// default rather than addressing a resource. A fixture that supplied a target would
// exercise a form the contract forbids and would hide a validator that accepted one.
func modelSetRequest(payload string) request {
	return mutationRequest(operationAgentModelSet, nil, payload)
}

// modelSetPayloadDocument renders one provider-private model key payload.
func modelSetPayloadDocument(id string) string {
	return `{"provider_resource_key":"model:` + id + `"}`
}

// TestModelSetInvokesTheProviderSelectionCommand proves the argv names the provider's
// own selection command with the provider identifier.
//
// The identifier is the provider's `id`, not its display name, because the provider's
// selection file is keyed by the identifier. A fixture whose id equals its name cannot
// express the failure mode, so the identifier here is deliberately different from the
// name the registry would report.
func TestModelSetInvokesTheProviderSelectionCommand(t *testing.T) {
	runner := &scriptedRunner{t: t, answers: map[string][]runnerAnswer{
		"models\x00list\x00--json":            answer(`[{"id":"my-model","name":"My Model","protocol":"openai-compatible","selected":false}]`),
		"models\x00set\x00my-model\x00--json": answer(`{"status":"ok","action":"set","scope":"workspace","model":{"id":"my-model","name":"My Model"}}`),
	}}
	got := fixedProvider(runner).dispatch(context.Background(), modelSetRequest(modelSetPayloadDocument("my-model")))
	if !got.OK {
		t.Fatalf("response = %+v", got)
	}
	if len(runner.calls) != 2 {
		t.Fatalf("calls = %v, want one preflight read and one selection", runner.calls)
	}
	want := []string{"models", "set", "my-model", "--json"}
	if strings.Join(runner.calls[1].args, "\x00") != strings.Join(want, "\x00") {
		t.Fatalf("argv = %v, want %v", runner.calls[1].args, want)
	}
}

// TestModelSetDeclaresTheWorkspaceDefaultOnly proves the argv carries no --project.
//
// The operation declares the machine-wide default, which is the value a launch uses
// when no project override applies. Accepting a folder would let one operation mean
// two different scopes depending on an optional field, and the operator could not tell
// which declaration they had changed.
func TestModelSetDeclaresTheWorkspaceDefaultOnly(t *testing.T) {
	runner := &scriptedRunner{t: t, answers: map[string][]runnerAnswer{
		"models\x00list\x00--json":     answer(`[{"id":"a","name":"A","protocol":"openai-compatible"}]`),
		"models\x00set\x00a\x00--json": answer(`{"status":"ok","action":"set","scope":"workspace"}`),
	}}
	if got := fixedProvider(runner).dispatch(context.Background(), modelSetRequest(modelSetPayloadDocument("a"))); !got.OK {
		t.Fatalf("response = %+v", got)
	}
	for _, argument := range runner.calls[1].args {
		if argument == "--project" {
			t.Fatalf("argv = %v, want no project scope", runner.calls[1].args)
		}
	}
}

// TestModelSetRefusesAnUnknownModelBeforeWriting proves an identifier the registry does
// not contain is refused before the selection command runs.
//
// The refusal must happen before the write, because the provider reports its own
// refusal on stdout with a non-zero exit, and a non-zero exit whose stdout is not a
// JSON document is classified as an unknown effect. Reporting unknown for a selection
// that provably did not happen would send the operator to investigate a write that
// never occurred.
func TestModelSetRefusesAnUnknownModelBeforeWriting(t *testing.T) {
	runner := &scriptedRunner{t: t, answers: map[string][]runnerAnswer{
		"models\x00list\x00--json": answer(`[{"id":"a","name":"A","protocol":"openai-compatible"}]`),
	}}
	got := fixedProvider(runner).dispatch(context.Background(), modelSetRequest(modelSetPayloadDocument("missing")))
	if got.OK || got.Error == nil {
		t.Fatalf("response = %+v, want a refusal", got)
	}
	if got.Error.Code != modelSetUnknownCode {
		t.Fatalf("code = %q, want %q", got.Error.Code, modelSetUnknownCode)
	}
	if len(runner.calls) != 1 {
		t.Fatalf("calls = %v, want only the preflight read", runner.calls)
	}
}

// TestModelSetRefusesADisabledModelBeforeWriting proves an entry the provider would not
// launch with is refused before the selection command runs.
//
// The availability decision is the same one the registry read uses, so the menu an
// operator saw and the refusal they receive cannot disagree about which entries are
// usable. A disabled entry is a different remedy from an unknown one, which is why the
// code differs.
func TestModelSetRefusesADisabledModelBeforeWriting(t *testing.T) {
	runner := &scriptedRunner{t: t, answers: map[string][]runnerAnswer{
		"models\x00list\x00--json": answer(`[{"id":"a","name":"A","protocol":"openai-compatible","enabled":false}]`),
	}}
	got := fixedProvider(runner).dispatch(context.Background(), modelSetRequest(modelSetPayloadDocument("a")))
	if got.OK || got.Error == nil {
		t.Fatalf("response = %+v, want a refusal", got)
	}
	if got.Error.Code != modelSetUnavailableCode {
		t.Fatalf("code = %q, want %q", got.Error.Code, modelSetUnavailableCode)
	}
	if len(runner.calls) != 1 {
		t.Fatalf("calls = %v, want only the preflight read", runner.calls)
	}
}

// TestModelSetRefusesAnUnsupportedProtocolBeforeWriting proves the availability rule is
// the registry's rule rather than a second copy of "is it disabled".
//
// A model whose protocol the provider cannot launch with is unavailable for a different
// reason than a disabled one, and both must be refused. A preflight that checked only
// the enabled flag would admit this entry and let the provider refuse it later, which
// would arrive as an unknown effect.
func TestModelSetRefusesAnUnsupportedProtocolBeforeWriting(t *testing.T) {
	runner := &scriptedRunner{t: t, answers: map[string][]runnerAnswer{
		"models\x00list\x00--json": answer(`[{"id":"a","name":"A","protocol":"anthropic"}]`),
	}}
	got := fixedProvider(runner).dispatch(context.Background(), modelSetRequest(modelSetPayloadDocument("a")))
	if got.OK || got.Error == nil || got.Error.Code != modelSetUnavailableCode {
		t.Fatalf("response = %+v, want an unavailable refusal", got)
	}
	if len(runner.calls) != 1 {
		t.Fatalf("calls = %v, want only the preflight read", runner.calls)
	}
}

// TestModelSetRejectsAKeyWithoutTheProviderPrefix proves a key that is not a provider
// model key is refused before any provider call.
//
// The prefix is what distinguishes a model key from any other provider resource key. A
// payload that carried a session key would otherwise be forwarded as a model
// identifier, and the provider would report an unknown model for a value that was never
// a model at all.
func TestModelSetRejectsAKeyWithoutTheProviderPrefix(t *testing.T) {
	runner := &scriptedRunner{t: t, answers: map[string][]runnerAnswer{}}
	got := fixedProvider(runner).dispatch(context.Background(), modelSetRequest(`{"provider_resource_key":"session:abc"}`))
	if got.OK || got.Error == nil || got.Error.Code != "invalid_request" {
		t.Fatalf("response = %+v, want an invalid_request refusal", got)
	}
	if len(runner.calls) != 0 {
		t.Fatalf("calls = %v, want none", runner.calls)
	}
}

// TestModelSetRejectsATarget proves the operation refuses a target instead of ignoring
// one.
//
// An ignored target would let a session-scoped caller believe the declaration applied
// to their session, while it actually changed the machine default. Refusing is the only
// answer that cannot be misread.
func TestModelSetRejectsATarget(t *testing.T) {
	runner := &scriptedRunner{t: t, answers: map[string][]runnerAnswer{}}
	got := fixedProvider(runner).dispatch(context.Background(), mutationRequest(operationAgentModelSet, sessionTarget(t), modelSetPayloadDocument("a")))
	if got.OK || got.Error == nil || got.Error.Code != "invalid_request" {
		t.Fatalf("response = %+v, want an invalid_request refusal", got)
	}
	if len(runner.calls) != 0 {
		t.Fatalf("calls = %v, want none", runner.calls)
	}
}

// TestModelSetIsAdvertisedAndDispatched proves the operation is both advertised and
// reachable.
//
// The two halves are separate facts: a descriptor can advertise an operation that
// dispatch does not implement, and dispatch can implement one the descriptor never
// advertises. Asserting both here means a missing dispatch case cannot leave the suite
// green while the operation silently answers "unsupported".
func TestModelSetIsAdvertisedAndDispatched(t *testing.T) {
	advertised := false
	for _, contract := range mutationOperations(supportedPlatform) {
		if contract.Name == operationAgentModelSet {
			advertised = true
		}
	}
	if !advertised {
		t.Fatalf("agent.model.set is not advertised")
	}
	runner := &scriptedRunner{t: t, answers: map[string][]runnerAnswer{
		"models\x00list\x00--json":     answer(`[{"id":"a","name":"A","protocol":"openai-compatible"}]`),
		"models\x00set\x00a\x00--json": answer(`{"status":"ok","action":"set","scope":"workspace"}`),
	}}
	if got := fixedProvider(runner).dispatch(context.Background(), modelSetRequest(modelSetPayloadDocument("a"))); !got.OK {
		t.Fatalf("dispatch refused an advertised operation: %+v", got)
	}
}

// TestModelSetIsTargetlessInTheValidator proves the validator and the argv builder agree
// that the operation carries no target.
//
// The rule lives at two sites, and a disagreement is silent in both directions: a
// validator that demanded a target would make the operation unreachable, while an argv
// builder that read one would panic on the nil it was promised.
func TestModelSetIsTargetlessInTheValidator(t *testing.T) {
	if !targetlessMutation(operationAgentModelSet) {
		t.Fatalf("agent.model.set is not registered as target-less")
	}
	if _, err := validateExecuteRequest(modelSetRequest(modelSetPayloadDocument("a")), supportedPlatform); err != nil {
		t.Fatalf("validator refused a target-less agent.model.set: %v", err)
	}
	if _, err := validateExecuteRequest(mutationRequest(operationAgentModelSet, sessionTarget(t), modelSetPayloadDocument("a")), supportedPlatform); err == nil {
		t.Fatalf("validator accepted a target for agent.model.set")
	}
}

// TestModelSetPayloadIsClosed proves the payload rejects an unknown field.
//
// The payload is the only place a caller could smuggle provider vocabulary onto the
// wire, so a loose decode would forward a provider model name or a file path as an
// extra key. The decoder is strict for that reason, and this test is what keeps it
// strict.
func TestModelSetPayloadIsClosed(t *testing.T) {
	runner := &scriptedRunner{t: t, answers: map[string][]runnerAnswer{}}
	got := fixedProvider(runner).dispatch(context.Background(), modelSetRequest(`{"provider_resource_key":"model:a","name":"A"}`))
	if got.OK || got.Error == nil || got.Error.Code != "invalid_request" {
		t.Fatalf("response = %+v, want an invalid_request refusal", got)
	}
	if len(runner.calls) != 0 {
		t.Fatalf("calls = %v, want none", runner.calls)
	}
}

// TestModelSetPayloadDecodesTheIdentifier proves the decoder strips the provider prefix
// and rejects an empty identifier.
func TestModelSetPayloadDecodesTheIdentifier(t *testing.T) {
	id, err := decodeModelSetID(json.RawMessage(modelSetPayloadDocument("my-model")))
	if err != nil {
		t.Fatalf("decodeModelSetID: %v", err)
	}
	if id != "my-model" {
		t.Fatalf("id = %q, want my-model", id)
	}
	if _, err := decodeModelSetID(json.RawMessage(`{"provider_resource_key":"model:"}`)); err == nil {
		t.Fatalf("decoder accepted an empty identifier")
	}
}
