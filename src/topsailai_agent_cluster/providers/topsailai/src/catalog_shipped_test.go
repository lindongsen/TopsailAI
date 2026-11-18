package main

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"regexp"
	"strings"
	"testing"
)

// shippedCatalogPath is the catalog the deployment documentation points at.
//
// It is read from the repository so the test fails when the shipped example stops
// being a catalog the Provider can load. The Provider is the component that reads
// this file, so the guard lives here rather than beside the Endpoint.
func shippedCatalogPath(t *testing.T) string {
	t.Helper()
	return clusterPath(t, "conf", "control-actions.conf.example")
}

// loadShippedCatalog reads and parses the shipped example.
func loadShippedCatalog(t *testing.T) controlCatalog {
	t.Helper()
	data, err := os.ReadFile(shippedCatalogPath(t))
	if err != nil {
		t.Fatalf("read the shipped control action catalog: %v", err)
	}
	catalog, err := parseControlCatalog(data)
	if err != nil {
		t.Fatalf("the shipped control action catalog must parse, got %v", err)
	}
	return catalog
}

// TestShippedCatalogParses proves the shipped example is loadable.
//
// The catalog is optional, so an invalid example does not stop a fresh Provider
// from starting; it instead fails the first operator who copies it. That is
// exactly the defect this test exists to prevent.
func TestShippedCatalogParses(t *testing.T) {
	catalog := loadShippedCatalog(t)
	if len(catalog.order) == 0 {
		t.Fatal("the shipped catalog declares no action, so the ctl. family would be disabled")
	}
}

// TestShippedCatalogDocumentsEverySchema proves every example action carries a
// payload schema.
//
// The schema is what the interactive prompt walks. An action without one falls
// back to the generic key=value prompt, so an example that omits it documents an
// action whose fields an operator has to guess.
func TestShippedCatalogDocumentsEverySchema(t *testing.T) {
	catalog := loadShippedCatalog(t)
	for _, name := range catalog.order {
		if catalog.actions[name].PayloadSchema == "" {
			t.Errorf("the shipped catalog omits payload_schema for %q, so the example does not document its fields", name)
		}
	}
}

// TestShippedCatalogDeclaresCommands proves every example action carries the
// provider argv template.
//
// The template is the only way an action reaches the provider, so an example
// without one would document an action that cannot run.
func TestShippedCatalogDeclaresCommands(t *testing.T) {
	catalog := loadShippedCatalog(t)
	for _, name := range catalog.order {
		if len(catalog.actions[name].Command) == 0 {
			t.Errorf("the shipped catalog omits the command for %q", name)
		}
	}
}

// TestShippedCatalogInjectsTheSessionSelector proves the example declares the
// payload field for the action that needs the provider session key in its
// payload, so the operator is never asked for a selector the cluster already
// holds.
func TestShippedCatalogInjectsTheSessionSelector(t *testing.T) {
	catalog := loadShippedCatalog(t)
	action, ok := catalog.actions["get_session_messages"]
	if !ok {
		t.Fatal("the shipped catalog must document get_session_messages")
	}
	if action.PayloadSessionField != "session_id" {
		t.Fatalf("payload_session_field = %q, want session_id", action.PayloadSessionField)
	}
}

// TestShippedCatalogUsesNoShellMetacharacters proves the example templates are
// plain argv arrays.
//
// A template is executed directly, so a token that only makes sense to a shell
// would either fail or, worse, be passed to the provider as literal text.
func TestShippedCatalogUsesNoShellMetacharacters(t *testing.T) {
	catalog := loadShippedCatalog(t)
	for _, name := range catalog.order {
		for _, token := range catalog.actions[name].Command {
			if strings.ContainsAny(token, "|&;<>$`") {
				t.Errorf("action %q command token %q contains a shell metacharacter", name, token)
			}
		}
	}
}

