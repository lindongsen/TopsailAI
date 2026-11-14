package controlaction

import (
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

// shippedControlActionPath is the catalog the deployment documentation points
// at. It is read from the repository so the test fails when the shipped example
// stops being a valid catalog.
func shippedControlActionPath(t *testing.T) string {
	t.Helper()
	return filepath.Join("..", "..", "conf", "control-actions.conf.example")
}

// TestShippedControlActionCatalogParses proves the shipped example is loadable.
// The catalog is optional, so an invalid example does not stop a fresh Endpoint
// from starting; it instead fails the first operator who copies it. That is
// exactly the defect this test exists to prevent.
func TestShippedControlActionCatalogParses(t *testing.T) {
	data, err := os.ReadFile(shippedControlActionPath(t))
	if err != nil {
		t.Fatalf("read the shipped control action catalog: %v", err)
	}
	set, err := ParseControlActionSet(data)
	if err != nil {
		t.Fatalf("the shipped control action catalog must parse, got %v", err)
	}
	if set.Len() == 0 {
		t.Fatalf("the shipped catalog must enable something, otherwise the example silently disables the feature")
	}
}

// TestShippedControlActionCatalogDocumentsEverySchema proves the example carries a
// payload schema for every action. A catalog that omits a schema still works,
// because the interactive surface falls back to its generic prompt, but the
// example is the operator's reference and must show the fields.
func TestShippedControlActionCatalogDocumentsEverySchema(t *testing.T) {
	data, err := os.ReadFile(shippedControlActionPath(t))
	if err != nil {
		t.Fatalf("read the shipped control action catalog: %v", err)
	}
	set, err := ParseControlActionSet(data)
	if err != nil {
		t.Fatalf("the shipped control action catalog must parse, got %v", err)
	}
	for _, action := range set.Actions() {
		if action.PayloadSchema == "" {
			t.Errorf("the shipped catalog omits payload_schema for %q, so the example does not document its fields", action.Name)
		}
	}
}

// TestShippedControlActionCatalogDeclaresCommands proves every example action
// carries the provider argv template. The template is the only way an action
// reaches the provider, so an example without one would document an action that
// cannot run.
func TestShippedControlActionCatalogDeclaresCommands(t *testing.T) {
	data, err := os.ReadFile(shippedControlActionPath(t))
	if err != nil {
		t.Fatalf("read the shipped control action catalog: %v", err)
	}
	set, err := ParseControlActionSet(data)
	if err != nil {
		t.Fatalf("the shipped control action catalog must parse, got %v", err)
	}
	for _, action := range set.Actions() {
		if len(action.Command) == 0 {
			t.Errorf("the shipped catalog omits command for %q", action.Name)
		}
	}
}

// TestShippedControlActionCatalogKeepsContentActionsReadOnly pins the intent of
// the example: an action that returns conversation content must require
// read_output rather than control, because an operator allowed to interrupt a
// session is not thereby allowed to read its messages.
func TestShippedControlActionCatalogKeepsContentActionsReadOnly(t *testing.T) {
	data, err := os.ReadFile(shippedControlActionPath(t))
	if err != nil {
		t.Fatalf("read the shipped control action catalog: %v", err)
	}
	set, err := ParseControlActionSet(data)
	if err != nil {
		t.Fatalf("the shipped control action catalog must parse, got %v", err)
	}
	content := map[string]bool{"get_runtime_messages": true, "get_session_messages": true}
	for _, action := range set.Actions() {
		if !content[action.Name] {
			continue
		}
		if action.Permission != "read_output" {
			t.Errorf("the shipped catalog gives %q permission %q, but it returns conversation content and must require read_output", action.Name, action.Permission)
		}
	}
}

// TestShippedControlActionCatalogInjectsTheSessionSelector proves the example
// declares the payload field for the action that needs the provider session key
// in its payload, so the operator is never asked for a selector the Endpoint
// already holds.
func TestShippedControlActionCatalogInjectsTheSessionSelector(t *testing.T) {
	data, err := os.ReadFile(shippedControlActionPath(t))
	if err != nil {
		t.Fatalf("read the shipped control action catalog: %v", err)
	}
	set, err := ParseControlActionSet(data)
	if err != nil {
		t.Fatalf("the shipped control action catalog must parse, got %v", err)
	}
	action, ok := set.Get("get_session_messages")
	if !ok {
		t.Fatalf("the shipped catalog must document get_session_messages")
	}
	if action.PayloadSessionField != "session_id" {
		t.Fatalf("payload_session_field = %q, want session_id", action.PayloadSessionField)
	}
}

// TestShippedControlActionCatalogUsesNoShellMetacharacters proves the example
// templates are plain argv arrays. A template is executed directly, so a token
// that only makes sense to a shell would either fail or, worse, be passed to the
// provider as literal text.
func TestShippedControlActionCatalogUsesNoShellMetacharacters(t *testing.T) {
	data, err := os.ReadFile(shippedControlActionPath(t))
	if err != nil {
		t.Fatalf("read the shipped control action catalog: %v", err)
	}
	set, err := ParseControlActionSet(data)
	if err != nil {
		t.Fatalf("the shipped control action catalog must parse, got %v", err)
	}
	for _, action := range set.Actions() {
		for _, token := range action.Command {
			if strings.ContainsAny(token, "|&;<>$`") {
				t.Errorf("action %q command token %q contains a shell metacharacter", action.Name, token)
			}
		}
	}
}

// TestShippedControlActionCatalogListsInstructions proves the shipped
// call_instruction entry carries the instruction inventory in its enum, so the
// guided prompt offers a menu instead of a free-text field. The enum is a prompt
// convenience rather than an authorization gate, but an empty or duplicated list
// would still make the prompt unusable.
func TestShippedControlActionCatalogListsInstructions(t *testing.T) {
	data, err := os.ReadFile(shippedControlActionPath(t))
	if err != nil {
		t.Fatalf("read the shipped control action catalog: %v", err)
	}
	set, err := ParseControlActionSet(data)
	if err != nil {
		t.Fatalf("the shipped control action catalog must parse, got %v", err)
	}
	action, ok := set.Get("call_instruction")
	if !ok {
		t.Fatalf("the shipped catalog must document call_instruction")
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
		t.Fatalf("the call_instruction schema must document the instruction field")
	}
	if len(instruction.Enum) == 0 {
		t.Fatalf("the instruction field must list the registered instructions, otherwise the prompt asks for free text")
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

// TestShippedControlActionCatalogRequiresControlToChangeTheModel proves the
// shipped catalog does not let a read_output credential change the live model.
//
// agent.models applies a model configuration to a running agent, so it mutates
// the session. Advertising it as read_output would let an operator who is only
// allowed to read output reconfigure the model that produces that output. The
// permission is therefore control, and this test fails if the example drifts
// back to a read scope.
func TestShippedControlActionCatalogRequiresControlToChangeTheModel(t *testing.T) {
	data, err := os.ReadFile(shippedControlActionPath(t))
	if err != nil {
		t.Fatalf("read the shipped control action catalog: %v", err)
	}
	set, err := ParseControlActionSet(data)
	if err != nil {
		t.Fatalf("the shipped control action catalog must parse, got %v", err)
	}
	var found bool
	for _, action := range set.Actions() {
		if action.Name != "agent.models" {
			continue
		}
		found = true
		if action.Permission != "control" {
			t.Errorf("the shipped catalog gives agent.models permission %q, but it changes the live model and must require control", action.Permission)
		}
	}
	if !found {
		t.Fatal("the shipped catalog no longer declares agent.models, so the model selection surface is unreachable")
	}
}
