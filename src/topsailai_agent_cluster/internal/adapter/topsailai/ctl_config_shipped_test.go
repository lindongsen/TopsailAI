package topsailai

import (
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
