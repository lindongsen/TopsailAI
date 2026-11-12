package main

import "testing"

func TestCLIEnvironmentValuePrefersComponentName(t *testing.T) {
	lookup := lookupFrom(map[string]string{
		cliServerURLEnv:        "https://new.example.test",
		deprecatedServerURLEnv: "https://old.example.test",
	})
	if got := cliEnvironmentValue(lookup, cliServerURLEnv, deprecatedServerURLEnv); got != "https://new.example.test" {
		t.Fatalf("CLI environment value = %q", got)
	}
}

func TestCLIEnvironmentValueUsesDeprecatedFallback(t *testing.T) {
	lookup := lookupFrom(map[string]string{deprecatedTokenEnv: "old-token"})
	if got := cliEnvironmentValue(lookup, cliTokenEnv, deprecatedTokenEnv); got != "old-token" {
		t.Fatalf("CLI environment value = %q", got)
	}
}

func TestCLIEnvironmentValueTreatsBlankPrimaryAsUnset(t *testing.T) {
	lookup := lookupFrom(map[string]string{cliTokenEnv: "   ", deprecatedTokenEnv: "old-token"})
	if got := cliEnvironmentValue(lookup, cliTokenEnv, deprecatedTokenEnv); got != "old-token" {
		t.Fatalf("CLI environment value = %q", got)
	}
}