// TestShippedCatalogListsInstructions proves the shipped call_instruction entry
// carries the instruction inventory in its enum, so the guided prompt offers a
// menu instead of a free-text field.
//
// The enum is a prompt convenience rather than an authorization gate, but an
// empty or duplicated list would still make the prompt unusable.
func TestShippedCatalogListsInstructions(t *testing.T) {
	catalog := loadShippedCatalog(t)
	action, ok := catalog.actions["call_instruction"]
	if !ok {
		t.Fatal("the shipped catalog must document call_instruction")
	}
	var schema struct {
		Properties map[string]struct {
			Enum []string `json:"enum"`
		} `json:"properties"`
	}
	if err := json.Unmarshal([]byte(action.PayloadSchema), &schema); err != nil {
		t.Fatalf("decode the call_instruction schema: %v", err)
	}
	instruction, ok := schema.Properties["instruction"]
	if !ok {
		t.Fatal("the call_instruction schema must document the instruction field")
	}
	if len(instruction.Enum) == 0 {
		t.Fatal("the instruction field must list the registered instructions, otherwise the prompt asks for free text")
	}
	seen := make(map[string]bool, len(instruction.Enum))
	for _, name := range instruction.Enum {
		if strings.TrimSpace(name) == "" {
			t.Errorf("the instruction enum contains an empty entry")
		}
		if seen[name] {
			t.Errorf("the instruction enum lists %q more than once", name)
		}
		seen[name] = true
	}
}

// TestShippedCatalogDeclaresNoPermission proves the example leaves authorization
// to the Endpoint.
//
// The permission an action requires is declared on the Endpoint's ADAPTERS
// capability entry, because the Endpoint is the component that enforces it. A
// permission field here would be a second, unread copy of an authorization
// decision, and the copy nobody reads is the one that drifts.
func TestShippedCatalogDeclaresNoPermission(t *testing.T) {
	data, err := os.ReadFile(shippedCatalogPath(t))
	if err != nil {
		t.Fatalf("read the shipped control action catalog: %v", err)
	}
	if strings.Contains(string(data), `"permission"`) {
		t.Fatal("the shipped catalog declares a permission, but the Endpoint owns that decision")
	}
}

// TestShippedCatalogDeclaresNoAlias proves every shortcut is written out as a
// full action.
//
// The Provider has no alias concept, so an alias_of entry would be refused at
// load time. The example must therefore carry the expanded form, and this test
// fails if a shortcut is ever added back in the Endpoint-only shape.
func TestShippedCatalogDeclaresNoAlias(t *testing.T) {
	data, err := os.ReadFile(shippedCatalogPath(t))
	if err != nil {
		t.Fatalf("read the shipped control action catalog: %v", err)
	}
	if strings.Contains(string(data), `"alias_of"`) {
		t.Fatal("the shipped catalog declares an alias, but the Provider has no alias concept")
	}
}

// TestShippedCatalogKeepsShortcutCopiesIdentical proves each shortcut copy is the
// same document as the action it names.
//
// A copy is how a shortcut survives without an alias concept. If a copy drifted
// from its target it would run a different command or advertise a different
// schema under a name an operator expects to mean the target, which is exactly
// the confusion the shortcut exists to avoid.
func TestShippedCatalogKeepsShortcutCopiesIdentical(t *testing.T) {
	catalog := loadShippedCatalog(t)
	pairs := map[string]string{
		"session.messages":         "get_session_messages",
		"session.runtime_messages": "get_runtime_messages",
		"session.heartbeat":        "heartbeat",
		"session.pause":            "pause",
		"session.unpause":          "clear_pause",
		"session.interrupt":        "hard_interrupt",
		"session.soft_interrupt":   "soft_interrupt",
		"session.clear_interrupt":  "clear_interrupt",
		"session.instruction":      "call_instruction",
		"session.llm":              "llm_control",
	}
	for shortcut, target := range pairs {
		copied, ok := catalog.actions[shortcut]
		if !ok {
			t.Errorf("the shipped catalog no longer declares the shortcut %q", shortcut)
			continue
		}
		original, ok := catalog.actions[target]
		if !ok {
			t.Errorf("the shipped catalog no longer declares the target %q", target)
			continue
		}
		if strings.Join(copied.Command, "\x00") != strings.Join(original.Command, "\x00") {
			t.Errorf("shortcut %q runs a different command than %q", shortcut, target)
		}
		if copied.PayloadSchema != original.PayloadSchema {
			t.Errorf("shortcut %q advertises a different schema than %q", shortcut, target)
		}
		if copied.PayloadSessionField != original.PayloadSessionField {
			t.Errorf("shortcut %q declares a different payload_session_field than %q", shortcut, target)
		}
		if len(copied.PayloadConstants) != len(original.PayloadConstants) {
			t.Errorf("shortcut %q declares different payload_constants than %q", shortcut, target)
		}
		for key, value := range original.PayloadConstants {
			if copied.PayloadConstants[key] != value {
				t.Errorf("shortcut %q constant %q = %q, want %q", shortcut, key, copied.PayloadConstants[key], value)
			}
		}
	}
}

