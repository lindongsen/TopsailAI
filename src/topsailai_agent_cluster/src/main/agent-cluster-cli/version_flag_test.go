package main

import (
	"encoding/json"
	"strings"
	"testing"

	"topsailai_agent_cluster/internal/version"
)

// TestVersionFlagAnswersBeforeAnyCommand proves the flag is reachable through the
// real entry point, not only through the helper.
//
// The helper test proves the scan works; this one proves the wiring does. A
// version request that is answered only after flag parsing would fail here,
// because the invocation carries no command and the parser would reject it as
// "a command is required" before the flag was ever consulted.
func TestVersionFlagAnswersBeforeAnyCommand(t *testing.T) {
	for _, args := range [][]string{{"-v"}, {"--version"}} {
		var output, diagnostics strings.Builder
		if err := runWithIO(args, strings.NewReader(""), &output, &diagnostics, false, nil); err != nil {
			t.Fatalf("runWithIO(%q) returned %v; stderr=%q", args, err, diagnostics.String())
		}
		rendered := output.String()
		if !strings.Contains(rendered, "agent-cluster-cli") {
			t.Fatalf("runWithIO(%q) did not name the component:\n%s", args, rendered)
		}
		if !strings.Contains(rendered, version.Version) {
			t.Fatalf("runWithIO(%q) did not report the injected version %q:\n%s", args, version.Version, rendered)
		}
		if diagnostics.String() != "" {
			t.Fatalf("runWithIO(%q) wrote a diagnostic for a successful request: %q", args, diagnostics.String())
		}
	}
}

// TestVersionFlagIsReachableAfterACommand proves the flag survives the parser
// boundary that stops at the first positional argument.
//
// This is the case that a flag-set registration alone cannot serve: Go's flag
// package stops parsing at "list", so a -v written after it would never reach the
// flag set and the invocation would instead try to run the command.
func TestVersionFlagIsReachableAfterACommand(t *testing.T) {
	var output, diagnostics strings.Builder
	if err := runWithIO([]string{"list", "-v"}, strings.NewReader(""), &output, &diagnostics, false, nil); err != nil {
		t.Fatalf("runWithIO returned %v; stderr=%q", err, diagnostics.String())
	}
	if !strings.Contains(output.String(), "agent-cluster-cli") {
		t.Fatalf("a -v written after the command was not answered:\n%s", output.String())
	}
}

// TestVersionFlagHonoursJSON proves the structured form is selected by the same
// flag every other command uses.
//
// The assertion parses the document rather than searching for a substring, because
// a substring check would pass on the human-readable layout too and would not prove
// that a script can read the result.
func TestVersionFlagHonoursJSON(t *testing.T) {
	var output, diagnostics strings.Builder
	if err := runWithIO([]string{"--json", "-v"}, strings.NewReader(""), &output, &diagnostics, false, nil); err != nil {
		t.Fatalf("runWithIO returned %v; stderr=%q", err, diagnostics.String())
	}
	var decoded version.Identity
	if err := json.Unmarshal([]byte(output.String()), &decoded); err != nil {
		t.Fatalf("--json -v did not produce one JSON document: %v\n%s", err, output.String())
	}
	if decoded.Component != "agent-cluster-cli" {
		t.Fatalf("decoded component = %q, want agent-cluster-cli", decoded.Component)
	}
}

// TestVersionFlagDoesNotStealAnOptionValue proves a value that looks like the flag
// stays a value.
//
// "--endpoint -v" names an endpoint called "-v". Answering the version request
// there would make the flag unreachable for any command that takes a value, and the
// operator would see a version banner instead of the endpoint they asked about.
func TestVersionFlagDoesNotStealAnOptionValue(t *testing.T) {
	if version.Requested([]string{"--endpoint", "-v", "list"}, versionValueOptions) {
		t.Fatal("the version request consumed an option value")
	}
}

// TestVersionFlagLeavesTerminatorDataAlone proves a literal -v after "--" is data.
//
// The exec command passes everything after "--" to the child process, so answering
// -v here would silently replace the operator's argument with a version banner.
func TestVersionFlagLeavesTerminatorDataAlone(t *testing.T) {
	if version.Requested([]string{"exec", "ep", "res", "gen", "--", "ls", "-v"}, versionValueOptions) {
		t.Fatal("the version request consumed an argument written after the -- terminator")
	}
}
