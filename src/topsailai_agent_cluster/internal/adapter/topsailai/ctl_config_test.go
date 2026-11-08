package topsailai

import (
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

// minimalCatalog is the smallest catalog that enables one action.
const minimalCatalog = `{
  "actions": [
    {"name": "probe", "permission": "control", "command": ["runtime", "control", "probe", "-s", "{session}", "-a", "{payload}", "--json"]}
  ]
}`

// TestParseControlActionSetAcceptsACatalog proves a well-formed catalog loads and
// keeps its fields.
func TestParseControlActionSetAcceptsACatalog(t *testing.T) {
	set := newTestControlSet(t, minimalCatalog)
	if set.Len() != 1 {
		t.Fatalf("actions = %d, want 1", set.Len())
	}
	action, ok := set.Get("probe")
	if !ok {
		t.Fatal("probe is not enabled")
	}
	if action.Permission != "control" {
		t.Fatalf("permission = %q, want control", action.Permission)
	}
	if len(action.Command) != 8 {
		t.Fatalf("command = %v, want 8 tokens", action.Command)
	}
}

// TestParseControlActionSetAcceptsAnyName proves the action name is configuration,
// not a compiled-in list. A name the code has never seen must load, because the
// catalog is the only source of actions.
func TestParseControlActionSetAcceptsAnyName(t *testing.T) {
	document := `{"actions": [{"name": "brand_new_action", "permission": "control", "command": ["runtime", "control", "brand_new_action", "--json"]}]}`
	set := newTestControlSet(t, document)
	if _, ok := set.Get("brand_new_action"); !ok {
		t.Fatal("a catalog name the code has never seen must be accepted")
	}
}

// TestParseControlActionSetAcceptsADottedName proves a dotted name stays one
// action. The operation is split only on the ctl. prefix, so a dotted name is not
// reinterpreted as a nested path.
func TestParseControlActionSetAcceptsADottedName(t *testing.T) {
	document := `{"actions": [{"name": "pause.request", "permission": "control", "command": ["runtime", "control", "pause", "--json"]}]}`
	set := newTestControlSet(t, document)
	if _, ok := set.Get("pause.request"); !ok {
		t.Fatal("a dotted name must stay one action")
	}
}

// TestParseControlActionSetRejectsAnEmptyName proves a nameless action is refused,
// because it would advertise the bare ctl. operation.
func TestParseControlActionSetRejectsAnEmptyName(t *testing.T) {
	document := `{"actions": [{"name": "", "permission": "control", "command": ["runtime", "control", "x", "--json"]}]}`
	if _, err := ParseControlActionSet([]byte(document)); err == nil {
		t.Fatal("an empty name was accepted")
	}
}

// TestParseControlActionSetRejectsWhitespaceInName proves a name with whitespace is
// refused, because it would produce an operation that cannot be addressed.
func TestParseControlActionSetRejectsWhitespaceInName(t *testing.T) {
	document := `{"actions": [{"name": "two words", "permission": "control", "command": ["runtime", "control", "x", "--json"]}]}`
	if _, err := ParseControlActionSet([]byte(document)); err == nil {
		t.Fatal("a name with whitespace was accepted")
	}
}

// TestParseControlActionSetRejectsRepeatedPrefix proves a name that repeats the
// ctl. prefix is refused, because the operation would read ctl.ctl.x.
func TestParseControlActionSetRejectsRepeatedPrefix(t *testing.T) {
	document := `{"actions": [{"name": "ctl.probe", "permission": "control", "command": ["runtime", "control", "x", "--json"]}]}`
	if _, err := ParseControlActionSet([]byte(document)); err == nil {
		t.Fatal("a name repeating the ctl. prefix was accepted")
	}
}

// TestParseControlActionSetRejectsUnknownScope proves the permission vocabulary is
// closed. A catalog may not invent a scope no credential can hold.
func TestParseControlActionSetRejectsUnknownScope(t *testing.T) {
	document := `{"actions": [{"name": "probe", "permission": "superuser", "command": ["runtime", "control", "x", "--json"]}]}`
	if _, err := ParseControlActionSet([]byte(document)); err == nil {
		t.Fatal("an undefined scope was accepted")
	}
}

// TestParseControlActionSetRejectsMissingPermission proves a permission is
// required, because an action without one would be unreachable.
func TestParseControlActionSetRejectsMissingPermission(t *testing.T) {
	document := `{"actions": [{"name": "probe", "command": ["runtime", "control", "x", "--json"]}]}`
	if _, err := ParseControlActionSet([]byte(document)); err == nil {
		t.Fatal("a missing permission was accepted")
	}
}

// TestParseControlActionSetRejectsMissingCommand proves a command is required,
// because the template is the only way an action reaches the provider.
func TestParseControlActionSetRejectsMissingCommand(t *testing.T) {
	document := `{"actions": [{"name": "probe", "permission": "control"}]}`
	if _, err := ParseControlActionSet([]byte(document)); err == nil {
		t.Fatal("a missing command was accepted")
	}
}

// TestParseControlActionSetRejectsEmptyCommandToken proves an empty token is
// refused, because it would reach the provider as an empty argument.
func TestParseControlActionSetRejectsEmptyCommandToken(t *testing.T) {
	document := `{"actions": [{"name": "probe", "permission": "control", "command": ["runtime", "", "--json"]}]}`
	if _, err := ParseControlActionSet([]byte(document)); err == nil {
		t.Fatal("an empty command token was accepted")
	}
}

// TestParseControlActionSetRejectsUnknownPlaceholder proves a misspelled
// placeholder is refused instead of reaching the provider as literal text.
func TestParseControlActionSetRejectsUnknownPlaceholder(t *testing.T) {
	document := `{"actions": [{"name": "probe", "permission": "control", "command": ["runtime", "{sesion}", "--json"]}]}`
	if _, err := ParseControlActionSet([]byte(document)); err == nil {
		t.Fatal("an unknown placeholder was accepted")
	}
}

// TestParseControlActionSetRejectsUnterminatedPlaceholder proves a token with an
// opening brace and no closing brace is refused.
func TestParseControlActionSetRejectsUnterminatedPlaceholder(t *testing.T) {
	document := `{"actions": [{"name": "probe", "permission": "control", "command": ["runtime", "{session", "--json"]}]}`
	if _, err := ParseControlActionSet([]byte(document)); err == nil {
		t.Fatal("an unterminated placeholder was accepted")
	}
}

// TestParseControlActionSetRejectsRepeatedPlaceholder proves a placeholder may
// appear at most once, because a second occurrence would silently duplicate the
// selector or the payload.
func TestParseControlActionSetRejectsRepeatedPlaceholder(t *testing.T) {
	cases := map[string]string{
		"session": `{"actions": [{"name": "probe", "permission": "control", "command": ["runtime", "-s", "{session}", "-s", "{session}", "--json"]}]}`,
		"payload": `{"actions": [{"name": "probe", "permission": "control", "command": ["runtime", "-a", "{payload}", "-a", "{payload}", "--json"]}]}`,
	}
	for name, document := range cases {
		t.Run(name, func(t *testing.T) {
			if _, err := ParseControlActionSet([]byte(document)); err == nil {
				t.Fatalf("a repeated %s placeholder was accepted", name)
			}
		})
	}
}

// TestParseControlActionSetRejectsPayloadSessionFieldWithoutPayload proves a
// payload field is refused when the command never forwards the payload, because
// the injection would be silently ignored.
func TestParseControlActionSetRejectsPayloadSessionFieldWithoutPayload(t *testing.T) {
	document := `{"actions": [{"name": "probe", "permission": "control", "payload_session_field": "session_id", "command": ["runtime", "control", "probe", "--json"]}]}`
	if _, err := ParseControlActionSet([]byte(document)); err == nil {
		t.Fatal("a payload_session_field without a payload placeholder was accepted")
	}
}

// TestParseControlActionSetRejectsDuplicateName proves a repeated name is refused,
// because the second entry would silently replace the first.
func TestParseControlActionSetRejectsDuplicateName(t *testing.T) {
	document := `{"actions": [
	  {"name": "probe", "permission": "control", "command": ["runtime", "control", "a", "--json"]},
	  {"name": "probe", "permission": "read_output", "command": ["runtime", "control", "b", "--json"]}
	]}`
	if _, err := ParseControlActionSet([]byte(document)); err == nil {
		t.Fatal("a duplicate name was accepted")
	}
}

// TestParseControlActionSetRejectsUnknownField proves an unknown field is refused
// rather than ignored, so a misspelled key fails at load time.
func TestParseControlActionSetRejectsUnknownField(t *testing.T) {
	document := `{"actions": [{"name": "probe", "permission": "control", "command": ["runtime", "control", "x", "--json"], "extra": true}]}`
	if _, err := ParseControlActionSet([]byte(document)); err == nil {
		t.Fatal("an unknown field was accepted")
	}
}

// TestParseControlActionSetRejectsNonObjectPayloadSchema proves a schema must be a
// JSON object, because the interactive surface reads it as a property map.
func TestParseControlActionSetRejectsNonObjectPayloadSchema(t *testing.T) {
	document := `{"actions": [{"name": "probe", "permission": "control", "payload_schema": ["not", "an", "object"], "command": ["runtime", "control", "x", "--json"]}]}`
	if _, err := ParseControlActionSet([]byte(document)); err == nil {
		t.Fatal("a non-object payload_schema was accepted")
	}
}

// TestParseControlActionSetAcceptsEmptyList proves an empty catalog is accepted and
// disables the whole family, which is the fail-closed default.
func TestParseControlActionSetAcceptsEmptyList(t *testing.T) {
	set := newTestControlSet(t, `{"actions": []}`)
	if set.Len() != 0 {
		t.Fatalf("actions = %d, want 0", set.Len())
	}
	if capabilities := controlActionCapabilities(set); len(capabilities) != 0 {
		t.Fatalf("capabilities = %v, want none", capabilities)
	}
}

// TestControlActionCapabilitiesCarryConfiguredPayloadSchema proves the advertised
// schema comes from the catalog, so the interactive prompt follows the file.
func TestControlActionCapabilitiesCarryConfiguredPayloadSchema(t *testing.T) {
	document := `{"actions": [{"name": "probe", "permission": "control", "payload_schema": {"type": "object", "properties": {"detail": {"type": "boolean"}}}, "command": ["runtime", "control", "probe", "-a", "{payload}", "--json"]}]}`
	set := newTestControlSet(t, document)
	capabilities := controlActionCapabilities(set)
	if len(capabilities) != 1 {
		t.Fatalf("capabilities = %d, want 1", len(capabilities))
	}
	if !strings.Contains(capabilities[0].PayloadSchema, `"detail"`) {
		t.Fatalf("payload schema = %q, want it to document detail", capabilities[0].PayloadSchema)
	}
}

// TestControlActionArgsRejectDisabledAction proves an action absent from the
// catalog is refused even when submitted directly.
func TestControlActionArgsRejectDisabledAction(t *testing.T) {
	document := `{"actions": [{"name": "probe", "permission": "control", "command": ["runtime", "control", "probe", "-s", "{session}", "--json"]}]}`
	set := newTestControlSet(t, document)
	if _, err := controlActionArgs(set, "ctl.inspect", "sess1", nil); err == nil {
		t.Fatal("a disabled action was accepted")
	}
}

// TestControlActionSetReloadKeepsPreviousSetOnParseFailure proves a broken edit
// cannot disable or widen the policy.
func TestControlActionSetReloadKeepsPreviousSetOnParseFailure(t *testing.T) {
	set := newTestControlSet(t, minimalCatalog)
	if err := set.Reload([]byte(`{"actions": [`)); err == nil {
		t.Fatal("a broken document was accepted")
	}
	if set.Len() != 1 {
		t.Fatalf("actions = %d, want the previous 1", set.Len())
	}
	if _, ok := set.Get("probe"); !ok {
		t.Fatal("the previous action was lost")
	}
}

// TestControlActionSetReloadSwapsAtomically proves a valid reload replaces the set.
func TestControlActionSetReloadSwapsAtomically(t *testing.T) {
	set := newTestControlSet(t, minimalCatalog)
	document := `{"actions": [{"name": "inspect", "permission": "read_output", "command": ["runtime", "control", "inspect", "--json"]}]}`
	if err := set.Reload([]byte(document)); err != nil {
		t.Fatalf("Reload: %v", err)
	}
	if _, ok := set.Get("probe"); ok {
		t.Fatal("the replaced action is still enabled")
	}
	if _, ok := set.Get("inspect"); !ok {
		t.Fatal("the new action is not enabled")
	}
}

// TestControlActionSetReloadFromDiskReadsTheFile proves the reload path reads the
// configured file.
func TestControlActionSetReloadFromDiskReadsTheFile(t *testing.T) {
	path := filepath.Join(t.TempDir(), "control-actions.json")
	if err := os.WriteFile(path, []byte(minimalCatalog), 0o600); err != nil {
		t.Fatalf("write catalog: %v", err)
	}
	set, err := LoadControlActionSet(path)
	if err != nil {
		t.Fatalf("LoadControlActionSet: %v", err)
	}
	document := `{"actions": [{"name": "inspect", "permission": "read_output", "command": ["runtime", "control", "inspect", "--json"]}]}`
	if err := os.WriteFile(path, []byte(document), 0o600); err != nil {
		t.Fatalf("rewrite catalog: %v", err)
	}
	if err := set.ReloadFromDisk(); err != nil {
		t.Fatalf("ReloadFromDisk: %v", err)
	}
	if _, ok := set.Get("inspect"); !ok {
		t.Fatal("the reloaded action is not enabled")
	}
}

// TestControlActionSetReloadFromDiskKeepsPreviousSetOnBrokenFile proves a broken
// file on disk keeps the previous set in force.
func TestControlActionSetReloadFromDiskKeepsPreviousSetOnBrokenFile(t *testing.T) {
	path := filepath.Join(t.TempDir(), "control-actions.json")
	if err := os.WriteFile(path, []byte(minimalCatalog), 0o600); err != nil {
		t.Fatalf("write catalog: %v", err)
	}
	set, err := LoadControlActionSet(path)
	if err != nil {
		t.Fatalf("LoadControlActionSet: %v", err)
	}
	if err := os.WriteFile(path, []byte(`{"actions": [`), 0o600); err != nil {
		t.Fatalf("break catalog: %v", err)
	}
	if err := set.ReloadFromDisk(); err == nil {
		t.Fatal("a broken file was accepted")
	}
	if set.Len() != 1 {
		t.Fatalf("actions = %d, want the previous 1", set.Len())
	}
}

// TestControlActionSetWatchReloadRequiresConfiguration proves a nil set cannot be
// watched.
func TestControlActionSetWatchReloadRequiresConfiguration(t *testing.T) {
	var set *ControlActionSet
	if _, err := set.WatchReload(t.Context(), nil); err == nil {
		t.Fatal("a nil set was watchable")
	}
}

// TestControlActionSetWatchReloadStopsCleanly proves the watcher releases its
// signal handler.
func TestControlActionSetWatchReloadStopsCleanly(t *testing.T) {
	set := newTestControlSet(t, minimalCatalog)
	stop, err := set.WatchReload(t.Context(), nil)
	if err != nil {
		t.Fatalf("WatchReload: %v", err)
	}
	stop()
	stop()
}

// TestControlActionSetNilAccessorsAreSafe proves every accessor tolerates a nil
// set, so an Endpoint without a catalog never panics.
func TestControlActionSetNilAccessorsAreSafe(t *testing.T) {
	var set *ControlActionSet
	if set.Actions() != nil {
		t.Fatal("Actions on a nil set must be nil")
	}
	if _, ok := set.Get("probe"); ok {
		t.Fatal("Get on a nil set must report absence")
	}
	if set.Len() != 0 {
		t.Fatal("Len on a nil set must be 0")
	}
	if set.Names() != nil {
		t.Fatal("Names on a nil set must be nil")
	}
	if err := set.ReloadFromDisk(); err == nil {
		t.Fatal("ReloadFromDisk on a nil set must fail")
	}
}

// TestControlActionTargetPayloadInjectsSessionID proves the configured payload
// field is filled from the revalidated target.
func TestControlActionTargetPayloadInjectsSessionID(t *testing.T) {
	action := ControlAction{Name: "read_messages", PayloadSessionField: "session_id"}
	payload, err := controlActionTargetPayload(action, "sess-42", []byte(`{}`))
	if err != nil {
		t.Fatalf("controlActionTargetPayload: %v", err)
	}
	if !strings.Contains(string(payload), `"session_id":"sess-42"`) {
		t.Fatalf("payload = %s, want the injected session_id", payload)
	}
}

// TestControlActionTargetPayloadKeepsOtherActionsUntouched proves an action without
// a declared field is not modified.
func TestControlActionTargetPayloadKeepsOtherActionsUntouched(t *testing.T) {
	action := ControlAction{Name: "probe"}
	payload, err := controlActionTargetPayload(action, "sess-42", []byte(`{"reason":"x"}`))
	if err != nil {
		t.Fatalf("controlActionTargetPayload: %v", err)
	}
	if string(payload) != `{"reason":"x"}` {
		t.Fatalf("payload = %s, want it unchanged", payload)
	}
}

// TestControlActionTargetPayloadRejectsMismatchedSessionID proves a supplied value
// that disagrees with the target is refused instead of being overwritten.
func TestControlActionTargetPayloadRejectsMismatchedSessionID(t *testing.T) {
	action := ControlAction{Name: "read_messages", PayloadSessionField: "session_id"}
	if _, err := controlActionTargetPayload(action, "sess-42", []byte(`{"session_id":"other"}`)); err == nil {
		t.Fatal("a mismatched session_id was accepted")
	}
}

// TestControlActionTargetPayloadAcceptsMatchingSessionID proves a supplied value
// that agrees with the target is accepted.
func TestControlActionTargetPayloadAcceptsMatchingSessionID(t *testing.T) {
	action := ControlAction{Name: "read_messages", PayloadSessionField: "session_id"}
	if _, err := controlActionTargetPayload(action, "sess-42", []byte(`{"session_id":"sess-42"}`)); err != nil {
		t.Fatalf("controlActionTargetPayload: %v", err)
	}
}

// TestControlActionTargetPayloadRequiresResolvedSession proves an unresolved target
// is refused rather than producing a payload with an empty selector.
func TestControlActionTargetPayloadRequiresResolvedSession(t *testing.T) {
	action := ControlAction{Name: "read_messages", PayloadSessionField: "session_id"}
	if _, err := controlActionTargetPayload(action, "", []byte(`{}`)); err == nil {
		t.Fatal("an unresolved session was accepted")
	}
}

// TestControlActionCommandRequiresResolvedSession proves a template using the
// session placeholder is refused when the target did not resolve.
func TestControlActionCommandRequiresResolvedSession(t *testing.T) {
	action := ControlAction{Name: "probe", Command: []string{"runtime", "-s", "{session}", "--json"}}
	if _, err := controlActionCommand(action, "", []byte(`{}`)); err == nil {
		t.Fatal("an unresolved session was accepted")
	}
}

// TestControlActionCommandSubstitutesPerToken proves substitution happens inside a
// token, so a placeholder never splits into several arguments.
func TestControlActionCommandSubstitutesPerToken(t *testing.T) {
	action := ControlAction{Name: "probe", Command: []string{"runtime", "--session={session}", "--json"}}
	args, err := controlActionCommand(action, "sess-42", []byte(`{}`))
	if err != nil {
		t.Fatalf("controlActionCommand: %v", err)
	}
	if len(args) != 3 {
		t.Fatalf("argv = %v, want 3 tokens", args)
	}
	if args[1] != "--session=sess-42" {
		t.Fatalf("argv[1] = %q, want --session=sess-42", args[1])
	}
}

// TestControlActionCommandAllowsATemplateWithoutSession proves an action may address
// the provider without a session selector.
func TestControlActionCommandAllowsATemplateWithoutSession(t *testing.T) {
	action := ControlAction{Name: "probe", Command: []string{"runtime", "control", "probe", "--json"}}
	args, err := controlActionCommand(action, "", []byte(`{}`))
	if err != nil {
		t.Fatalf("controlActionCommand: %v", err)
	}
	if len(args) != 4 {
		t.Fatalf("argv = %v, want 4 tokens", args)
	}
}

// TestParseControlActionSetAcceptsPayloadConstants proves a catalog entry may fix
// a payload field itself, which is how one entry names a single instruction
// instead of asking the operator to choose from the whole inventory.
func TestParseControlActionSetAcceptsPayloadConstants(t *testing.T) {
	document := `{"actions": [
	  {"name": "git.status", "permission": "read_output",
	   "payload_constants": {"instruction": "git.git_status"},
	   "payload_schema": {"type": "object", "properties": {"args": {"type": "array"}}},
	   "command": ["runtime", "control", "call_instruction", "-s", "{session}", "-a", "{payload}", "--json"]}
	]}`
	set := newTestControlSet(t, document)
	action, ok := set.Get("git.status")
	if !ok {
		t.Fatal("git.status is not enabled")
	}
	if action.PayloadConstants["instruction"] != "git.git_status" {
		t.Fatalf("payload_constants = %v, want instruction=git.git_status", action.PayloadConstants)
	}
}

// TestParseControlActionSetRejectsATemplatedConstant proves a constant must be a
// literal. A constant that expanded would let the catalog reintroduce the
// operator-controlled command it exists to prevent.
func TestParseControlActionSetRejectsATemplatedConstant(t *testing.T) {
	document := `{"actions": [
	  {"name": "probe", "permission": "control",
	   "payload_constants": {"instruction": "{session}"},
	   "command": ["runtime", "control", "call_instruction", "-s", "{session}", "-a", "{payload}", "--json"]}
	]}`
	if _, err := ParseControlActionSet([]byte(document)); err == nil {
		t.Fatal("a templated constant must be rejected")
	}
}

// TestParseControlActionSetRejectsConstantsWithoutPayload proves a constant needs
// a {payload} placeholder, because otherwise the value would never be forwarded.
func TestParseControlActionSetRejectsConstantsWithoutPayload(t *testing.T) {
	document := `{"actions": [
	  {"name": "probe", "permission": "control",
	   "payload_constants": {"instruction": "git.git_status"},
	   "command": ["runtime", "control", "probe", "-s", "{session}", "--json"]}
	]}`
	if _, err := ParseControlActionSet([]byte(document)); err == nil {
		t.Fatal("constants without a {payload} placeholder must be rejected")
	}
}

// TestParseControlActionSetRejectsAConstantOnTheSessionField proves the injected
// selector and a constant cannot claim the same field, because the two would
// disagree about who owns the value.
func TestParseControlActionSetRejectsAConstantOnTheSessionField(t *testing.T) {
	document := `{"actions": [
	  {"name": "probe", "permission": "control",
	   "payload_session_field": "session_id",
	   "payload_constants": {"session_id": "fixed"},
	   "command": ["runtime", "control", "probe", "-s", "{session}", "-a", "{payload}", "--json"]}
	]}`
	if _, err := ParseControlActionSet([]byte(document)); err == nil {
		t.Fatal("a constant on the payload_session_field must be rejected")
	}
}

// TestControlActionConstantPayloadFillsTheField proves the constant reaches the
// provider payload, so the operator never has to supply it.
func TestControlActionConstantPayloadFillsTheField(t *testing.T) {
	action := ControlAction{Name: "git.status", PayloadConstants: map[string]string{"instruction": "git.git_status"}}
	payload, err := controlActionConstantPayload(action, []byte(`{"args":["--short"]}`))
	if err != nil {
		t.Fatalf("controlActionConstantPayload: %v", err)
	}
	var decoded map[string]json.RawMessage
	if err := json.Unmarshal(payload, &decoded); err != nil {
		t.Fatalf("decode payload: %v", err)
	}
	var instruction string
	if err := json.Unmarshal(decoded["instruction"], &instruction); err != nil {
		t.Fatalf("decode instruction: %v", err)
	}
	if instruction != "git.git_status" {
		t.Fatalf("instruction = %q, want git.git_status", instruction)
	}
	if _, ok := decoded["args"]; !ok {
		t.Fatal("the operator-supplied args were dropped")
	}
}

// TestControlActionConstantPayloadRejectsADisagreeingValue proves a caller cannot
// reach a different instruction through an entry that advertises one.
func TestControlActionConstantPayloadRejectsADisagreeingValue(t *testing.T) {
	action := ControlAction{Name: "git.status", PayloadConstants: map[string]string{"instruction": "git.git_status"}}
	if _, err := controlActionConstantPayload(action, []byte(`{"instruction":"ctx.clear"}`)); err == nil {
		t.Fatal("a disagreeing instruction must be rejected")
	}
}

// TestControlActionConstantPayloadAcceptsTheSameValue proves a caller that repeats
// the fixed value is not punished for it.
func TestControlActionConstantPayloadAcceptsTheSameValue(t *testing.T) {
	action := ControlAction{Name: "git.status", PayloadConstants: map[string]string{"instruction": "git.git_status"}}
	if _, err := controlActionConstantPayload(action, []byte(`{"instruction":"git.git_status"}`)); err != nil {
		t.Fatalf("controlActionConstantPayload: %v", err)
	}
}

// TestParseControlActionSetRejectsConstantsOnAShortcut proves a shortcut cannot
// pin a field, because it inherits its target's constants and a second set would
// make the effective payload depend on which entry the operator typed.
func TestParseControlActionSetRejectsConstantsOnAShortcut(t *testing.T) {
	document := `{"actions": [
	  {"name": "probe", "permission": "control", "command": ["runtime", "control", "probe", "-s", "{session}", "-a", "{payload}", "--json"]},
	  {"name": "probe.shortcut", "alias_of": "probe", "payload_constants": {"instruction": "x"}}
	]}`
	if _, err := ParseControlActionSet([]byte(document)); err == nil {
		t.Fatal("a shortcut declaring payload_constants must be rejected")
	}
}

// TestParseControlActionSetShortcutInheritsConstants proves a shortcut of an entry
// that fixes a field keeps that field fixed, so a shortcut never loses the
// instruction its target names.
func TestParseControlActionSetShortcutInheritsConstants(t *testing.T) {
	document := `{"actions": [
	  {"name": "git.status", "permission": "read_output",
	   "payload_constants": {"instruction": "git.git_status"},
	   "command": ["runtime", "control", "call_instruction", "-s", "{session}", "-a", "{payload}", "--json"]},
	  {"name": "git.st", "alias_of": "git.status"}
	]}`
	set := newTestControlSet(t, document)
	shortcut, ok := set.Get("git.st")
	if !ok {
		t.Fatal("git.st is not enabled")
	}
	if shortcut.PayloadConstants["instruction"] != "git.git_status" {
		t.Fatalf("payload_constants = %v, want the target's instruction", shortcut.PayloadConstants)
	}
}
