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

// testControlCatalog is a catalog used by the tests. It is deliberately not the
// shipped example: the tests must prove the adapter follows whatever the catalog
// says, so they use names and commands that appear nowhere in the code.
const testControlCatalog = `{
  "actions": [
    {"name": "probe", "permission": "control", "command": ["runtime", "control", "probe", "-s", "{session}", "-a", "{payload}", "--json"]},
    {"name": "inspect", "permission": "read_output", "command": ["runtime", "control", "inspect", "-s", "{session}", "--json"]},
    {"name": "read_messages", "permission": "read_output", "payload_session_field": "session_id", "command": ["runtime", "control", "read_messages", "-s", "{session}", "-a", "{payload}", "--json"]}
  ]
}`

// newTestControlSet builds a control action set from a document.
func newTestControlSet(t *testing.T, document string) *ControlActionSet {
	t.Helper()
	set, err := ParseControlActionSet([]byte(document))
	if err != nil {
		t.Fatalf("parse control action set: %v", err)
	}
	return set
}

// TestControlActionCapabilitiesComeFromTheCatalog proves the advertised surface
// follows the catalog. Nothing about an action is declared in code, so a catalog
// naming an action the code has never seen must still be advertised.
func TestControlActionCapabilitiesComeFromTheCatalog(t *testing.T) {
	set := newTestControlSet(t, testControlCatalog)
	capabilities := controlActionCapabilities(set)
	if len(capabilities) != 3 {
		t.Fatalf("capabilities = %d, want 3", len(capabilities))
	}
	advertised := make(map[string]protocol.Capability, len(capabilities))
	for _, capability := range capabilities {
		advertised[capability.Name] = capability
	}
	for _, name := range []string{"ctl.probe", "ctl.inspect", "ctl.read_messages"} {
		if _, ok := advertised[name]; !ok {
			t.Fatalf("capability %q is not advertised", name)
		}
	}
	if advertised["ctl.inspect"].RequiredPermission != security.ScopeReadOutput {
		t.Fatalf("inspect permission = %q, want read_output", advertised["ctl.inspect"].RequiredPermission)
	}
	if advertised["ctl.probe"].RequiredPermission != security.ScopeControl {
		t.Fatalf("probe permission = %q, want control", advertised["ctl.probe"].RequiredPermission)
	}
}

// TestControlActionCapabilitiesAreEmptyWithoutACatalog proves the fail-closed
// default: an Endpoint with no catalog advertises no action, so every ctl.
// operation is refused instead of falling back to a compiled-in list.
func TestControlActionCapabilitiesAreEmptyWithoutACatalog(t *testing.T) {
	if capabilities := controlActionCapabilities(nil); len(capabilities) != 0 {
		t.Fatalf("capabilities = %v, want none", capabilities)
	}
	empty := newTestControlSet(t, `{"actions": []}`)
	if capabilities := controlActionCapabilities(empty); len(capabilities) != 0 {
		t.Fatalf("capabilities = %v, want none", capabilities)
	}
}

// TestControlActionArgsUsesTheConfiguredCommand proves the provider argv comes
// from the catalog template rather than a compiled-in switch.
func TestControlActionArgsUsesTheConfiguredCommand(t *testing.T) {
	set := newTestControlSet(t, testControlCatalog)
	args, err := controlActionArgs(set, "ctl.probe", "sess1", []byte(`{"detail":true}`))
	if err != nil {
		t.Fatalf("controlActionArgs: %v", err)
	}
	want := []string{"runtime", "control", "probe", "-s", "sess1", "-a", `{"detail":true}`, "--json"}
	if len(args) != len(want) {
		t.Fatalf("argv = %v, want %v", args, want)
	}
	for index := range want {
		if args[index] != want[index] {
			t.Fatalf("argv[%d] = %q, want %q", index, args[index], want[index])
		}
	}
}

