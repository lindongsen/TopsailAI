package topsailai

import (
	"strings"
	"testing"
)

// shortcutCatalog declares one real action and one shortcut that points at it.
const shortcutCatalog = `{
  "actions": [
    {"name": "get_session_messages", "permission": "read_output", "payload_schema": {"type": "object", "properties": {}}, "payload_session_field": "session_id", "command": ["runtime", "control", "get_session_messages", "-s", "{session}", "-a", "{payload}", "--json"]},
    {"name": "session.messages", "alias_of": "get_session_messages"}
  ]
}`

// TestParseControlActionSetExpandsAShortcut proves a shortcut becomes a full copy
// of its target, so the advertised capability, the schema and the argv all come
// from the action it names instead of being repeated in the file.
func TestParseControlActionSetExpandsAShortcut(t *testing.T) {
	set := newTestControlSet(t, shortcutCatalog)
	shortcut, ok := set.Get("session.messages")
	if !ok {
		t.Fatal("the shortcut is not enabled")
	}
	target, ok := set.Get("get_session_messages")
	if !ok {
		t.Fatal("the target is not enabled")
	}
	if shortcut.Permission != target.Permission {
		t.Fatalf("permission = %q, want the target's %q", shortcut.Permission, target.Permission)
	}
	if shortcut.PayloadSchema != target.PayloadSchema {
		t.Fatalf("payload schema = %q, want the target's %q", shortcut.PayloadSchema, target.PayloadSchema)
	}
	if shortcut.PayloadSessionField != target.PayloadSessionField {
		t.Fatalf("payload_session_field = %q, want the target's %q", shortcut.PayloadSessionField, target.PayloadSessionField)
	}
	if strings.Join(shortcut.Command, " ") != strings.Join(target.Command, " ") {
		t.Fatalf("command = %v, want the target's %v", shortcut.Command, target.Command)
	}
	if shortcut.AliasOf != "get_session_messages" {
		t.Fatalf("alias_of = %q, want get_session_messages", shortcut.AliasOf)
	}
}

// TestControlActionCapabilitiesAdvertiseAShortcut proves the shortcut reaches the
// operator as its own capability, which is what makes the dotted spelling
// ctl.session.messages resolvable without any client change.
func TestControlActionCapabilitiesAdvertiseAShortcut(t *testing.T) {
	set := newTestControlSet(t, shortcutCatalog)
	names := make(map[string]bool)
	for _, capability := range controlActionCapabilities(set) {
		names[capability.Name] = true
	}
	if !names["ctl.session.messages"] {
		t.Fatalf("capabilities = %v, want ctl.session.messages advertised", names)
	}
	if !names["ctl.get_session_messages"] {
		t.Fatalf("capabilities = %v, want the target still advertised", names)
	}
}

// TestControlActionArgsRunTheTargetCommand proves a shortcut runs exactly the argv
// of the action it names, so a shortcut is a typing convenience and never a second
// execution path.
func TestControlActionArgsRunTheTargetCommand(t *testing.T) {
	set := newTestControlSet(t, shortcutCatalog)
	shortcutArgs, err := controlActionArgs(set, "ctl.session.messages", "sess-42", []byte(`{}`))
	if err != nil {
		t.Fatalf("controlActionArgs for the shortcut: %v", err)
	}
	targetArgs, err := controlActionArgs(set, "ctl.get_session_messages", "sess-42", []byte(`{}`))
	if err != nil {
		t.Fatalf("controlActionArgs for the target: %v", err)
	}
	if strings.Join(shortcutArgs, " ") != strings.Join(targetArgs, " ") {
		t.Fatalf("shortcut argv = %v, want the target's %v", shortcutArgs, targetArgs)
	}
}

// TestControlActionShortcutInjectsTheSessionSelector proves the inherited
// payload_session_field still applies, so a shortcut does not lose the selector the
// Endpoint injects from the revalidated target.
func TestControlActionShortcutInjectsTheSessionSelector(t *testing.T) {
	set := newTestControlSet(t, shortcutCatalog)
	args, err := controlActionArgs(set, "ctl.session.messages", "sess-42", []byte(`{}`))
	if err != nil {
		t.Fatalf("controlActionArgs: %v", err)
	}
	joined := strings.Join(args, " ")
	if !strings.Contains(joined, `"session_id":"sess-42"`) {
		t.Fatalf("argv = %q, want the injected session_id", joined)
	}
}

// TestParseControlActionSetResolvesAForwardReference proves a shortcut may name an
// action declared later in the file, so the catalog does not depend on entry order.
func TestParseControlActionSetResolvesAForwardReference(t *testing.T) {
	document := `{
  "actions": [
    {"name": "session.messages", "alias_of": "get_session_messages"},
    {"name": "get_session_messages", "permission": "read_output", "command": ["runtime", "control", "get_session_messages", "-s", "{session}", "--json"]}
  ]
}`
	set := newTestControlSet(t, document)
	shortcut, ok := set.Get("session.messages")
	if !ok {
		t.Fatal("a forward reference was not resolved")
	}
	if shortcut.Permission != "read_output" {
		t.Fatalf("permission = %q, want the inherited read_output", shortcut.Permission)
	}
}

// TestParseControlActionSetKeepsFileOrderWithShortcuts proves the rendered menu
// follows the file, so the operator sees the catalog in the order it was written.
func TestParseControlActionSetKeepsFileOrderWithShortcuts(t *testing.T) {
	set := newTestControlSet(t, shortcutCatalog)
	names := set.Names()
	if len(names) != 2 || names[0] != "get_session_messages" || names[1] != "session.messages" {
		t.Fatalf("names = %v, want the file order", names)
	}
}

