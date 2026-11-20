package main

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
)

// environmentFrom builds a lookup over a fixed map, so a test states the
// environment it means instead of mutating the process's own.
func environmentFrom(values map[string]string) func(string) string {
	return func(key string) string {
		return values[key]
	}
}

// writeEnvFile writes a dotenv file into the test's temporary directory and
// returns its absolute path.
func writeEnvFile(t *testing.T, content string) string {
	t.Helper()
	path := filepath.Join(t.TempDir(), "node.env")
	if err := os.WriteFile(path, []byte(content), 0o600); err != nil {
		t.Fatalf("write %s: %v", path, err)
	}
	return path
}

// TestOverrideFlagSetKeepsAnEqualsInsideTheValue proves the split is on the
// first `=` only. A secret may contain one, and a split on the last would
// truncate it into a value that never authenticates.
func TestOverrideFlagSetKeepsAnEqualsInsideTheValue(t *testing.T) {
	overrides := overrideFlag{}
	if err := overrides.Set("CONNECTOR_NODE_TUNNEL_TOKEN=abc=def"); err != nil {
		t.Fatalf("Set: %v", err)
	}
	if got := overrides["CONNECTOR_NODE_TUNNEL_TOKEN"]; got != "abc=def" {
		t.Fatalf("value is %q, want %q", got, "abc=def")
	}
}

// TestOverrideFlagSetRefusesAPairWithoutEquals proves a bare key is refused
// rather than read as an empty value, because an empty value is the same as
// unset and the operator would see the compiled-in value win without a message.
func TestOverrideFlagSetRefusesAPairWithoutEquals(t *testing.T) {
	overrides := overrideFlag{}
	err := overrides.Set("CONNECTOR_NODE_TUNNEL_TOKEN")
	if err == nil {
		t.Fatal("Set accepted a pair with no =")
	}
	if !strings.Contains(err.Error(), "has no =") {
		t.Fatalf("error is %q, want it to say the pair has no =", err)
	}
}

// TestOverrideFlagSetRefusesAnInvalidKey proves the key rule is applied, so a
// pair that could never be looked up is refused at the command line rather than
// silently ignored.
func TestOverrideFlagSetRefusesAnInvalidKey(t *testing.T) {
	cases := map[string]string{
		"empty":             "=value",
		"starts with digit": "1KEY=value",
		"contains a dash":   "CONNECTOR-NODE=value",
		"contains a space":  "CONNECTOR NODE=value",
	}
	for name, pair := range cases {
		t.Run(name, func(t *testing.T) {
			overrides := overrideFlag{}
			if err := overrides.Set(pair); err == nil {
				t.Fatalf("Set accepted %q", pair)
			}
		})
	}
}

// TestOverrideFlagStringNeverPrintsAValue proves the flag package's error
// messages cannot echo a secret. A --set argument may carry a tunnel token, and
// a usage error that printed it would write a secret to stderr.
func TestOverrideFlagStringNeverPrintsAValue(t *testing.T) {
	overrides := overrideFlag{}
	if err := overrides.Set("CONNECTOR_NODE_TUNNEL_TOKEN=super-secret-value"); err != nil {
		t.Fatalf("Set: %v", err)
	}
	rendered := overrides.String()
	if strings.Contains(rendered, "super-secret-value") {
		t.Fatalf("String() printed the value: %q", rendered)
	}
	if !strings.Contains(rendered, "CONNECTOR_NODE_TUNNEL_TOKEN") {
		t.Fatalf("String() is %q, want it to name the key", rendered)
	}
}

// TestResolveEnvFilePrefersTheFlag proves the flag wins over the variable, which
// is the same order the argument layer wins everywhere else.
func TestResolveEnvFilePrefersTheFlag(t *testing.T) {
	environment := environmentFrom(map[string]string{
		envFileVariable: "/from/the/variable.env",
	})
	got, err := resolveEnvFile("/from/the/flag.env", environment)
	if err != nil {
		t.Fatalf("resolveEnvFile: %v", err)
	}
	if got != "/from/the/flag.env" {
		t.Fatalf("path is %q, want the flag's path", got)
	}
}

