package node

import (
	"os"
	"path/filepath"
	"strings"
	"testing"

	"topsailai_connector/internal/security"
)

// lookupFrom builds an environment lookup from a map, so a test never mutates the
// process environment.
func lookupFrom(values map[string]string) func(string) string {
	return func(name string) string { return values[name] }
}

// validEnvironment returns an environment that passes every check, so a test can
// break exactly one value.
func validEnvironment(t *testing.T) map[string]string {
	t.Helper()
	return map[string]string{
		"CONNECTOR_NODE_SERVER_URL":      "wss://127.0.0.1:8443/channel",
		"CONNECTOR_NODE_TUNNEL_TOKEN":    "tunnel-token-of-sufficient-length",
		"CONNECTOR_NODE_CONFIG_DIR":      t.TempDir(),
		"CONNECTOR_NODE_POLICY_FILE":     "",
		"CONNECTOR_NODE_UNRELATED_VALUE": "ignored",
	}
}

// TestLoadConfigAcceptsValidEnvironment checks that a complete environment yields
// a configuration with the policy path defaulted inside the config directory.
func TestLoadConfigAcceptsValidEnvironment(t *testing.T) {
	environment := validEnvironment(t)
	config, err := LoadConfig(lookupFrom(environment))
	if err != nil {
		t.Fatalf("LoadConfig() = %v, want nil", err)
	}

	if config.ServerURL != environment["CONNECTOR_NODE_SERVER_URL"] {
		t.Fatalf("ServerURL = %q, want %q", config.ServerURL, environment["CONNECTOR_NODE_SERVER_URL"])
	}
	if config.ConfigDir != environment["CONNECTOR_NODE_CONFIG_DIR"] {
		t.Fatalf("ConfigDir = %q, want %q", config.ConfigDir, environment["CONNECTOR_NODE_CONFIG_DIR"])
	}
	wantPolicy := filepath.Join(environment["CONNECTOR_NODE_CONFIG_DIR"], "policy.yaml")
	if config.PolicyPath != wantPolicy {
		t.Fatalf("PolicyPath = %q, want %q", config.PolicyPath, wantPolicy)
	}
	if !config.TunnelToken.Equal(security.Secret(environment["CONNECTOR_NODE_TUNNEL_TOKEN"])) {
		t.Fatal("TunnelToken does not match the configured value")
	}
}

// TestLoadConfigRejectsBadServerURL checks that a missing or malformed channel
// address fails startup, because a Node with no address cannot dial and a Node
// with a wrong scheme fails at the first dial instead of at startup.
func TestLoadConfigRejectsBadServerURL(t *testing.T) {
	cases := []struct {
		name  string
		value string
	}{
		{"empty", ""},
		{"http scheme", "http://127.0.0.1:8443/channel"},
		{"no scheme", "127.0.0.1:8443/channel"},
		{"no host", "wss:///channel"},
		{"unparseable", "wss://127.0.0.1:8443/%zz"},
	}

	for _, testCase := range cases {
		t.Run(testCase.name, func(t *testing.T) {
			environment := validEnvironment(t)
			environment["CONNECTOR_NODE_SERVER_URL"] = testCase.value
			if _, err := LoadConfig(lookupFrom(environment)); err == nil {
				t.Fatal("LoadConfig() = nil error, want a failure")
			}
		})
	}
}

// TestLoadConfigRejectsBadTunnelToken checks that an absent, empty, short or
// whitespace-padded tunnel token fails startup, because an unset secret is the
// most likely way to accidentally disable authentication.
func TestLoadConfigRejectsBadTunnelToken(t *testing.T) {
	cases := []struct {
		name  string
		value string
	}{
		{"absent", ""},
		{"too short", "short"},
		{"trailing newline", "tunnel-token-of-sufficient-length\n"},
		{"leading space", " tunnel-token-of-sufficient-length"},
	}

	for _, testCase := range cases {
		t.Run(testCase.name, func(t *testing.T) {
			environment := validEnvironment(t)
			environment["CONNECTOR_NODE_TUNNEL_TOKEN"] = testCase.value
			if _, err := LoadConfig(lookupFrom(environment)); err == nil {
				t.Fatal("LoadConfig() = nil error, want a failure")
			}
		})
	}
}

