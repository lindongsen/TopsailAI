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
	lookup := lookupFrom(map[string]string{deprecatedServerTokenEnv: "old-token"})
	if got := cliEnvironmentValue(lookup, cliServerTokenEnv, deprecatedServerTokenEnv); got != "old-token" {
		t.Fatalf("CLI environment value = %q", got)
	}
}

func TestCLIEnvironmentValueTreatsBlankPrimaryAsUnset(t *testing.T) {
	lookup := lookupFrom(map[string]string{cliServerTokenEnv: "   ", deprecatedServerTokenEnv: "old-token"})
	if got := cliEnvironmentValue(lookup, cliServerTokenEnv, deprecatedServerTokenEnv); got != "old-token" {
		t.Fatalf("CLI environment value = %q", got)
	}
}

func TestCLIEnvironmentValueReportsSelectedDeprecatedName(t *testing.T) {
	lookup := lookupFrom(map[string]string{deprecatedServerTokenEnv: "old-token"})
	var diagnostics strings.Builder
	if got := cliEnvironmentValueWithDiagnostics(lookup, &diagnostics, cliServerTokenEnv, deprecatedServerTokenEnv); got != "old-token" {
		t.Fatalf("CLI environment value = %q", got)
	}
	want := "warning: " + deprecatedServerTokenEnv + " is deprecated; use " + cliServerTokenEnv + "\n"
	if got := diagnostics.String(); got != want {
		t.Fatalf("diagnostics=%q want=%q", got, want)
	}
}

func TestCLIEnvironmentValueDoesNotReportIgnoredDeprecatedName(t *testing.T) {
	lookup := lookupFrom(map[string]string{cliServerTokenEnv: "new-token", deprecatedServerTokenEnv: "old-token"})
	var diagnostics strings.Builder
	if got := cliEnvironmentValueWithDiagnostics(lookup, &diagnostics, cliServerTokenEnv, deprecatedServerTokenEnv); got != "new-token" {
		t.Fatalf("CLI environment value = %q", got)
	}
	if got := diagnostics.String(); got != "" {
		t.Fatalf("diagnostics=%q want empty", got)
	}
}

func TestCLIServerTokenEnvironmentUsesTransitionalFallbackBeforeLegacyName(t *testing.T) {
	lookup := lookupFrom(map[string]string{
		transitionalCLITokenEnv:  "transitional-token",
		deprecatedServerTokenEnv: "legacy-token",
	})
	var diagnostics strings.Builder
	if got := cliEnvironmentValueWithDiagnostics(lookup, &diagnostics, cliServerTokenEnv, transitionalCLITokenEnv, deprecatedServerTokenEnv); got != "transitional-token" {
		t.Fatalf("CLI Server token = %q", got)
	}
	want := "warning: " + transitionalCLITokenEnv + " is deprecated; use " + cliServerTokenEnv + "\n"
	if got := diagnostics.String(); got != want {
		t.Fatalf("diagnostics=%q want=%q", got, want)
	}
}

func TestCLIServerTokenEnvironmentPrimarySuppressesEveryDeprecatedName(t *testing.T) {
	lookup := lookupFrom(map[string]string{
		cliServerTokenEnv:        "primary-token",
		transitionalCLITokenEnv:  "transitional-token",
		deprecatedServerTokenEnv: "legacy-token",
	})
	var diagnostics strings.Builder
	if got := cliEnvironmentValueWithDiagnostics(lookup, &diagnostics, cliServerTokenEnv, transitionalCLITokenEnv, deprecatedServerTokenEnv); got != "primary-token" {
		t.Fatalf("CLI Server token = %q", got)
	}
	if got := diagnostics.String(); got != "" {
		t.Fatalf("diagnostics=%q want empty", got)
	}
}