// TestResolveEnvFileFallsBackToTheVariable proves the variable is read when the
// flag is absent, so an operator can export it once for a service manager.
func TestResolveEnvFileFallsBackToTheVariable(t *testing.T) {
	environment := environmentFrom(map[string]string{
		envFileVariable: "/from/the/variable.env",
	})
	got, err := resolveEnvFile("", environment)
	if err != nil {
		t.Fatalf("resolveEnvFile: %v", err)
	}
	if got != "/from/the/variable.env" {
		t.Fatalf("path is %q, want the variable's path", got)
	}
}

// TestResolveEnvFileReturnsNothingWhenNeitherIsSet proves the absence of both
// sources is not an error, so a deployment that names no file behaves exactly as
// it did before the flag existed.
func TestResolveEnvFileReturnsNothingWhenNeitherIsSet(t *testing.T) {
	got, err := resolveEnvFile("", environmentFrom(nil))
	if err != nil {
		t.Fatalf("resolveEnvFile: %v", err)
	}
	if got != "" {
		t.Fatalf("path is %q, want empty", got)
	}
}

// TestResolveEnvFileRefusesARelativePath proves the rule the six existing path
// variables already follow: a relative path resolves differently per launch.
func TestResolveEnvFileRefusesARelativePath(t *testing.T) {
	_, err := resolveEnvFile("node.env", environmentFrom(nil))
	if err == nil {
		t.Fatal("resolveEnvFile accepted a relative path")
	}
	if !strings.Contains(err.Error(), "is relative") {
		t.Fatalf("error is %q, want it to say the path is relative", err)
	}
}

// TestLoadEnvFileReturnsNothingForAnEmptyPath proves no path means no file, so
// the caller does not have to special-case the absent source.
func TestLoadEnvFileReturnsNothingForAnEmptyPath(t *testing.T) {
	values, err := loadEnvFile("")
	if err != nil {
		t.Fatalf("loadEnvFile: %v", err)
	}
	if values != nil {
		t.Fatalf("values are %v, want nil", values)
	}
}

// TestLoadEnvFileRefusesAMissingFile proves a named file that does not exist is
// an error. envfile.Load treats a missing file as empty, which is right for a
// default location and wrong here: a typo would silently fall through to the
// compiled-in values and the operator would believe a configuration is in force
// that was never read.
func TestLoadEnvFileRefusesAMissingFile(t *testing.T) {
	path := filepath.Join(t.TempDir(), "absent.env")
	_, err := loadEnvFile(path)
	if err == nil {
		t.Fatal("loadEnvFile accepted a path that does not exist")
	}
	if !strings.Contains(err.Error(), path) {
		t.Fatalf("error is %q, want it to name %q", err, path)
	}
}

// TestLoadEnvFileAcceptsAFileHoldingOnlyComments proves an existing file with no
// pairs is a legitimate empty configuration rather than a missing one. The two
// produce the same empty map, so the distinction is made by probing the path.
func TestLoadEnvFileAcceptsAFileHoldingOnlyComments(t *testing.T) {
	path := writeEnvFile(t, "# nothing is configured here\n")
	values, err := loadEnvFile(path)
	if err != nil {
		t.Fatalf("loadEnvFile: %v", err)
	}
	if len(values) != 0 {
		t.Fatalf("values are %v, want empty", values)
	}
}

// TestLoadEnvFileRefusesAMalformedFile proves a file that cannot be parsed is
// refused with the path named, so the operator knows which file to fix.
func TestLoadEnvFileRefusesAMalformedFile(t *testing.T) {
	path := writeEnvFile(t, "not a pair\n")
	_, err := loadEnvFile(path)
	if err == nil {
		t.Fatal("loadEnvFile accepted a malformed file")
	}
	if !strings.Contains(err.Error(), path) {
		t.Fatalf("error is %q, want it to name %q", err, path)
	}
}

