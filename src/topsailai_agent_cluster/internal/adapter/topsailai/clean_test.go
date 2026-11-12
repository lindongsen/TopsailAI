package topsailai

import (
	"context"
	"errors"
	"reflect"
	"testing"

	"topsailai_agent_cluster/internal/adapter"
	"topsailai_agent_cluster/internal/protocol"
)

// TestWorkspaceCleanCapabilityDeclaresMutatingControl proves cleanup is
// advertised as a destructive standard operation instead of inheriting a
// provider-private safety or permission label.
func TestWorkspaceCleanCapabilityDeclaresMutatingControl(t *testing.T) {
	descriptor, err := newTestAdapter(t, &fakeRunner{}).Describe(context.Background())
	if err != nil {
		t.Fatal(err)
	}
	for _, capability := range descriptor.Capabilities.Capabilities {
		if capability.Name != protocol.OperationWorkspaceClean {
			continue
		}
		if capability.SafetyClass != protocol.SafetyClassMutating {
			t.Fatalf("safety class = %q, want mutating", capability.SafetyClass)
		}
		if capability.RequiredPermission != "control" {
			t.Fatalf("permission = %q, want control", capability.RequiredPermission)
		}
		if !reflect.DeepEqual(capability.TargetKinds, []string{"session"}) {
			t.Fatalf("target kinds = %#v, want session", capability.TargetKinds)
		}
		return
	}
	t.Fatal("workspace.clean capability is missing")
}

// TestExecuteWorkspaceCleanUsesExactSessionAndPID proves the adapter decodes
// the private row mapping and sends both selectors. The provider command is
// authorized non-interactively only after the cluster has already confirmed it.
func TestExecuteWorkspaceCleanUsesExactSessionAndPID(t *testing.T) {
	runner := &fakeRunner{out: []byte(`{"items":[{"session_id":"shared","filename":"member.stdout","pid":202,"process_generation":null}]}`)}
	a := newTestAdapter(t, runner)
	discovered, err := a.Discover(context.Background(), adapter.DiscoverRequest{})
	if err != nil {
		t.Fatal(err)
	}
	if len(discovered.Sessions) != 1 {
		t.Fatalf("sessions = %#v, want one", discovered.Sessions)
	}
	runner.out = []byte(`{"ok":true,"exit_code":0,"delivery_state":"deleted","response":{"deleted_count":1}}`)
	result, err := a.Execute(context.Background(), adapter.ExecuteRequest{Intent: protocol.ImmutableIntent{
		CommandID: "clean-1",
		Operation: protocol.OperationWorkspaceClean,
		Target:    &protocol.CommandTarget{ResourceID: discovered.Sessions[0].ClusterSessionID},
	}})
	if err != nil {
		t.Fatalf("execute: %v", err)
	}
	want := []string{"workspace", "clean", "-s", "shared", "-p", "202", "--yes", "--json"}
	if !reflect.DeepEqual(runner.args, want) {
		t.Fatalf("argv = %#v, want %#v", runner.args, want)
	}
	if result.Receipt.Outcome != "succeeded" || result.Receipt.EffectCertainty != protocol.EffectAcknowledged {
		t.Fatalf("receipt = %#v, want acknowledged success", result.Receipt)
	}
	if result.Receipt.ProviderResponse != string(runner.out) {
		t.Fatalf("provider response = %q, want opaque provider document", result.Receipt.ProviderResponse)
	}
}

