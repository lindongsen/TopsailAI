package topsailai

import (
	"context"
	"encoding/json"
	"errors"
	"os"
	"path/filepath"
	"regexp"
	"strings"
	"testing"

	"topsailai_agent_cluster/internal/adapter"
	"topsailai_agent_cluster/internal/protocol"
	"topsailai_agent_cluster/internal/security"
)

// reviewedControlActionNames is the provider control contract this adapter
// serves. It is written out literally so the test fails when the reviewed list
// silently gains or loses an action.
var reviewedControlActionNames = []string{
	"call_instruction", "clear_interrupt", "clear_pause",
	"get_runtime_messages", "get_session_messages", "hard_interrupt",
	"heartbeat", "llm_control", "pause", "soft_interrupt",
}

// contentControlActions return conversation content, so they must require
// read_output instead of control.
var contentControlActions = map[string]bool{
	"get_runtime_messages": true,
	"get_session_messages": true,
}

func TestProviderControlActionsMatchReviewedContract(t *testing.T) {
	if len(providerControlActions) != len(reviewedControlActionNames) {
		t.Fatalf("reviewed actions = %d, want %d", len(providerControlActions), len(reviewedControlActionNames))
	}
	seen := make(map[string]bool, len(providerControlActions))
	for _, action := range providerControlActions {
		if seen[action.Name] {
			t.Fatalf("duplicate reviewed action %q", action.Name)
		}
		seen[action.Name] = true
	}
	for _, name := range reviewedControlActionNames {
		if !seen[name] {
			t.Fatalf("reviewed action %q is missing", name)
		}
	}
}

func TestProviderControlActionsDeclarePerActionPermission(t *testing.T) {
	for _, action := range providerControlActions {
		want := security.ScopeControl
		if contentControlActions[action.Name] {
			want = security.ScopeReadOutput
		}
		if action.Permission != want {
			t.Fatalf("action %q permission = %q, want %q", action.Name, action.Permission, want)
		}
	}
}

// TestProviderControlActionsMatchProviderFallbackRegistry catches drift against
// the provider's own fallback registry. It reads the sibling provider source
// instead of invoking the CLI, so the check is deterministic and needs no live
// provider installation.
func TestProviderControlActionsMatchProviderFallbackRegistry(t *testing.T) {
	source := filepath.Join("..", "..", "..", "..", "topsailai", "cli", "cli_topsailai", "runtime_cli.py")
	content, err := os.ReadFile(source)
	if err != nil {
		t.Skipf("provider source unavailable: %v", err)
	}
	block := regexp.MustCompile(`(?s)_FALLBACK_CONTROL_ACTIONS = \((.*?)\)`).FindSubmatch(content)
	if block == nil {
		t.Fatalf("provider fallback registry not found in %s", source)
	}
	quoted := regexp.MustCompile(`"([a-z_]+)"`).FindAllStringSubmatch(string(block[1]), -1)
	provider := make(map[string]bool, len(quoted))
	for _, match := range quoted {
		provider[match[1]] = true
	}
	if len(provider) != len(reviewedControlActionNames) {
		t.Fatalf("provider registry = %d actions, reviewed = %d", len(provider), len(reviewedControlActionNames))
	}
	for _, name := range reviewedControlActionNames {
		if !provider[name] {
			t.Fatalf("reviewed action %q is absent from the provider registry", name)
		}
	}
}

func TestDescribeAdvertisesEveryControlAction(t *testing.T) {
	descriptor, err := newTestAdapter(t, &fakeRunner{}).Describe(context.Background())
	if err != nil {
		t.Fatalf("Describe: %v", err)
	}
	advertised := make(map[string]protocol.Capability, len(descriptor.Capabilities.Capabilities))
	for _, capability := range descriptor.Capabilities.Capabilities {
		advertised[capability.Name] = capability
	}
	for _, action := range providerControlActions {
		name := security.ProviderControlPrefix + action.Name
		capability, ok := advertised[name]
		if !ok {
			t.Fatalf("capability %q is not advertised", name)
		}
		if capability.RequiredPermission != action.Permission {
			t.Fatalf("capability %q permission = %q, want %q", name, capability.RequiredPermission, action.Permission)
		}
		if capability.Version != "v1" {
			t.Fatalf("capability %q version = %q, want v1", name, capability.Version)
		}
		if len(capability.TargetKinds) != 1 || capability.TargetKinds[0] != "session" {
			t.Fatalf("capability %q target kinds = %v, want [session]", name, capability.TargetKinds)
		}
	}
}

func TestControlActionArgsBuildsProviderArgv(t *testing.T) {
	args, err := controlActionArgs(nil, "ctl.heartbeat", "sess1", []byte(`{"detail":true}`))
	if err != nil {
		t.Fatalf("controlActionArgs: %v", err)
	}
	want := []string{"runtime", "control", "heartbeat", "-s", "sess1", "-a", `{"detail":true}`, "--json"}
	if len(args) != len(want) {
		t.Fatalf("argv = %v, want %v", args, want)
	}
	for index := range want {
		if args[index] != want[index] {
			t.Fatalf("argv[%d] = %q, want %q", index, args[index], want[index])
		}
	}
}

func TestControlActionArgsDefaultsEmptyPayload(t *testing.T) {
	args, err := controlActionArgs(nil, "ctl.heartbeat", "sess1", nil)
	if err != nil {
		t.Fatalf("controlActionArgs: %v", err)
	}
	if args[6] != "{}" {
		t.Fatalf("payload = %q, want {}", args[6])
	}
}