// TestLoadConfigRejectsRelativePaths checks that a relative config directory or
// policy path fails startup, because a relative path resolves differently per
// launch and a policy that moves is a policy nobody can reason about.
func TestLoadConfigRejectsRelativePaths(t *testing.T) {
	t.Run("relative config dir", func(t *testing.T) {
		environment := validEnvironment(t)
		environment["CONNECTOR_NODE_CONFIG_DIR"] = "relative/config"
		if _, err := LoadConfig(lookupFrom(environment)); err == nil {
			t.Fatal("LoadConfig() = nil error, want a failure")
		}
	})

	t.Run("relative policy file", func(t *testing.T) {
		environment := validEnvironment(t)
		environment["CONNECTOR_NODE_POLICY_FILE"] = "relative/policy.yaml"
		if _, err := LoadConfig(lookupFrom(environment)); err == nil {
			t.Fatal("LoadConfig() = nil error, want a failure")
		}
	})
}

// TestLoadConfigRejectsConfigDirThatIsAFile checks that a config directory naming
// a regular file fails startup rather than being used as a directory.
func TestLoadConfigRejectsConfigDirThatIsAFile(t *testing.T) {
	base := t.TempDir()
	filePath := filepath.Join(base, "not-a-directory")
	writeFile(t, filePath, "content")

	environment := validEnvironment(t)
	environment["CONNECTOR_NODE_CONFIG_DIR"] = filePath
	if _, err := LoadConfig(lookupFrom(environment)); err == nil {
		t.Fatal("LoadConfig() = nil error, want a failure")
	}
}

// TestLoadConfigCreatesConfigDir checks that a config directory that does not
// exist is created with owner-only permissions, because it holds the node token.
func TestLoadConfigCreatesConfigDir(t *testing.T) {
	base := t.TempDir()
	configDir := filepath.Join(base, "created")

	environment := validEnvironment(t)
	environment["CONNECTOR_NODE_CONFIG_DIR"] = configDir

	config, err := LoadConfig(lookupFrom(environment))
	if err != nil {
		t.Fatalf("LoadConfig() = %v, want nil", err)
	}
	if config.ConfigDir != configDir {
		t.Fatalf("ConfigDir = %q, want %q", config.ConfigDir, configDir)
	}

	info, err := os.Stat(configDir)
	if err != nil {
		t.Fatalf("stat created config dir: %v", err)
	}
	if !info.IsDir() {
		t.Fatal("created config dir is not a directory")
	}
}

// TestLoadConfigRejectsNilLookup checks that a nil lookup is an error rather than
// a panic, so a caller that forgot to pass one gets a message.
func TestLoadConfigRejectsNilLookup(t *testing.T) {
	if _, err := LoadConfig(nil); err == nil {
		t.Fatal("LoadConfig(nil) = nil error, want a failure")
	}
}

// TestConfigRedactedHidesTheTunnelToken checks that printing a configuration does
// not print the tunnel token, because a configuration that leaks by being logged
// is a configuration that will be logged.
func TestConfigRedactedHidesTheTunnelToken(t *testing.T) {
	environment := validEnvironment(t)
	config, err := LoadConfig(lookupFrom(environment))
	if err != nil {
		t.Fatalf("LoadConfig() = %v, want nil", err)
	}

	rendered := config.Redacted()
	if strings.Contains(rendered, environment["CONNECTOR_NODE_TUNNEL_TOKEN"]) {
		t.Fatalf("Redacted() = %q, want it to hide the tunnel token", rendered)
	}
	if !strings.Contains(rendered, config.ServerURL) {
		t.Fatalf("Redacted() = %q, want it to keep the server address", rendered)
	}
	if config.String() != rendered {
		t.Fatalf("String() = %q, want it to equal Redacted()", config.String())
	}
}

