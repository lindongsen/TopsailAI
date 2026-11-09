package topsailai

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
	return filepath.Join("..", "..", "..", "conf", "control-actions.conf.example")
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

// TestEndpointTemplateNamesTheInstalledCatalog keeps the configuration template
// and the deployment scripts in agreement. The catalog is the only source of ctl.
// actions, so a template that omits the key silently removes the feature from a
// fresh node instead of failing loudly.
func TestEndpointTemplateNamesTheInstalledCatalog(t *testing.T) {
	templatePath := filepath.Join("..", "..", "..", "conf", "node.endpoint.conf.example")
	data, err := os.ReadFile(templatePath)
	if err != nil {
		t.Fatalf("read the endpoint template: %v", err)
	}
	var configured string
	for _, line := range strings.Split(string(data), "\n") {
		trimmed := strings.TrimSpace(line)
		if strings.HasPrefix(trimmed, "CONTROL_ACTION_FILE=") {
			configured = strings.TrimPrefix(trimmed, "CONTROL_ACTION_FILE=")
		}
	}
	if configured == "" {
		t.Fatalf("the endpoint template must set CONTROL_ACTION_FILE, otherwise a fresh node advertises no ctl. action")
	}
	if !strings.HasSuffix(configured, "/control-actions.conf") {
		t.Fatalf("the template names %q, but the deployment scripts install control-actions.conf", configured)
	}
}

// TestDeploymentScriptsInstallTheCatalog proves both deployment paths ship the
// file the template names. A template pointing at a file the package does not
// contain leaves the operator with a configured catalog that is never loaded.
func TestDeploymentScriptsInstallTheCatalog(t *testing.T) {
	scripts := map[string]string{
		"make-node-bundle.sh": filepath.Join("..", "..", "..", "scripts", "make-node-bundle.sh"),
		"make-deb.sh":         filepath.Join("..", "..", "..", "scripts", "make-deb.sh"),
	}
	for name, path := range scripts {
		data, err := os.ReadFile(path)
		if err != nil {
			t.Fatalf("read %s: %v", name, err)
		}
		content := string(data)
		if !strings.Contains(content, "control-actions.conf.example") {
			t.Errorf("%s must install conf/control-actions.conf.example, otherwise a fresh node advertises no ctl. action", name)
		}
		if !strings.Contains(content, "control-actions.conf") {
			t.Errorf("%s must install the catalog under the name the template uses", name)
		}
	}
}

// TestLauncherForwardsTheControlActionCatalog proves the launcher hands the
// catalog path to the endpoint binary.
//
// This guards a real defect: the template named CONTROL_ACTION_FILE and both
// deployment paths installed the catalog, but scripts/agent-clusterctl resolved
// and forwarded only COMMAND_ALLOWLIST_FILE. Every packaged node therefore
// started with no catalog, advertised zero ctl. actions and refused every ctl.
// operation, while node.conf named the file and the file was present. The
// failure is fail-closed, so nothing unsafe happened and nothing was logged as
// an error; the only symptom was an empty capability list that an operator reads
// as "not configured yet".
//
// The allowlist received this treatment in d0bad293. The catalog was added later
// and never received the same three edits, so the two keys drifted. Asserting all
// three sites here is what keeps them from drifting again: a resolve without a
// forward still drops the path, and a forward without a resolve passes a
// relative path the binary cannot use.
func TestLauncherForwardsTheControlActionCatalog(t *testing.T) {
	path := filepath.Join("..", "..", "..", "scripts", "agent-clusterctl")
	data, err := os.ReadFile(path)
	if err != nil {
		t.Fatalf("read the launcher: %v", err)
	}
	content := string(data)

	// The resolve step turns the configured relative path into an absolute one.
	if !strings.Contains(content, `CONTROL_ACTION_FILE=$(resolve_path "${CONTROL_ACTION_FILE:-}")`) {
		t.Errorf("the launcher must resolve CONTROL_ACTION_FILE like COMMAND_ALLOWLIST_FILE;\n" +
			"a relative path reaches the binary unresolved and the catalog is never found")
	}

	// The doctor line is how an operator sees which catalog a node would load.
	if !strings.Contains(content, `echo "catalog    : ${CONTROL_ACTION_FILE:-<disabled>}"`) {
		t.Errorf("doctor must print the resolved catalog path, otherwise an operator cannot tell\n" +
			"a missing catalog from a catalog that was never forwarded")
	}

	// The argv entry is the only site that actually delivers the path.
	if !strings.Contains(content, `args+=(--control-action-file "${CONTROL_ACTION_FILE}")`) {
		t.Errorf("the launcher must pass --control-action-file to the endpoint binary;\n" +
			"without it every packaged node advertises no ctl. action")
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