func TestControlActionArgsRejectsUnreviewedAction(t *testing.T) {
	cases := map[string]string{
		"unknown action":    "ctl.not_a_real_action",
		"missing prefix":    "heartbeat",
		"empty action":      "ctl.",
		"provider raw name": "runtime.control",
	}
	for name, operation := range cases {
		t.Run(name, func(t *testing.T) {
			if _, err := controlActionArgs(nil, operation, "sess1", nil); !errors.Is(err, errControlActionUnreviewed) {
				t.Fatalf("error = %v, want errControlActionUnreviewed", err)
			}
		})
	}
}

func TestControlActionArgsRejectsNonObjectPayload(t *testing.T) {
	cases := map[string]string{
		"array":  `["soft_interrupt"]`,
		"string": `"soft_interrupt"`,
		"number": `7`,
		"null":   `null`,
		"broken": `{`,
	}
	for name, payload := range cases {
		t.Run(name, func(t *testing.T) {
			if _, err := controlActionArgs(nil, "ctl.heartbeat", "sess1", []byte(payload)); err == nil {
				t.Fatalf("payload %q was accepted", payload)
			}
		})
	}
}

func TestControlActionPayloadNormalizesObject(t *testing.T) {
	encoded, err := controlActionPayload([]byte(`{"b":2,"a":1}`))
	if err != nil {
		t.Fatalf("controlActionPayload: %v", err)
	}
	var decoded map[string]int
	if err := json.Unmarshal(encoded, &decoded); err != nil {
		t.Fatalf("decode: %v", err)
	}
	if decoded["a"] != 1 || decoded["b"] != 2 {
		t.Fatalf("decoded = %v", decoded)
	}
}

// controlIntent builds one ctl. intent targeting a mapped session.
func controlIntent(t *testing.T, binding *Adapter, operation string, payload []byte) protocol.ImmutableIntent {
	t.Helper()
	if _, err := binding.mapper.GetOrCreateResourceID(context.Background(), "a1", "sess1", 0); err != nil {
		t.Fatalf("map resource: %v", err)
	}
	return protocol.ImmutableIntent{
		CommandID:        "cmd_ctl",
		Operation:        operation,
		OperationVersion: "v1",
		Target:           &protocol.CommandTarget{Kind: "session", ResourceID: "res_sess1", Generation: "g1"},
		Payload:          payload,
	}
}

func TestExecuteDispatchesControlAction(t *testing.T) {
	runner := &fakeRunner{out: []byte(`{"ok":true,"delivery_state":"acknowledged"}`)}
	binding := newTestAdapter(t, runner)
	intent := controlIntent(t, binding, "ctl.heartbeat", []byte(`{"detail":true}`))
	if _, err := binding.Execute(context.Background(), adapter.ExecuteRequest{Intent: intent}); err != nil {
		t.Fatalf("Execute: %v", err)
	}
	want := []string{"runtime", "control", "heartbeat", "-s", "sess1", "-a", `{"detail":true}`, "--json"}
	if len(runner.args) != len(want) {
		t.Fatalf("argv = %v, want %v", runner.args, want)
	}
	for index := range want {
		if runner.args[index] != want[index] {
			t.Fatalf("argv[%d] = %q, want %q", index, runner.args[index], want[index])
		}
	}
}

func TestExecuteRejectsUnreviewedControlAction(t *testing.T) {
	runner := &fakeRunner{}
	binding := newTestAdapter(t, runner)
	intent := controlIntent(t, binding, "ctl.not_a_real_action", nil)
	result, err := binding.Execute(context.Background(), adapter.ExecuteRequest{Intent: intent})
	if !errors.Is(err, errControlActionUnreviewed) {
		t.Fatalf("error = %v, want errControlActionUnreviewed", err)
	}
	if runner.args != nil {
		t.Fatalf("provider was invoked with %v", runner.args)
	}
	if result.Receipt.ErrorCode != "control_action_unreviewed" {
		t.Fatalf("error code = %q, want control_action_unreviewed", result.Receipt.ErrorCode)
	}
	if result.Receipt.EffectCertainty != protocol.EffectNotApplied {
		t.Fatalf("effect certainty = %q, want not_applied", result.Receipt.EffectCertainty)
	}
}

func TestExecuteStillRejectsUnknownOperation(t *testing.T) {
	runner := &fakeRunner{}
	binding := newTestAdapter(t, runner)
	intent := controlIntent(t, binding, "totally.unknown", nil)
	if _, err := binding.Execute(context.Background(), adapter.ExecuteRequest{Intent: intent}); !errors.Is(err, adapter.ErrUnsupported) {
		t.Fatalf("error = %v, want unsupported", err)
	}
	if runner.args != nil {
		t.Fatalf("provider was invoked with %v", runner.args)
	}
}

// TestControlActionPrefixIsNotConfusedWithInterrupt guards the existing
// interrupt contract: control remains the documented spelling of
// execution.interrupt and must not be re-routed through the ctl. family.
func TestControlActionPrefixIsNotConfusedWithInterrupt(t *testing.T) {
	if strings.HasPrefix("control", security.ProviderControlPrefix) {
		t.Fatal("control must not match the ctl. prefix")
	}
	if strings.HasPrefix(protocol.OperationExecutionInterrupt, security.ProviderControlPrefix) {
		t.Fatal("execution.interrupt must not match the ctl. prefix")
	}
}
