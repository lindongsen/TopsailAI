package topsailai

import (
	"context"
	"errors"
	"testing"

	"topsailai_agent_cluster/internal/adapter"
	"topsailai_agent_cluster/internal/controlaction"
	"topsailai_agent_cluster/internal/protocol"
)

// testControlCatalog mirrors the catalog the controlaction package tests use.
// Go test files are not importable, so the fixture is repeated here rather than
// shared; the two copies must stay in step.
const testControlCatalog = `{
  "actions": [
    {"name": "probe", "permission": "control", "command": ["runtime", "control", "probe", "-s", "{session}", "-a", "{payload}", "--json"]},
    {"name": "inspect", "permission": "read_output", "command": ["runtime", "control", "inspect", "-s", "{session}", "--json"]},
    {"name": "read_messages", "permission": "read_output", "payload_session_field": "session_id", "command": ["runtime", "control", "read_messages", "-s", "{session}", "-a", "{payload}", "--json"]}
  ]
}`

// newDispatchControlSet builds a control action set from a document.
func newDispatchControlSet(t *testing.T, document string) *controlaction.ControlActionSet {
	t.Helper()
	set, err := controlaction.ParseControlActionSet([]byte(document))
	if err != nil {
		t.Fatalf("parse control action set: %v", err)
	}
	return set
}

// controlIntent builds one ctl. intent targeting a mapped session.
func controlIntent(t *testing.T, binding *Adapter, operation string, payload []byte) protocol.ImmutableIntent {
	t.Helper()
	if _, err := binding.mapper.GetOrCreateResourceID(context.Background(), "a1", protocol.ResourceSession, "sess1", 0); err != nil {
		t.Fatalf("map resource: %v", err)
	}
	return protocol.ImmutableIntent{
		CommandID:        "cmd_ctl",
		Operation:        operation,
		OperationVersion: "v1",
		Target:           &protocol.CommandTarget{Kind: "session", ResourceID: "res_sess1", ProviderGeneration: "g1"},
		Payload:          payload,
	}
}

// newControlAdapter builds an adapter whose catalog is the test catalog.
func newControlAdapter(t *testing.T, runner *fakeRunner) *Adapter {
	t.Helper()
	result, err := newWithRunner(Config{
		AdapterID:      "a1",
		Executable:     "/provider",
		MaxOutput:      1024,
		ResourceMapper: newFakeMapper(),
		ControlActions: newDispatchControlSet(t, testControlCatalog),
		PlatformProbe: func() (PlatformCapabilities, error) {
			return PlatformCapabilities{ProcAvailable: true, PidfdAvailable: true}, nil
		},
	}, runner)
	if err != nil {
		t.Fatal(err)
	}
	return result
}

// TestExecuteDispatchesConfiguredControlAction proves Execute runs the configured
// command for a catalog action.
func TestExecuteDispatchesConfiguredControlAction(t *testing.T) {
	runner := &fakeRunner{out: []byte(`{"ok":true,"delivery_state":"acknowledged"}`)}
	binding := newControlAdapter(t, runner)
	intent := controlIntent(t, binding, "ctl.probe", []byte(`{"detail":true}`))
	if _, err := binding.Execute(context.Background(), adapter.ExecuteRequest{Intent: intent}); err != nil {
		t.Fatalf("Execute: %v", err)
	}
	want := []string{"runtime", "control", "probe", "-s", "sess1", "-a", `{"detail":true}`, "--json"}
	if len(runner.args) != len(want) {
		t.Fatalf("argv = %v, want %v", runner.args, want)
	}
	for index := range want {
		if runner.args[index] != want[index] {
			t.Fatalf("argv[%d] = %q, want %q", index, runner.args[index], want[index])
		}
	}
}

// TestExecuteRejectsUnconfiguredControlAction proves an action absent from the
// catalog is refused without invoking the provider.
func TestExecuteRejectsUnconfiguredControlAction(t *testing.T) {
	runner := &fakeRunner{}
	binding := newControlAdapter(t, runner)
	intent := controlIntent(t, binding, "ctl.not_a_real_action", nil)
	result, err := binding.Execute(context.Background(), adapter.ExecuteRequest{Intent: intent})
	if !errors.Is(err, controlaction.ErrControlActionUnreviewed) {
		t.Fatalf("error = %v, want controlaction.ErrControlActionUnreviewed", err)
	}
	if runner.args != nil {
		t.Fatalf("provider was invoked with %v", runner.args)
	}
	if result.Receipt.ErrorCode != "control_action_unconfigured" {
		t.Fatalf("error code = %q, want control_action_unconfigured", result.Receipt.ErrorCode)
	}
	if result.Receipt.EffectCertainty != protocol.EffectNotApplied {
		t.Fatalf("effect certainty = %q, want not_applied", result.Receipt.EffectCertainty)
	}
}