// TestLayeredLookupArgumentBeatsEnvironment proves the most specific layer wins.
func TestLayeredLookupArgumentBeatsEnvironment(t *testing.T) {
	lookup := layeredLookup(
		map[string]string{"CONNECTOR_NODE_SERVER_URL": "ws://from-argument/channel"},
		environmentFrom(map[string]string{"CONNECTOR_NODE_SERVER_URL": "ws://from-environment/channel"}),
		map[string]string{"CONNECTOR_NODE_SERVER_URL": "ws://from-file/channel"},
	)
	if got := lookup("CONNECTOR_NODE_SERVER_URL"); got != "ws://from-argument/channel" {
		t.Fatalf("value is %q, want the argument's value", got)
	}
}

// TestLayeredLookupEnvironmentBeatsFile proves the ambient layer beats the file,
// so an operator can override one installation's default without editing it.
func TestLayeredLookupEnvironmentBeatsFile(t *testing.T) {
	lookup := layeredLookup(
		nil,
		environmentFrom(map[string]string{"CONNECTOR_NODE_SERVER_URL": "ws://from-environment/channel"}),
		map[string]string{"CONNECTOR_NODE_SERVER_URL": "ws://from-file/channel"},
	)
	if got := lookup("CONNECTOR_NODE_SERVER_URL"); got != "ws://from-environment/channel" {
		t.Fatalf("value is %q, want the environment's value", got)
	}
}

// TestLayeredLookupFallsThroughToTheFile proves the file is read when neither
// more specific layer supplies a value.
func TestLayeredLookupFallsThroughToTheFile(t *testing.T) {
	lookup := layeredLookup(
		nil,
		environmentFrom(nil),
		map[string]string{"CONNECTOR_NODE_SERVER_URL": "ws://from-file/channel"},
	)
	if got := lookup("CONNECTOR_NODE_SERVER_URL"); got != "ws://from-file/channel" {
		t.Fatalf("value is %q, want the file's value", got)
	}
}

// TestLayeredLookupTreatsAnEmptyValueAsUnset proves an exported but empty
// variable does not shadow a file that holds a value. Without this rule the
// operator would see a Node start with a value they did not write.
func TestLayeredLookupTreatsAnEmptyValueAsUnset(t *testing.T) {
	lookup := layeredLookup(
		map[string]string{"CONNECTOR_NODE_SERVER_URL": ""},
		environmentFrom(map[string]string{"CONNECTOR_NODE_SERVER_URL": ""}),
		map[string]string{"CONNECTOR_NODE_SERVER_URL": "ws://from-file/channel"},
	)
	if got := lookup("CONNECTOR_NODE_SERVER_URL"); got != "ws://from-file/channel" {
		t.Fatalf("value is %q, want the file's value because the empty layers are unset", got)
	}
}

// TestLayeredLookupReturnsEmptyForAnUnknownKey proves a key no layer defines is
// empty rather than a panic, so LoadConfig's own default handling is reached.
func TestLayeredLookupReturnsEmptyForAnUnknownKey(t *testing.T) {
	lookup := layeredLookup(nil, environmentFrom(nil), nil)
	if got := lookup("CONNECTOR_NODE_NOT_A_KEY"); got != "" {
		t.Fatalf("value is %q, want empty", got)
	}
}