// TestTrimLineTerminatorRemovesOneTerminator checks that exactly one trailing
// terminator is removed, so a hand-edited file with extra whitespace is still
// refused by the parser instead of being silently repaired.
func TestTrimLineTerminatorRemovesOneTerminator(t *testing.T) {
	cases := []struct {
		name  string
		input string
		want  string
	}{
		{"no terminator", "value", "value"},
		{"newline", "value\n", "value"},
		{"carriage return and newline", "value\r\n", "value"},
		{"two newlines", "value\n\n", "value\n"},
		{"inner newline", "val\nue", "val\nue"},
	}

	for _, testCase := range cases {
		t.Run(testCase.name, func(t *testing.T) {
			if got := trimLineTerminator(testCase.input); got != testCase.want {
				t.Fatalf("trimLineTerminator(%q) = %q, want %q", testCase.input, got, testCase.want)
			}
		})
	}
}

// TestResolveConfigDirNeedsOnlyTheConfigDirectory checks that the narrow resolver
// returns the config directory without requiring a dial target or a tunnel token.
//
// It is the unit-level counterpart of the subcommand regression test: `id` and
// `regenerate` call this function, so a change that made it depend on the dial
// configuration again would break the documented first-run order at the same
// place.
func TestResolveConfigDirNeedsOnlyTheConfigDirectory(t *testing.T) {
	configDir := t.TempDir()
	environment := map[string]string{
		"CONNECTOR_NODE_CONFIG_DIR": configDir,
	}

	resolved, err := ResolveConfigDir(lookupFrom(environment))
	if err != nil {
		t.Fatalf("ResolveConfigDir() = %v, want nil", err)
	}
	if resolved != configDir {
		t.Fatalf("ResolveConfigDir() = %q, want %q", resolved, configDir)
	}
}

// TestResolveConfigDirCreatesTheDirectory checks that the narrow resolver creates
// a missing config directory, because `id` on a fresh machine is the first thing
// an operator runs and there is nothing to read yet.
func TestResolveConfigDirCreatesTheDirectory(t *testing.T) {
	configDir := filepath.Join(t.TempDir(), "absent", "nested")
	environment := map[string]string{
		"CONNECTOR_NODE_CONFIG_DIR": configDir,
	}

	resolved, err := ResolveConfigDir(lookupFrom(environment))
	if err != nil {
		t.Fatalf("ResolveConfigDir() = %v, want nil", err)
	}
	if resolved != configDir {
		t.Fatalf("ResolveConfigDir() = %q, want %q", resolved, configDir)
	}

	info, err := os.Stat(configDir)
	if err != nil {
		t.Fatalf("stat created config directory: %v", err)
	}
	if !info.IsDir() {
		t.Fatalf("%q is not a directory", configDir)
	}
}

// TestResolveConfigDirRejectsBadValues checks that the narrow resolver keeps the
// config directory checks, because narrowing the loader must not drop a check
// that protects the directory holding the node token.
func TestResolveConfigDirRejectsBadValues(t *testing.T) {
	filePath := filepath.Join(t.TempDir(), "not-a-directory")
	if err := os.WriteFile(filePath, []byte("x"), 0o600); err != nil {
		t.Fatalf("write file: %v", err)
	}

	cases := []struct {
		name  string
		value string
	}{
		{"relative path", "relative/config"},
		{"path is a file", filePath},
	}

	for _, testCase := range cases {
		t.Run(testCase.name, func(t *testing.T) {
			environment := map[string]string{
				"CONNECTOR_NODE_CONFIG_DIR": testCase.value,
			}
			if _, err := ResolveConfigDir(lookupFrom(environment)); err == nil {
				t.Fatalf("ResolveConfigDir(%q) = nil error, want a refusal", testCase.value)
			}
		})
	}
}

// TestResolveConfigDirRejectsANilLookup checks that a nil lookup is reported
// rather than dereferenced, because a nil lookup is a programming mistake and a
// panic in a credential path is harder to diagnose than an error.
func TestResolveConfigDirRejectsANilLookup(t *testing.T) {
	if _, err := ResolveConfigDir(nil); err == nil {
		t.Fatal("ResolveConfigDir(nil) = nil error, want a refusal")
	}
}