// TestExecuteReportsPayloadConflictSeparately proves a payload that disagrees
// with a value the catalog entry fixes itself is reported as a payload conflict,
// not as an unconfigured action. The two failures need different operator
// responses: one means the catalog is missing an entry, the other means the entry
// exists and the payload is wrong.
func TestExecuteReportsPayloadConflictSeparately(t *testing.T) {
	const pinnedCatalog = `{
  "actions": [
    {"name": "pinned", "permission": "read_output", "payload_constants": {"instruction": "probe.one"}, "command": ["runtime", "control", "call_instruction", "-s", "{session}", "-a", "{payload}", "--json"]}
  ]
}`
	runner := &fakeRunner{}
	binding, err := newWithRunner(Config{
		AdapterID:      "a1",
		Executable:     "/provider",
		MaxOutput:      1024,
		ResourceMapper: newFakeMapper(),
		ControlActions: newDispatchControlSet(t, pinnedCatalog),
		PlatformProbe: func() (PlatformCapabilities, error) {
			return PlatformCapabilities{ProcAvailable: true, PidfdAvailable: true}, nil
		},
	}, runner)
	if err != nil {
		t.Fatal(err)
	}
	intent := controlIntent(t, binding, "ctl.pinned", []byte(`{"instruction":"probe.two"}`))
	result, err := binding.Execute(context.Background(), adapter.ExecuteRequest{Intent: intent})
	if !errors.Is(err, controlaction.ErrPayloadConflict) {
		t.Fatalf("error = %v, want controlaction.ErrPayloadConflict", err)
	}
	if runner.args != nil {
		t.Fatalf("provider was invoked with %v", runner.args)
	}
	if result.Receipt.ErrorCode != "control_payload_conflict" {
		t.Fatalf("error code = %q, want control_payload_conflict", result.Receipt.ErrorCode)
	}
	if result.Receipt.EffectCertainty != protocol.EffectNotApplied {
		t.Fatalf("effect certainty = %q, want not_applied", result.Receipt.EffectCertainty)
	}
}

// TestExecuteStillRejectsUnknownOperation proves a non-ctl operation keeps its
// existing unsupported result.
func TestExecuteStillRejectsUnknownOperation(t *testing.T) {
	runner := &fakeRunner{}
	binding := newControlAdapter(t, runner)
	intent := controlIntent(t, binding, "totally.unknown", nil)
	if _, err := binding.Execute(context.Background(), adapter.ExecuteRequest{Intent: intent}); !errors.Is(err, adapter.ErrUnsupported) {
		t.Fatalf("error = %v, want unsupported", err)
	}
	if runner.args != nil {
		t.Fatalf("provider was invoked with %v", runner.args)
	}
}

func TestDescribeRevisionChangesWithControlActionCatalog(t *testing.T) {
	set := newDispatchControlSet(t, `{"actions":[{"name":"probe","permission":"control","command":["runtime","control","probe"]}]}`)
	instance, err := New(Config{AdapterID: "fixture", Executable: "topsailai", ControlActions: set, PlatformProbe: func() (PlatformCapabilities, error) { return PlatformCapabilities{}, nil }})
	if err != nil {
		t.Fatal(err)
	}
	before, err := instance.Describe(context.Background())
	if err != nil {
		t.Fatal(err)
	}
	if err := set.Reload([]byte(`{"actions":[{"name":"restart","permission":"control","command":["runtime","control","restart"]}]}`)); err != nil {
		t.Fatal(err)
	}
	after, err := instance.Describe(context.Background())
	if err != nil {
		t.Fatal(err)
	}
	if before.Capabilities.Revision == after.Capabilities.Revision {
		t.Fatalf("revision did not change: %q", before.Capabilities.Revision)
	}
}