// TestExecuteWorkspaceCleanRejectsIncompletePrivateSelectors proves no invalid
// durable mapping reaches the provider and no session-only fallback is tried.
func TestExecuteWorkspaceCleanRejectsIncompletePrivateSelectors(t *testing.T) {
	cases := []struct {
		name   string
		target providerSessionTarget
	}{
		{name: "missing session", target: providerSessionTarget{PID: 202}},
		{name: "missing pid", target: providerSessionTarget{SessionID: "shared"}},
		{name: "negative pid", target: providerSessionTarget{SessionID: "shared", PID: -1}},
	}
	for _, testCase := range cases {
		t.Run(testCase.name, func(t *testing.T) {
			runner := &fakeRunner{out: []byte(`{"delivery_state":"deleted"}`)}
			mapper := newFakeMapper()
			key, err := providerSessionKey(workspaceItem{SessionID: testCase.target.SessionID, PID: testCase.target.PID})
			if err != nil {
				t.Fatal(err)
			}
			mapping := ResourceMapping{AdapterID: "a1", ProviderKey: key, ResourceID: "res-clean"}
			mapper.byID[mapping.ResourceID] = mapping
			a, err := newWithRunner(Config{AdapterID: "a1", Executable: "/provider", MaxOutput: 1024, ResourceMapper: mapper}, runner)
			if err != nil {
				t.Fatal(err)
			}
			result, err := a.Execute(context.Background(), adapter.ExecuteRequest{Intent: protocol.ImmutableIntent{
				CommandID: "clean-invalid", Operation: protocol.OperationWorkspaceClean,
				Target: &protocol.CommandTarget{ResourceID: mapping.ResourceID},
			}})
			if err == nil {
				t.Fatal("incomplete selector was accepted")
			}
			if runner.args != nil {
				t.Fatalf("provider was invoked with %#v", runner.args)
			}
			if result.Receipt.EffectCertainty != protocol.EffectNotApplied {
				t.Fatalf("effect certainty = %q, want not_applied", result.Receipt.EffectCertainty)
			}
		})
	}
}

// TestExecuteWorkspaceCleanPreservesProviderOutcomes proves provider cleanup
// detail remains opaque while generic effect evidence accurately distinguishes
// a completed or empty cleanup, a partial mutation, and a pre-execution failure.
func TestExecuteWorkspaceCleanPreservesProviderOutcomes(t *testing.T) {
	cases := []struct {
		name          string
		document      string
		runErr        error
		wantOutcome   string
		wantCertainty protocol.EffectCertainty
		wantCode      string
	}{
		{name: "deleted", document: `{"ok":true,"delivery_state":"deleted","response":{"deleted_count":1}}`, wantOutcome: "succeeded", wantCertainty: protocol.EffectAcknowledged},
		{name: "nothing to delete", document: `{"ok":true,"delivery_state":"nothing_to_delete","response":{"deleted_count":0}}`, wantOutcome: "succeeded", wantCertainty: protocol.EffectAcknowledged},
		{name: "partial", document: `{"ok":false,"delivery_state":"partial","error_code":"delete_failed","response":{"deleted_count":1,"failed_count":1}}`, runErr: errors.New("provider exited 1"), wantOutcome: "partial", wantCertainty: protocol.EffectAcknowledged, wantCode: "delete_failed"},
		{name: "inspection failure", document: `{"ok":false,"delivery_state":"not_delivered","error_code":"inspection_failed","message":"permission denied"}`, runErr: errors.New("provider exited 1"), wantOutcome: "failed", wantCertainty: protocol.EffectNotApplied, wantCode: "inspection_failed"},
	}
	for _, testCase := range cases {
		t.Run(testCase.name, func(t *testing.T) {
			runner := &fakeRunner{out: []byte(`{"items":[{"session_id":"shared","pid":202}]}`)}
			a := newTestAdapter(t, runner)
			discovered, err := a.Discover(context.Background(), adapter.DiscoverRequest{})
			if err != nil {
				t.Fatal(err)
			}
			runner.out = []byte(testCase.document)
			runner.err = testCase.runErr
			result, err := a.Execute(context.Background(), adapter.ExecuteRequest{Intent: protocol.ImmutableIntent{
				CommandID: "clean-outcome", Operation: protocol.OperationWorkspaceClean,
				Target: &protocol.CommandTarget{ResourceID: discovered.Sessions[0].ClusterSessionID},
			}})
			if testCase.runErr == nil && err != nil {
				t.Fatalf("execute: %v", err)
			}
			if testCase.runErr != nil && err == nil {
				t.Fatal("provider failure did not propagate")
			}
			if result.Receipt.Outcome != testCase.wantOutcome || result.Receipt.EffectCertainty != testCase.wantCertainty || result.Receipt.ErrorCode != testCase.wantCode {
				t.Fatalf("receipt = %#v", result.Receipt)
			}
			if result.Receipt.ProviderResponse != testCase.document {
				t.Fatalf("provider response = %q, want %q", result.Receipt.ProviderResponse, testCase.document)
			}
		})
	}
}