// TestControlActionArgsDefaultsEmptyPayload proves an absent payload becomes the
// empty object the provider expects.
func TestControlActionArgsDefaultsEmptyPayload(t *testing.T) {
	set := newTestControlSet(t, testControlCatalog)
	args, err := controlActionArgs(set, "ctl.probe", "sess1", nil)
	if err != nil {
		t.Fatalf("controlActionArgs: %v", err)
	}
	if args[6] != "{}" {
		t.Fatalf("payload = %q, want {}", args[6])
	}
}

// TestControlActionArgsRejectsUnconfiguredAction proves an action absent from the
// catalog never reaches the provider, even when a caller submits it directly.
func TestControlActionArgsRejectsUnconfiguredAction(t *testing.T) {
	set := newTestControlSet(t, testControlCatalog)
	cases := map[string]string{
		"unknown action":    "ctl.not_a_real_action",
		"missing prefix":    "probe",
		"empty action":      "ctl.",
		"provider raw name": "runtime.control",
	}
	for name, operation := range cases {
		t.Run(name, func(t *testing.T) {
			if _, err := controlActionArgs(set, operation, "sess1", nil); !errors.Is(err, errControlActionUnreviewed) {
				t.Fatalf("error = %v, want errControlActionUnreviewed", err)
			}
		})
	}
}

// TestControlActionArgsRejectsWithoutACatalog proves a nil catalog refuses every
// ctl. operation instead of falling back to a compiled-in list.
func TestControlActionArgsRejectsWithoutACatalog(t *testing.T) {
	if _, err := controlActionArgs(nil, "ctl.probe", "sess1", nil); !errors.Is(err, errControlActionUnreviewed) {
		t.Fatalf("error = %v, want errControlActionUnreviewed", err)
	}
}

// TestControlActionArgsRejectsNonObjectPayload proves a non-object payload is
// refused before any argv is built.
func TestControlActionArgsRejectsNonObjectPayload(t *testing.T) {
	set := newTestControlSet(t, testControlCatalog)
	cases := map[string]string{
		"array":  `["probe"]`,
		"string": `"probe"`,
		"number": `7`,
		"null":   `null`,
		"broken": `{`,
	}
	for name, payload := range cases {
		t.Run(name, func(t *testing.T) {
			if _, err := controlActionArgs(set, "ctl.probe", "sess1", []byte(payload)); err == nil {
				t.Fatalf("payload %q was accepted", payload)
			}
		})
	}
}

