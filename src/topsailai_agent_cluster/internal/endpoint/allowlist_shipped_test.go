package endpoint

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
)

// shippedAllowlistPath is the default policy the deployment scripts install as
// conf/command-allowlist.conf. It is read from the repository so the test fails
// when the shipped file stops being a valid policy.
func shippedAllowlistPath(t *testing.T) string {
	t.Helper()
	return filepath.Join("..", "..", "conf", "command-allowlist.conf.example")
}

// TestShippedAllowlistParses proves the default policy is loadable. A shipped file
// that fails to parse would make every fresh Endpoint exit at startup, because a
// missing or invalid allowlist is a configuration error rather than an implicit
// unrestricted policy.
func TestShippedAllowlistParses(t *testing.T) {
	data, err := os.ReadFile(shippedAllowlistPath(t))
	if err != nil {
		t.Fatalf("read the shipped allowlist: %v", err)
	}
	list, err := LoadAllowlist(data)
	if err != nil {
		t.Fatalf("the shipped allowlist must parse, got %v", err)
	}
	if list.Len() == 0 {
		t.Fatalf("the shipped allowlist must permit something, otherwise the feature is silently disabled")
	}
}

// TestShippedAllowlistPinsTheDefaultPolicy pins the intent of the default policy.
// It is mostly read-only, but it deliberately includes `git push` and `git show`,
// so a later edit that adds a mutating or shell-capable entry has to change this
// test and justify the change.
func TestShippedAllowlistPinsTheDefaultPolicy(t *testing.T) {
	data, err := os.ReadFile(shippedAllowlistPath(t))
	if err != nil {
		t.Fatalf("read the shipped allowlist: %v", err)
	}
	list, err := LoadAllowlist(data)
	if err != nil {
		t.Fatalf("the shipped allowlist must parse, got %v", err)
	}
	permitted := [][]string{
		{"ls"},
		{"ls", "-la"},
		{"pwd"},
		{"git", "status"},
		{"git", "status", "--short"},
		{"git", "log", "--oneline"},
		{"git", "diff", "HEAD"},
		{"git", "show"},
		{"git", "show", "HEAD:README.md"},
		{"git", "push"},
		{"git", "push", "origin", "main"},
	}
	for _, argv := range permitted {
		if err := list.Permit(argv); err != nil {
			t.Errorf("the default policy must permit %v, got %v", argv, err)
		}
	}
	denied := [][]string{
		{"rm", "-rf", "/"},
		{"git", "commit", "-m", "x"},
		{"git", "clean", "-fdx"},
		{"git", "reset", "--hard"},
		{"sh", "-c", "id"},
		{"bash"},
		{"python3", "-c", "print(1)"},
		{"curl", "http://example.com"},
	}
	for _, argv := range denied {
		if err := list.Permit(argv); err == nil {
			t.Errorf("the default policy must deny %v", argv)
		}
	}
}

// TestShippedAllowlistGitPushAndShowAreNotSandboxed records the accepted risk of
// the two entries this policy adds. Prefix matching cannot see the options that
// turn them into local command execution, so the test asserts the permissive
// behaviour explicitly instead of leaving it as an undocumented surprise.
func TestShippedAllowlistGitPushAndShowAreNotSandboxed(t *testing.T) {
	data, err := os.ReadFile(shippedAllowlistPath(t))
	if err != nil {
		t.Fatalf("read the shipped allowlist: %v", err)
	}
	list, err := LoadAllowlist(data)
	if err != nil {
		t.Fatalf("the shipped allowlist must parse, got %v", err)
	}
	// `git push --receive-pack=CMD` runs CMD locally, and `git show --output=PATH`
	// writes PATH. Both keep argv[0..1] equal to the allowlisted prefix, so the
	// policy permits them. This is a documented consequence of prefix matching.
	risky := [][]string{
		{"git", "push", "--receive-pack=sh -c id", "origin", "main"},
		{"git", "show", "--output=/tmp/x", "HEAD"},
	}
	for _, argv := range risky {
		if err := list.Permit(argv); err != nil {
			t.Errorf("prefix matching is expected to permit %v, got %v", argv, err)
		}
	}
}

// TestEndpointTemplateNamesTheInstalledAllowlist keeps the configuration template
// and the deployment scripts in agreement. The template value is the file name the
// scripts install, so a rename on either side is caught here rather than by an
// Endpoint that refuses to start on a fresh node.
func TestEndpointTemplateNamesTheInstalledAllowlist(t *testing.T) {
	templatePath := filepath.Join("..", "..", "conf", "node.endpoint.conf.example")
	data, err := os.ReadFile(templatePath)
	if err != nil {
		t.Fatalf("read the endpoint template: %v", err)
	}
	var configured string
	for _, line := range strings.Split(string(data), "\n") {
		trimmed := strings.TrimSpace(line)
		if strings.HasPrefix(trimmed, "COMMAND_ALLOWLIST_FILE=") {
			configured = strings.TrimPrefix(trimmed, "COMMAND_ALLOWLIST_FILE=")
		}
	}
	if configured == "" {
		t.Fatalf("the endpoint template must set COMMAND_ALLOWLIST_FILE, otherwise the shipped policy is never used")
	}
	if !strings.HasSuffix(configured, "/command-allowlist.conf") {
		t.Fatalf("the template names %q, but the deployment scripts install command-allowlist.conf", configured)
	}
}

// TestDeploymentScriptsInstallTheAllowlist proves both deployment paths ship the
// file the template names. Shipping a configuration that points at a file the
// package does not contain makes the Endpoint exit at startup, which is exactly the
// defect this test exists to prevent.
func TestDeploymentScriptsInstallTheAllowlist(t *testing.T) {
	scripts := map[string]string{
		"make-node-bundle.sh": filepath.Join("..", "..", "scripts", "make-node-bundle.sh"),
		"make-deb.sh":         filepath.Join("..", "..", "scripts", "make-deb.sh"),
	}
	for name, path := range scripts {
		data, err := os.ReadFile(path)
		if err != nil {
			t.Fatalf("read %s: %v", name, err)
		}
		content := string(data)
		if !strings.Contains(content, "command-allowlist.conf.example") {
			t.Errorf("%s must install conf/command-allowlist.conf.example, otherwise a fresh node cannot start", name)
		}
		if !strings.Contains(content, "command-allowlist.conf") {
			t.Errorf("%s must install the allowlist under the name the template uses", name)
		}
	}
}
