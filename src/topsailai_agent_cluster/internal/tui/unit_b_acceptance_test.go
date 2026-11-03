package tui

import (
	"context"
	"strings"
	"testing"
)

// TestUnitBHelpMentionsBareNumbers verifies interactive discoverability without adding a command.
func TestUnitBHelpMentionsBareNumbers(t *testing.T) {
	text := helpText(t, "cd")
	for _, want := range []string{"bare ASCII number", "leading zeros", "placeholders", "session scope"} {
		if !strings.Contains(text, want) {
			t.Fatalf("help cd missing %q: %q", want, text)
		}
	}
}

// TestUnitBB6NumericDiagnosticsHaveExactThreeLinePrecedence verifies exact
// newline-delimited diagnostics for surplus, overflow and range errors.
func TestUnitBB6NumericDiagnosticsHaveExactThreeLinePrecedence(t *testing.T) {
	cases := []struct{ input, want string }{
		{"1 foo\nquit\n", "error: invalid arguments\nusage: cd [target]\nnext: Run help cd for valid syntax.\n"},
		{"1\tfoo\nquit\n", "error: invalid arguments\nusage: cd [target]\nnext: Run help cd for valid syntax.\n"},
		{strings.Repeat("9", 64) + "\nquit\n", "error: row number exceeds the supported integer range\nusage: cd [target]\nnext: Run help cd for valid syntax.\n"},
		{"99\nquit\n", "error: row 99 is out of range; valid rows are 1-2\nusage: cd [target]\nnext: Run help cd for valid syntax.\n"},
	}
	for _, tc := range cases {
		_, diagnostics := runNav(t, scopeStub(), tc.input)
		if diagnostics != tc.want {
			t.Fatalf("diagnostics=%q want=%q", diagnostics, tc.want)
		}
		if strings.Count(diagnostics, "\n") != 3 {
			t.Fatalf("diagnostic newline count=%d: %q", strings.Count(diagnostics, "\n"), diagnostics)
		}
	}
}

// TestUnitBB8LogsUsesPinnedIdentityForBareAndExplicitNavigation proves the
// identity tuple through RunInteractive because the human renderer is metadata-only.
func TestUnitBB8LogsUsesPinnedIdentityForBareAndExplicitNavigation(t *testing.T) {
	run := func(input string) *recordingOutputAPI {
		stub := scopeStub()
		api := &recordingOutputAPI{interactiveStub: stub, outputs: map[string]string{
			"res-1": "sentinel-res-1",
			"res-2": "sentinel-res-2",
		}}
		var output, diagnostics strings.Builder
		if err := RunInteractive(context.Background(), api, strings.NewReader(input), &output, &diagnostics, InteractiveOptions{}); err != nil {
			t.Fatalf("RunInteractive %q: %v diagnostics=%q", input, err, diagnostics.String())
		}
		if !strings.Contains(output.String(), "sentinel-res-1") {
			t.Fatalf("logs did not render identity-specific content: %q", output.String())
		}
		if diagnostics.Len() != 0 {
			t.Fatalf("unexpected diagnostics: %q", diagnostics.String())
		}
		return api
	}
	for _, input := range []string{"list\n1\nlogs\nquit\n", "list\ncd 1\nlogs\nquit\n"} {
		api := run(input)
		if len(api.outputRequests) != 1 {
			t.Fatalf("output requests=%+v", api.outputRequests)
		}
		request := api.outputRequests[0]
		if request.endpointID != "endpoint-1" || request.resourceID != "res-1" || request.generation != "generation-1" || request.maxBytes <= 0 {
			t.Fatalf("wrong output identity tuple: %+v", request)
		}
		if api.admit != 0 {
			t.Fatalf("logs navigation admitted %d commands", api.admit)
		}
	}
}