// TestParseControlActionSetRejectsAShortcutThatWidensItsTarget proves a shortcut
// cannot declare its own permission. Silently ignoring the field would let an
// operator believe a shortcut grants a scope it does not.
func TestParseControlActionSetRejectsAShortcutThatWidensItsTarget(t *testing.T) {
	document := `{
  "actions": [
    {"name": "get_session_messages", "permission": "read_output", "command": ["runtime", "control", "get_session_messages", "--json"]},
    {"name": "session.messages", "alias_of": "get_session_messages", "permission": "control"}
  ]
}`
	if _, err := ParseControlActionSet([]byte(document)); err == nil {
		t.Fatal("a shortcut that declares its own permission was accepted")
	}
}

// TestParseControlActionSetRejectsAShortcutThatDeclaresACommand proves a shortcut
// cannot run a different command than the action it names.
func TestParseControlActionSetRejectsAShortcutThatDeclaresACommand(t *testing.T) {
	document := `{
  "actions": [
    {"name": "get_session_messages", "permission": "read_output", "command": ["runtime", "control", "get_session_messages", "--json"]},
    {"name": "session.messages", "alias_of": "get_session_messages", "command": ["runtime", "control", "other", "--json"]}
  ]
}`
	if _, err := ParseControlActionSet([]byte(document)); err == nil {
		t.Fatal("a shortcut that declares its own command was accepted")
	}
}

// TestParseControlActionSetRejectsAShortcutThatDeclaresASchema proves a shortcut
// cannot advertise a payload schema that differs from the action it names.
func TestParseControlActionSetRejectsAShortcutThatDeclaresASchema(t *testing.T) {
	document := `{
  "actions": [
    {"name": "get_session_messages", "permission": "read_output", "command": ["runtime", "control", "get_session_messages", "--json"]},
    {"name": "session.messages", "alias_of": "get_session_messages", "payload_schema": {"type": "object", "properties": {"x": {"type": "string"}}}}
  ]
}`
	if _, err := ParseControlActionSet([]byte(document)); err == nil {
		t.Fatal("a shortcut that declares its own payload_schema was accepted")
	}
}

// TestParseControlActionSetRejectsAnUnknownShortcutTarget proves a shortcut that
// names an action the file does not declare fails at load time instead of
// advertising a capability that cannot run.
func TestParseControlActionSetRejectsAnUnknownShortcutTarget(t *testing.T) {
	document := `{"actions": [{"name": "session.messages", "alias_of": "not_configured"}]}`
	if _, err := ParseControlActionSet([]byte(document)); err == nil {
		t.Fatal("a shortcut naming an unknown action was accepted")
	}
}

// TestParseControlActionSetRejectsAShortcutChain proves a shortcut may not point at
// another shortcut, because the effective permission would then depend on
// resolution order.
func TestParseControlActionSetRejectsAShortcutChain(t *testing.T) {
	document := `{
  "actions": [
    {"name": "get_session_messages", "permission": "read_output", "command": ["runtime", "control", "get_session_messages", "--json"]},
    {"name": "session.messages", "alias_of": "get_session_messages"},
    {"name": "session.msgs", "alias_of": "session.messages"}
  ]
}`
	if _, err := ParseControlActionSet([]byte(document)); err == nil {
		t.Fatal("a shortcut pointing at another shortcut was accepted")
	}
}

// TestParseControlActionSetRejectsASelfReferencingShortcut proves a shortcut that
// names itself is refused instead of resolving to nothing.
func TestParseControlActionSetRejectsASelfReferencingShortcut(t *testing.T) {
	document := `{"actions": [{"name": "session.messages", "alias_of": "session.messages"}]}`
	if _, err := ParseControlActionSet([]byte(document)); err == nil {
		t.Fatal("a self-referencing shortcut was accepted")
	}
}

// TestParseControlActionSetRejectsAShortcutNameCollision proves a shortcut cannot
// reuse the name of a real action, because the two would silently overwrite each
// other.
func TestParseControlActionSetRejectsAShortcutNameCollision(t *testing.T) {
	document := `{
  "actions": [
    {"name": "get_session_messages", "permission": "read_output", "command": ["runtime", "control", "get_session_messages", "--json"]},
    {"name": "get_session_messages", "alias_of": "get_session_messages"}
  ]
}`
	if _, err := ParseControlActionSet([]byte(document)); err == nil {
		t.Fatal("a duplicated name was accepted")
	}
}

// TestControlActionSetReloadDropsARemovedShortcut proves a reload replaces the
// shortcut set instead of merging into it, so retiring a shortcut in the file
// retires it on the Endpoint.
func TestControlActionSetReloadDropsARemovedShortcut(t *testing.T) {
	set := newTestControlSet(t, shortcutCatalog)
	if _, ok := set.Get("session.messages"); !ok {
		t.Fatal("the shortcut is not enabled before the reload")
	}
	document := `{"actions": [{"name": "get_session_messages", "permission": "read_output", "command": ["runtime", "control", "get_session_messages", "--json"]}]}`
	if err := set.Reload([]byte(document)); err != nil {
		t.Fatalf("Reload: %v", err)
	}
	if _, ok := set.Get("session.messages"); ok {
		t.Fatal("a removed shortcut is still enabled after the reload")
	}
}
