package main

import (
	"strings"
	"testing"
)

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

func TestCLIEnvironmentValueReportsSelectedDeprecatedName(t *testing.T) {
	lookup := lookupFrom(map[string]string{deprecatedTokenEnv: "old-token"})
	var diagnostics strings.Builder
	if got := cliEnvironmentValueWithDiagnostics(lookup, &diagnostics, cliTokenEnv, deprecatedTokenEnv); got != "old-token" {
		t.Fatalf("CLI environment value = %q", got)
	}
	want := "warning: " + deprecatedTokenEnv + " is deprecated; use " + cliTokenEnv + "\n"
	if got := diagnostics.String(); got != want {
		t.Fatalf("diagnostics=%q want=%q", got, want)
	}
}

func TestCLIEnvironmentValueDoesNotReportIgnoredDeprecatedName(t *testing.T) {
	lookup := lookupFrom(map[string]string{cliTokenEnv: "new-token", deprecatedTokenEnv: "old-token"})
	var diagnostics strings.Builder
	if got := cliEnvironmentValueWithDiagnostics(lookup, &diagnostics, cliTokenEnv, deprecatedTokenEnv); got != "new-token" {
		t.Fatalf("CLI environment value = %q", got)
	}
	if got := diagnostics.String(); got != "" {
		t.Fatalf("diagnostics=%q want empty", got)
	}
}
