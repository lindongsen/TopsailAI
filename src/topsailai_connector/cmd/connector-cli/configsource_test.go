package main

import (
	"bytes"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

// environmentFrom returns a lookup over a fixed map, so a test states the environment
// it means instead of mutating the process.
func environmentFrom(values map[string]string) func(string) string {
	return func(key string) string { return values[key] }
}

// writeConfigurationFile writes a dotenv file and returns its absolute path.
func writeConfigurationFile(t *testing.T, content string) string {
	t.Helper()
	path := filepath.Join(t.TempDir(), "cli.env")
	if err := os.WriteFile(path, []byte(content), 0o600); err != nil {
		t.Fatalf("write %s: %v", path, err)
	}
	return path
}

// TestOverrideFlagKeepsAnEqualsInsideTheValue checks that a credential containing an
// equals sign survives, because the split is on the first one.
func TestOverrideFlagKeepsAnEqualsInsideTheValue(t *testing.T) {
	overrides := overrideFlag{}
	if err := overrides.set("CONNECTOR_CLI_CLIENT_CREDENTIAL=key_id.sec=ret"); err != nil {
		t.Fatalf("set: %v", err)
	}
	if got := overrides["CONNECTOR_CLI_CLIENT_CREDENTIAL"]; got != "key_id.sec=ret" {
		t.Fatalf("value = %q, want %q", got, "key_id.sec=ret")
	}
}

// TestOverrideFlagRefusesAPairWithoutEquals checks that a pair with no separator is
// refused rather than stored under a name nothing reads.
func TestOverrideFlagRefusesAPairWithoutEquals(t *testing.T) {
	overrides := overrideFlag{}
	err := overrides.set("NOEQUALS")
	if err == nil {
		t.Fatal("set(NOEQUALS) = nil error, want a refusal")
	}
	if !strings.Contains(err.Error(), "has no =") {
		t.Fatalf("error = %q, want it to say the pair has no =", err)
	}
}

// TestOverrideFlagRefusesAnInvalidKey checks every shape that is not an environment
// variable name.
func TestOverrideFlagRefusesAnInvalidKey(t *testing.T) {
	testCases := []struct {
		name string
		pair string
	}{
		{"empty key", "=value"},
		{"starts with a digit", "1KEY=value"},
		{"contains a dash", "BAD-KEY=value"},
		{"contains a space", "BAD KEY=value"},
	}
	for _, testCase := range testCases {
		t.Run(testCase.name, func(t *testing.T) {
			overrides := overrideFlag{}
			if err := overrides.set(testCase.pair); err == nil {
				t.Fatalf("set(%q) = nil error, want a refusal", testCase.pair)
			}
		})
	}
}

// TestOverrideFlagStringNeverPrintsAValue checks that the flag package's error
// messages cannot echo a credential. A --set argument may carry one, and a usage error
// is the one place a secret must not reach.
func TestOverrideFlagStringNeverPrintsAValue(t *testing.T) {
	overrides := overrideFlag{}
	if err := overrides.set("CONNECTOR_CLI_NODE_CREDENTIAL=key_id.super-secret-value"); err != nil {
		t.Fatalf("set: %v", err)
	}
	rendered := overrides.String()
	if strings.Contains(rendered, "super-secret-value") {
		t.Fatalf("String() = %q, want it to omit the value", rendered)
	}
	if !strings.Contains(rendered, "CONNECTOR_CLI_NODE_CREDENTIAL") {
		t.Fatalf("String() = %q, want it to name the key", rendered)
	}
}

// TestExtractConfigurationArgumentsRemovesBothFlags checks that the shared cli package
// never sees a flag it does not register, and that the operation survives.
func TestExtractConfigurationArgumentsRemovesBothFlags(t *testing.T) {
	arguments := []string{
		"--env-file", "/etc/cli.env",
		"--set", "CONNECTOR_CLI_SCOPE=project",
		"--scope", "project",
		"file.list",
	}
	result, err := extractConfigurationArguments(arguments)
	if err != nil {
		t.Fatalf("extractConfigurationArguments: %v", err)
	}
	if result.envFile != "/etc/cli.env" {
		t.Fatalf("envFile = %q, want %q", result.envFile, "/etc/cli.env")
	}
	if got := result.overrides["CONNECTOR_CLI_SCOPE"]; got != "project" {
		t.Fatalf("override = %q, want %q", got, "project")
	}
	wanted := []string{"--scope", "project", "file.list"}
	if len(result.remaining) != len(wanted) {
		t.Fatalf("remaining = %#v, want %#v", result.remaining, wanted)
	}
	for index, value := range wanted {
		if result.remaining[index] != value {
			t.Fatalf("remaining[%d] = %q, want %q", index, result.remaining[index], value)
		}
	}
}

// TestExtractConfigurationArgumentsAcceptsEverySpelling checks the four forms Go's
// flag package accepts for each flag, so a caller who writes one of them is not told
// the flag does not exist.
func TestExtractConfigurationArgumentsAcceptsEverySpelling(t *testing.T) {
	testCases := []struct {
		name      string
		arguments []string
		wantFile  string
		wantScope string
	}{
		{"separate values", []string{"--env-file", "/a.env", "--set", "CONNECTOR_CLI_SCOPE=s", "file.list"}, "/a.env", "s"},
		{"double dash equals", []string{"--env-file=/a.env", "--set=CONNECTOR_CLI_SCOPE=s", "file.list"}, "/a.env", "s"},
		{"single dash equals", []string{"-env-file=/a.env", "-set=CONNECTOR_CLI_SCOPE=s", "file.list"}, "/a.env", "s"},
		{"single dash separate", []string{"-env-file", "/a.env", "-set", "CONNECTOR_CLI_SCOPE=s", "file.list"}, "/a.env", "s"},
	}
	for _, testCase := range testCases {
		t.Run(testCase.name, func(t *testing.T) {
			result, err := extractConfigurationArguments(testCase.arguments)
			if err != nil {
				t.Fatalf("extractConfigurationArguments: %v", err)
			}
			if result.envFile != testCase.wantFile {
				t.Fatalf("envFile = %q, want %q", result.envFile, testCase.wantFile)
			}
			if got := result.overrides["CONNECTOR_CLI_SCOPE"]; got != testCase.wantScope {
				t.Fatalf("override = %q, want %q", got, testCase.wantScope)
			}
		})
	}
}

// TestExtractConfigurationArgumentsLeavesOtherArgumentsAlone checks that a flag this
// function does not own is passed through, so the shared package still decides what a
// flag is.
func TestExtractConfigurationArgumentsLeavesOtherArgumentsAlone(t *testing.T) {
	arguments := []string{"--scope", "project", "--path", "a.txt", "file.read"}
	result, err := extractConfigurationArguments(arguments)
	if err != nil {
		t.Fatalf("extractConfigurationArguments: %v", err)
	}
	if len(result.remaining) != len(arguments) {
		t.Fatalf("remaining = %#v, want %#v", result.remaining, arguments)
	}
}

// TestExtractConfigurationArgumentsRefusesAMissingValue checks that a flag at the end
// of the line is refused rather than silently consuming nothing.
func TestExtractConfigurationArgumentsRefusesAMissingValue(t *testing.T) {
	for _, arguments := range [][]string{{"--env-file"}, {"--set"}} {
		if _, err := extractConfigurationArguments(arguments); err == nil {
			t.Fatalf("extractConfigurationArguments(%#v) = nil error, want a refusal", arguments)
		}
	}
}

// TestExtractConfigurationArgumentsNeverEchoesAValue checks that a rejected pair does
// not print the credential it carried. The flag package would echo the whole argument
// as `invalid value "<the whole argument>"`, which is why the pair is validated here.
func TestExtractConfigurationArgumentsNeverEchoesAValue(t *testing.T) {
	arguments := []string{"--set", "BAD-KEY=super-secret-value", "file.list"}
	_, err := extractConfigurationArguments(arguments)
	if err == nil {
		t.Fatal("extractConfigurationArguments = nil error, want a refusal")
	}
	if strings.Contains(err.Error(), "super-secret-value") {
		t.Fatalf("error = %q, want it to omit the value", err)
	}
	if !strings.Contains(err.Error(), "BAD-KEY") {
		t.Fatalf("error = %q, want it to name the key", err)
	}
}

// TestResolveConfigurationPathPrefersTheFlag checks that the flag wins over the
// variable, because it is the more specific statement.
func TestResolveConfigurationPathPrefersTheFlag(t *testing.T) {
	environment := environmentFrom(map[string]string{"CONNECTOR_CLI_ENV_FILE": "/from-variable.env"})
	path, named, err := resolveConfigurationPath("/from-flag.env", environment)
	if err != nil {
		t.Fatalf("resolveConfigurationPath: %v", err)
	}
	if path != "/from-flag.env" {
		t.Fatalf("path = %q, want %q", path, "/from-flag.env")
	}
	if !named {
		t.Fatal("named = false, want true for a path the caller typed")
	}
}

// TestResolveConfigurationPathFallsBackToTheVariable checks that the variable is used
// when the flag is absent, and that it is not treated as a path the caller named.
func TestResolveConfigurationPathFallsBackToTheVariable(t *testing.T) {
	environment := environmentFrom(map[string]string{"CONNECTOR_CLI_ENV_FILE": "/from-variable.env"})
	path, named, err := resolveConfigurationPath("", environment)
	if err != nil {
		t.Fatalf("resolveConfigurationPath: %v", err)
	}
	if path != "/from-variable.env" {
		t.Fatalf("path = %q, want %q", path, "/from-variable.env")
	}
	if named {
		t.Fatal("named = true, want false for a path the variable supplied")
	}
}

// TestResolveConfigurationPathRefusesARelativeFlag checks that a relative path is
// refused, because it resolves differently per launch.
func TestResolveConfigurationPathRefusesARelativeFlag(t *testing.T) {
	_, _, err := resolveConfigurationPath("cli.env", environmentFrom(nil))
	if err == nil {
		t.Fatal("resolveConfigurationPath(cli.env) = nil error, want a refusal")
	}
	if !strings.Contains(err.Error(), "is relative") {
		t.Fatalf("error = %q, want it to say the path is relative", err)
	}
}

// TestLoadConfigurationFileRefusesAMissingNamedFile checks that a file the caller
// named must exist. A typo would otherwise fall through to the environment and the
// caller would believe a configuration is in force that was never read.
func TestLoadConfigurationFileRefusesAMissingNamedFile(t *testing.T) {
	path := filepath.Join(t.TempDir(), "absent.env")
	_, err := loadConfigurationFile(path, true)
	if err == nil {
		t.Fatal("loadConfigurationFile(absent, named) = nil error, want a refusal")
	}
	if !strings.Contains(err.Error(), path) {
		t.Fatalf("error = %q, want it to name %q", err, path)
	}
}

// TestLoadConfigurationFileToleratesAMissingUnnamedFile checks that the historical
// behaviour is unchanged: a file the caller did not name may be absent, because the
// default location is a convenience and CONNECTOR_CLI_ENV_FILE predates the flag.
func TestLoadConfigurationFileToleratesAMissingUnnamedFile(t *testing.T) {
	path := filepath.Join(t.TempDir(), "absent.env")
	values, err := loadConfigurationFile(path, false)
	if err != nil {
		t.Fatalf("loadConfigurationFile(absent, unnamed): %v", err)
	}
	if len(values) != 0 {
		t.Fatalf("values = %#v, want an empty map", values)
	}
}

// TestLoadConfigurationFileAcceptsAFileHoldingOnlyComments checks that an existing
// file with no pairs is not mistaken for a missing one. The probe is a stat rather
// than a length check for exactly this case.
func TestLoadConfigurationFileAcceptsAFileHoldingOnlyComments(t *testing.T) {
	path := writeConfigurationFile(t, "# nothing here\n\n")
	values, err := loadConfigurationFile(path, true)
	if err != nil {
		t.Fatalf("loadConfigurationFile: %v", err)
	}
	if len(values) != 0 {
		t.Fatalf("values = %#v, want an empty map", values)
	}
}

// TestLayeredLookupArgumentBeatsEnvironment checks the first boundary.
func TestLayeredLookupArgumentBeatsEnvironment(t *testing.T) {
	lookup := layeredLookup(
		overrideFlag{"CONNECTOR_CLI_SCOPE": "from-argument"},
		environmentFrom(map[string]string{"CONNECTOR_CLI_SCOPE": "from-environment"}),
		map[string]string{"CONNECTOR_CLI_SCOPE": "from-file"},
	)
	if got := lookup("CONNECTOR_CLI_SCOPE"); got != "from-argument" {
		t.Fatalf("lookup = %q, want %q", got, "from-argument")
	}
}

// TestLayeredLookupEnvironmentBeatsFile checks the second boundary.
func TestLayeredLookupEnvironmentBeatsFile(t *testing.T) {
	lookup := layeredLookup(
		overrideFlag{},
		environmentFrom(map[string]string{"CONNECTOR_CLI_SCOPE": "from-environment"}),
		map[string]string{"CONNECTOR_CLI_SCOPE": "from-file"},
	)
	if got := lookup("CONNECTOR_CLI_SCOPE"); got != "from-environment" {
		t.Fatalf("lookup = %q, want %q", got, "from-environment")
	}
}

// TestLayeredLookupFallsThroughToTheFile checks the last layer.
func TestLayeredLookupFallsThroughToTheFile(t *testing.T) {
	lookup := layeredLookup(
		overrideFlag{},
		environmentFrom(nil),
		map[string]string{"CONNECTOR_CLI_SCOPE": "from-file"},
	)
	if got := lookup("CONNECTOR_CLI_SCOPE"); got != "from-file" {
		t.Fatalf("lookup = %q, want %q", got, "from-file")
	}
}

// TestLayeredLookupTreatsAnEmptyValueAsUnset checks that an exported but empty
// variable does not shadow a file that holds a value.
func TestLayeredLookupTreatsAnEmptyValueAsUnset(t *testing.T) {
	lookup := layeredLookup(
		overrideFlag{"CONNECTOR_CLI_SCOPE": ""},
		environmentFrom(map[string]string{"CONNECTOR_CLI_SCOPE": ""}),
		map[string]string{"CONNECTOR_CLI_SCOPE": "from-file"},
	)
	if got := lookup("CONNECTOR_CLI_SCOPE"); got != "from-file" {
		t.Fatalf("lookup = %q, want %q", got, "from-file")
	}
}

// TestLayeredLookupReturnsEmptyForAnUnknownKey checks that a key no source supplies
// reads as empty rather than as a zero value that looks configured.
func TestLayeredLookupReturnsEmptyForAnUnknownKey(t *testing.T) {
	lookup := layeredLookup(overrideFlag{}, environmentFrom(nil), nil)
	if got := lookup("CONNECTOR_CLI_UNKNOWN"); got != "" {
		t.Fatalf("lookup = %q, want an empty string", got)
	}
}

// TestRunRefusesAnInvalidSetWithoutEchoingTheValue checks the whole process, because
// the pre-pass and the message prefix are two halves of one behaviour: a unit test of
// the pre-pass alone would not prove the secret stays out of the output.
func TestRunRefusesAnInvalidSetWithoutEchoingTheValue(t *testing.T) {
	var stdout, stderr bytes.Buffer
	status := runWithOutput(
		[]string{"connector-cli", "--set", "BAD-KEY=super-secret-value", "file.list"},
		&stdout, &stderr,
	)
	if status != 2 {
		t.Fatalf("status = %d, want 2", status)
	}

	// The status alone cannot prove the secret stayed out of the output: a program
	// that echoes the credential and exits 2 has the right status and the wrong
	// behaviour. The value must be absent from both streams.
	combined := stdout.String() + stderr.String()
	if strings.Contains(combined, "super-secret-value") {
		t.Fatalf("the output echoes the value of a rejected --set pair: %q", combined)
	}
	if !strings.Contains(combined, "BAD-KEY") {
		t.Fatalf("the output does not name the rejected key, so the caller cannot fix it: %q", combined)
	}
}

// TestRunAcceptsTheConfigurationFlags checks that the two flags do not make the
// command line invalid. Every required value is supplied, so the only remaining
// failure is the unreachable Server, which is a different status from a rejected
// command line.
func TestRunAcceptsTheConfigurationFlags(t *testing.T) {
	path := writeConfigurationFile(t, "CONNECTOR_CLI_SERVER_URL=http://127.0.0.1:1\n")
	status := run([]string{
		"connector-cli",
		"--env-file", path,
		"--set", "CONNECTOR_CLI_NODE_ID=node_aaaaaaaaaaaaaaaaaaaaaaaaaa",
		"--set", "CONNECTOR_CLI_CLIENT_CREDENTIAL=caller." + strings.Repeat("a", 32),
		"--set", "CONNECTOR_CLI_NODE_CREDENTIAL=caller." + strings.Repeat("b", 32),
		"--scope", "project",
		"--path", "a.txt",
		"file.read",
	})
	if status == 2 {
		t.Fatal("status = 2, want the command line to be accepted")
	}
}
