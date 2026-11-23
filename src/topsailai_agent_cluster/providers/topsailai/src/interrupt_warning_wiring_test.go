package main

import (
	"context"
	"encoding/json"
	"strings"
	"testing"
)

// interruptRowDocument is one live workspace row whose generation matches the
// request, so the authority check admits the mutation.
const interruptRowDocument = `{"items":[` +
	`{"session_id":"s-1","filename":"20261117162228.2557392.session.stdout","pid":2557392,"process_generation":7,"state":"input","session_name":"demo"}` +
	`],"total":1}`

// TestExecuteAttachesTheHardInterruptWarning proves the warning reaches the
// operation result through the real execute path.
//
// The unit test on interruptWarnings proves the message is produced, and this test
// proves execute actually attaches it. Without this, the helper could be correct
// while nothing called it, which is the failure mode where every link in a chain is
// right and the chain has no consumer: the operator would never see the warning and
// every test would still pass.
func TestExecuteAttachesTheHardInterruptWarning(t *testing.T) {
	runner := &scriptedRunner{t: t, answers: map[string][]runnerAnswer{
		strings.Join([]string{"workspace", "list", "--json", "--local"}, "\x00"):                                  answer(interruptRowDocument),
		strings.Join([]string{"runtime", "control", "hard_interrupt", "-s", "s-1", "-a", "{}", "--json"}, "\x00"): answer(`{"ok":true,"action":"hard_interrupt","delivery_state":"control_acknowledged"}`),
	}}
	provider := newProvider(runner, controlCatalog{}, supportedPlatform, t.TempDir(), "")

	key, err := providerSessionKey(workspaceItem{SessionID: "s-1", ProviderRowKey: "20261117162228.2557392.session.stdout"})
	if err != nil {
		t.Fatal(err)
	}
	result, err := provider.execute(context.Background(), request{
		Function:     functionExecute,
		InvocationID: "inv-1",
		Target: &target{
			ResourceKind:        resourceSession,
			ProviderResourceKey: key,
			ExpectedGeneration:  "7",
		},
		Operation: &namedContract{Name: operationExecutionInterrupt, Version: "v1"},
		Payload:   json.RawMessage(`{"action":"hard_interrupt","message":"not delivered"}`),
	})
	if err != nil {
		t.Fatalf("execute refused a hard interrupt with a message: %v", err)
	}
	if len(result.Warnings) != 1 {
		t.Fatalf("warnings = %v, want exactly one", result.Warnings)
	}
	if !strings.Contains(result.Warnings[0], "not delivered") {
		t.Fatalf("warning %q does not say the message was not delivered", result.Warnings[0])
	}
}

// TestExecuteAttachesNoWarningForASoftInterrupt proves the warning is specific to
// the case that drops text.
//
// A warning on a soft interrupt would tell the operator a message was lost when it
// was delivered, which is worse than silence: it would make a working command look
// degraded.
func TestExecuteAttachesNoWarningForASoftInterrupt(t *testing.T) {
	runner := &scriptedRunner{t: t, answers: map[string][]runnerAnswer{
		strings.Join([]string{"workspace", "list", "--json", "--local"}, "\x00"):                                                     answer(interruptRowDocument),
		strings.Join([]string{"runtime", "control", "soft_interrupt", "-s", "s-1", "-a", `{"message":"wrap up"}`, "--json"}, "\x00"): answer(`{"ok":true,"action":"soft_interrupt","delivery_state":"control_acknowledged"}`),
	}}
	provider := newProvider(runner, controlCatalog{}, supportedPlatform, t.TempDir(), "")

	key, err := providerSessionKey(workspaceItem{SessionID: "s-1", ProviderRowKey: "20261117162228.2557392.session.stdout"})
	if err != nil {
		t.Fatal(err)
	}
	result, err := provider.execute(context.Background(), request{
		Function:     functionExecute,
		InvocationID: "inv-1",
		Target: &target{
			ResourceKind:        resourceSession,
			ProviderResourceKey: key,
			ExpectedGeneration:  "7",
		},
		Operation: &namedContract{Name: operationExecutionInterrupt, Version: "v1"},
		Payload:   json.RawMessage(`{"action":"soft_interrupt","message":"wrap up"}`),
	})
	if err != nil {
		t.Fatalf("execute refused a soft interrupt: %v", err)
	}
	if len(result.Warnings) != 0 {
		t.Fatalf("warnings = %v, want none for a delivered message", result.Warnings)
	}
}