// TestControlActionPayloadNormalizesObject proves the payload is re-encoded as a
// JSON object.
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
		ControlActions: newTestControlSet(t, testControlCatalog),
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
	if !errors.Is(err, errControlActionUnreviewed) {
		t.Fatalf("error = %v, want errControlActionUnreviewed", err)
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
		ControlActions: newTestControlSet(t, pinnedCatalog),
		PlatformProbe: func() (PlatformCapabilities, error) {
			return PlatformCapabilities{ProcAvailable: true, PidfdAvailable: true}, nil
		},
	}, runner)
	if err != nil {
		t.Fatal(err)
	}
	intent := controlIntent(t, binding, "ctl.pinned", []byte(`{"instruction":"probe.two"}`))
	result, err := binding.Execute(context.Background(), adapter.ExecuteRequest{Intent: intent})
	if !errors.Is(err, errControlPayloadConflict) {
		t.Fatalf("error = %v, want errControlPayloadConflict", err)
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

// TestProviderControlActionsMatchProviderFallbackRegistry catches drift against
// the provider's own fallback registry. It reads the sibling provider source
// instead of invoking the CLI, so the check is deterministic and needs no live
// provider installation.
//
// The catalog is configuration, so this test does not require the shipped example
// to list every provider action. It instead proves the shipped example only names
// actions the provider actually serves, which is the property that matters: a
// catalog entry the provider cannot execute would fail at the first command.
func TestShippedCatalogNamesOnlyProviderActions(t *testing.T) {
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
	data, err := os.ReadFile(shippedControlActionPath(t))
	if err != nil {
		t.Fatalf("read the shipped catalog: %v", err)
	}
	set, err := ParseControlActionSet(data)
	if err != nil {
		t.Fatalf("parse the shipped catalog: %v", err)
	}
	for _, action := range set.Actions() {
		// A shortcut never reaches the provider under its own name: it runs the
		// argv of the action it names. An entry that pins the instruction field
		// runs call_instruction, so its instruction name is a payload value and
		// not a provider action. The invariant is therefore about the action that
		// actually executes, never about the catalog entry's own name.
		served := action.Name
		if action.AliasOf != "" {
			served = action.AliasOf
		}
		if _, pinned := action.PayloadConstants["instruction"]; pinned {
			served = "call_instruction"
		}
		if !provider[served] {
			t.Errorf("the shipped catalog names %q, which the provider does not serve", served)
		}
	}
}

// TestShippedCatalogPinsOnlyProviderInstructions proves every instruction a
// catalog entry pins is one the provider actually registers. A pinned name is a
// payload value, so a typo would only surface as "unknown instruction" at the
// first command; this check catches it without a live provider.
func TestShippedCatalogPinsOnlyProviderInstructions(t *testing.T) {
	registered := providerInstructionNames(t)
	data, err := os.ReadFile(shippedControlActionPath(t))
	if err != nil {
		t.Fatalf("read the shipped catalog: %v", err)
	}
	set, err := ParseControlActionSet(data)
	if err != nil {
		t.Fatalf("parse the shipped catalog: %v", err)
	}
	for _, action := range set.Actions() {
		instruction, pinned := action.PayloadConstants["instruction"]
		if !pinned {
			continue
		}
		if !registered[instruction] {
			t.Errorf("the shipped catalog pins %q for %q, which the provider does not register", instruction, action.Name)
		}
	}
}

// providerInstructionNames reads the instruction names the provider registers.
//
// A plugin module registers a dict under INSTRUCTIONS, and get_function_map
// prefixes each key with the module name, so git.py's git_status is served as
// git.git_status. The context runtime registers its own dotted names directly.
// Both sources are read from the sibling provider source, so the check needs no
// live provider installation.
func providerInstructionNames(t *testing.T) map[string]bool {
	t.Helper()
	root := filepath.Join("..", "..", "..", "..", "topsailai", "workspace")
	pluginFiles, err := filepath.Glob(filepath.Join(root, "plugin_instruction", "*.py"))
	if err != nil {
		t.Fatalf("list provider plugin instructions: %v", err)
	}
	if len(pluginFiles) == 0 {
		t.Skipf("provider plugin instructions unavailable under %s", root)
	}
	blockPattern := regexp.MustCompile(`(?s)INSTRUCTIONS = (?:dict\(|\{)(.*?)(?:\n\)|\n\})`)
	keyPattern := regexp.MustCompile(`(?m)^\s+"?([a-z_0-9]+)"?\s*[=:]`)
	names := make(map[string]bool)
	for _, file := range pluginFiles {
		content, err := os.ReadFile(file)
		if err != nil {
			t.Fatalf("read %s: %v", file, err)
		}
		block := blockPattern.FindSubmatch(content)
		if block == nil {
			continue
		}
		prefix := strings.TrimSuffix(filepath.Base(file), ".py")
		for _, match := range keyPattern.FindAllSubmatch(block[1], -1) {
			names[prefix+"."+string(match[1])] = true
		}
	}
	contextFile := filepath.Join(root, "context", "instruction.py")
	content, err := os.ReadFile(contextFile)
	if err != nil {
		t.Fatalf("read %s: %v", contextFile, err)
	}
	for _, match := range regexp.MustCompile(`"([a-z_0-9.]+)":`).FindAllStringSubmatch(string(content), -1) {
		names[match[1]] = true
	}
	return names
}
