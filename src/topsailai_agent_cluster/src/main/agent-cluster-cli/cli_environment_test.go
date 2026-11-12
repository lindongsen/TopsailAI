package main

import (
	"testing"
)

// TestCLIEnvironmentValueReturnsConfiguredValue verifies the helper returns the
// component-owned value.
func TestCLIEnvironmentValueReturnsConfiguredValue(t *testing.T) {
	lookup := lookupFrom(map[string]string{cliServerURLEnv: "https://new.example.test"})
	if got := cliEnvironmentValue(lookup, cliServerURLEnv); got != "https://new.example.test" {
		t.Fatalf("CLI environment value = %q", got)
	}
}

// TestCLIEnvironmentValueTreatsBlankAsUnset verifies a variable exported as
// whitespace cannot override a default.
func TestCLIEnvironmentValueTreatsBlankAsUnset(t *testing.T) {
	lookup := lookupFrom(map[string]string{cliServerTokenEnv: "   "})
	if got := cliEnvironmentValue(lookup, cliServerTokenEnv); got != "" {
		t.Fatalf("CLI environment value = %q, want empty", got)
	}
}

// TestCLIEnvironmentValueIgnoresDeprecatedNames pins the removal of the
// compatibility fallback. A deprecated name must not supply a value, so an
// operator who still exports one gets the documented default instead of a
// silently different behaviour.
func TestCLIEnvironmentValueIgnoresDeprecatedNames(t *testing.T) {
	lookup := lookupFrom(map[string]string{
		"AGENT_CLUSTER_SERVER_URL":          "https://old.example.test",
		"AGENT_CLUSTER_TOKEN":               "old-token",
		"AGENT_CLUSTER_CLI_TOKEN":           "transitional-token",
		"AGENT_CLUSTER_ENDPOINT_TOKENS":     "ep1=old-token",
		"AGENT_CLUSTER_HISTORY_FILE":        "/old/history.jsonl",
		"AGENT_CLUSTER_HISTORY_MAX_ENTRIES": "70",
	})
	for _, name := range []string{
		cliServerURLEnv,
		cliServerTokenEnv,
		cliEndpointTokensEnv,
		inputHistoryFileEnv,
		inputHistoryMaxEntriesEnv,
	} {
		if got := cliEnvironmentValue(lookup, name); got != "" {
			t.Fatalf("%s = %q, want empty", name, got)
		}
	}
}