// TestShippedCatalogNamesOnlyProviderActions catches drift against the provider's
// own fallback registry.
//
// It reads the sibling provider source instead of invoking the CLI, so the check
// is deterministic and needs no live provider installation. The catalog is
// configuration, so this test does not require the shipped example to list every
// provider action. It instead proves the shipped example only names actions the
// provider actually serves, which is the property that matters: a catalog entry
// the provider cannot execute would fail at the first command.
func TestShippedCatalogNamesOnlyProviderActions(t *testing.T) {
	source := siblingPath(t, "cli", "cli_topsailai", "runtime_cli.py")
	content, err := os.ReadFile(source)
	if err != nil {
		t.Skipf("provider source unavailable: %v", err)
	}
	block := regexp.MustCompile(`(?s)_FALLBACK_CONTROL_ACTIONS = \((.*?)\)`).FindSubmatch(content)
	if block == nil {
		t.Fatalf("provider fallback registry not found in %s", source)
	}
	quoted := regexp.MustCompile(`"([a-z_]+)"`).FindAllStringSubmatch(string(block[1]), -1)
	served := make(map[string]bool, len(quoted))
	for _, match := range quoted {
		served[match[1]] = true
	}
	catalog := loadShippedCatalog(t)
	for _, name := range catalog.order {
		// The invariant is about the action that actually executes, never about
		// the catalog entry's own name: a shortcut copy and a pinned instruction
		// entry both run a provider action whose name differs from their own.
		// The executed action is read from the argv itself, so the check follows
		// what the Provider would run instead of trusting a second field.
		executed, err := providerActionOf(catalog.actions[name].Command)
		if err != nil {
			t.Errorf("action %q: %v", name, err)
			continue
		}
		if !served[executed] {
			t.Errorf("the shipped catalog names %q, which the provider does not serve", executed)
		}
	}
}

// providerActionOf reads the provider action a catalog command runs.
//
// Every shipped template is `runtime control <action> ...`, so the action is the
// third token. Reading it from the argv keeps the check honest: a copy that runs
// a different action is caught even though its own name looks correct.
func providerActionOf(command []string) (string, error) {
	if len(command) < 3 || command[0] != "runtime" || command[1] != "control" {
		return "", fmt.Errorf("command %v is not a runtime control invocation", command)
	}
	return command[2], nil
}

// TestShippedCatalogPinsOnlyProviderInstructions proves every instruction a
// catalog entry pins is one the provider actually registers.
//
// A pinned name is a payload value, so a typo would only surface as "unknown
// instruction" at the first command; this check catches it without a live
// provider.
func TestShippedCatalogPinsOnlyProviderInstructions(t *testing.T) {
	registered := providerInstructionNames(t)
	catalog := loadShippedCatalog(t)
	for _, name := range catalog.order {
		instruction, pinned := catalog.actions[name].PayloadConstants["instruction"]
		if !pinned {
			continue
		}
		if !registered[instruction] {
			t.Errorf("the shipped catalog pins %q for %q, which the provider does not register", instruction, name)
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
	root := siblingPath(t, "workspace")
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