// TestValidateOverrideArgumentsNeverEchoesAValue proves the pre-pass exists for the
// reason it exists: the flag package wraps a Set failure as
// `invalid value "<the whole argument>" for flag -set`, so a rejected pair reaches
// stderr verbatim. Measured before the pre-pass: `--set BAD-KEY=super-secret-value`
// printed the secret. A --set argument may carry a tunnel token.
func TestValidateOverrideArgumentsNeverEchoesAValue(t *testing.T) {
	err := validateOverrideArguments([]string{"--set", "BAD-KEY=super-secret-value"})
	if err == nil {
		t.Fatal("validateOverrideArguments accepted an invalid key")
	}
	if strings.Contains(err.Error(), "super-secret-value") {
		t.Fatalf("the error echoed the value: %q", err)
	}
	if !strings.Contains(err.Error(), "BAD-KEY") {
		t.Fatalf("the error is %q, want it to name the key", err)
	}
}

// TestValidateOverrideArgumentsAcceptsEverySpellingTheFlagPackageDoes proves the
// pre-pass recognises the forms the flag package accepts, so a valid pair is not
// refused by a scan that only knew one spelling.
func TestValidateOverrideArgumentsAcceptsEverySpellingTheFlagPackageDoes(t *testing.T) {
	cases := [][]string{
		{"--set", "KEY=value"},
		{"-set", "KEY=value"},
		{"--set=KEY=value"},
		{"-set=KEY=value"},
		{"--console", "--set", "KEY=value"},
	}
	for _, arguments := range cases {
		if err := validateOverrideArguments(arguments); err != nil {
			t.Errorf("validateOverrideArguments(%v): %v", arguments, err)
		}
	}
}

// TestValidateOverrideArgumentsLeavesOtherArgumentsAlone proves the scan does not
// decide what a flag is. An argument that merely looks like a pair is not one.
func TestValidateOverrideArgumentsLeavesOtherArgumentsAlone(t *testing.T) {
	cases := [][]string{
		{"--console"},
		{"--env-file", "/abs/path.env"},
		{"--setx", "KEY=value"},
		{"positional"},
	}
	for _, arguments := range cases {
		if err := validateOverrideArguments(arguments); err != nil {
			t.Errorf("validateOverrideArguments(%v): %v", arguments, err)
		}
	}
}

// TestValidateOverrideArgumentsRefusesAPairWithoutEquals proves the pre-pass applies
// the same rule as Set, so the two cannot disagree about what a valid pair is.
func TestValidateOverrideArgumentsRefusesAPairWithoutEquals(t *testing.T) {
	if err := validateOverrideArguments([]string{"--set", "KEY"}); err == nil {
		t.Fatal("validateOverrideArguments accepted a pair with no =")
	}
}

// TestValidateOverrideArgumentsRefusesAMissingValue proves a trailing --set is
// refused rather than read as an empty pair.
func TestValidateOverrideArgumentsRefusesAMissingValue(t *testing.T) {
	if err := validateOverrideArguments([]string{"--set"}); err == nil {
		t.Fatal("validateOverrideArguments accepted a --set with no argument")
	}
}

// TestRunRefusesAnInvalidSetWithoutEchoingTheValue proves the pre-pass is wired into
// the run subcommand, not merely defined.
//
// The unit test above exercises validateOverrideArguments directly, so it stays green
// when the call is deleted from runNodeWithOutput. This test drives the real entry
// point and reads the message it returns, which is the only way to observe the wiring.
// Measured: with the call removed, the flag package echoed the value and this test
// failed.
func TestRunRefusesAnInvalidSetWithoutEchoingTheValue(t *testing.T) {
	var buffer strings.Builder
	err := runNodeWithOutput(
		[]string{"--set", "BAD-KEY=super-secret-value"},
		nil,
		&buffer,
		false,
	)
	if err == nil {
		t.Fatal("runNodeWithOutput accepted an invalid --set key")
	}
	message := err.Error()
	if strings.Contains(message, "super-secret-value") {
		t.Fatalf("the refusal echoed the value: %q", message)
	}
	if !strings.Contains(message, "BAD-KEY") {
		t.Fatalf("the refusal is %q, want it to name the key", message)
	}
}
