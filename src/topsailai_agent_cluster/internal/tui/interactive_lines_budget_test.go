package tui

import (
	"context"
	"strings"
	"testing"
)

// TestUnitNormalizeInteractiveMaxLines covers the REPL line budget resolution.
// An unset value selects the documented default, and an out-of-range value is
// clamped into the supported window so a caller that bypasses the CLI still
// cannot request an unbounded snapshot.
func TestUnitNormalizeInteractiveMaxLines(t *testing.T) {
	cases := []struct {
		name  string
		value int
		want  int
	}{
		{name: "unset selects the default", value: 0, want: DefaultInteractiveMaxLines},
		{name: "negative selects the default", value: -5, want: DefaultInteractiveMaxLines},
		{name: "below the minimum clamps up", value: 99, want: MinInteractiveMaxLines},
		{name: "the minimum is kept", value: 100, want: 100},
		{name: "a value inside the window is kept", value: 500, want: 500},
		{name: "the maximum is kept", value: 1000, want: 1000},
		{name: "above the maximum clamps down", value: 1001, want: MaxInteractiveMaxLines},
	}

	for _, testCase := range cases {
		t.Run(testCase.name, func(t *testing.T) {
			if got := NormalizeInteractiveMaxLines(testCase.value); got != testCase.want {
				t.Fatalf("NormalizeInteractiveMaxLines(%d)=%d want=%d", testCase.value, got, testCase.want)
			}
		})
	}
}

// TestUnitInteractiveMaxLinesDefaultsToThreeHundred pins the operator-facing
// default. The entry snapshot is the first thing an operator reads after
// selecting a session, so it must not fall back to the standalone default.
func TestUnitInteractiveMaxLinesDefaultsToThreeHundred(t *testing.T) {
	if DefaultInteractiveMaxLines != 300 {
		t.Fatalf("DefaultInteractiveMaxLines=%d want=300", DefaultInteractiveMaxLines)
	}
	if MinInteractiveMaxLines != 100 || MaxInteractiveMaxLines != 1000 {
		t.Fatalf("interactive range=%d-%d want=100-1000", MinInteractiveMaxLines, MaxInteractiveMaxLines)
	}
}

// runScopeWithOptions executes one interactive scenario with explicit options.
func runScopeWithOptions(t *testing.T, stub InteractiveAPI, input string, options InteractiveOptions) (string, string) {
	t.Helper()
	var output, diagnostics strings.Builder
	if err := RunInteractive(context.Background(), stub, strings.NewReader(input), &output, &diagnostics, options); err != nil {
		t.Fatalf("RunInteractive: %v", err)
	}
	return output.String(), diagnostics.String()
}

// TestUnitStartupBudgetReachesTheEntrySnapshot proves the startup budget is the
// single source of truth: the automatic entry snapshot and a bare logs command
// both read the configured count instead of two independent literals.
func TestUnitStartupBudgetReachesTheEntrySnapshot(t *testing.T) {
	cases := []struct {
		name  string
		input string
		want  int
	}{
		{name: "entry snapshot only", input: "cd host-one/endpoint-1/res-1\nexit\n", want: 500},
		{name: "entry snapshot then bare logs", input: "cd host-one/endpoint-1/res-1\nlogs\nexit\n", want: 500},
	}

	for _, testCase := range cases {
		t.Run(testCase.name, func(t *testing.T) {
			stub := scopeStub()
			if _, diagnostics := runScopeWithOptions(t, stub, testCase.input, InteractiveOptions{MaxLines: 500}); diagnostics != "" {
				t.Fatalf("unexpected diagnostics: %q", diagnostics)
			}
			if len(stub.outputRequests) == 0 {
				t.Fatalf("no output request was recorded")
			}
			for index, request := range stub.outputRequests {
				if request.maxLines != testCase.want {
					t.Fatalf("output request %d maxLines=%d want=%d", index, request.maxLines, testCase.want)
				}
			}
		})
	}
}

// TestUnitStartupBudgetKeepsThePerCommandOverride proves the startup budget does
// not swallow an explicit per-command count: a deliberate read still wins.
func TestUnitStartupBudgetKeepsThePerCommandOverride(t *testing.T) {
	stub := scopeStub()
	input := "cd host-one/endpoint-1/res-1\nlogs -n 7\nexit\n"
	if _, diagnostics := runScopeWithOptions(t, stub, input, InteractiveOptions{MaxLines: 500}); diagnostics != "" {
		t.Fatalf("unexpected diagnostics: %q", diagnostics)
	}
	if len(stub.outputRequests) != 2 {
		t.Fatalf("output requests=%+v", stub.outputRequests)
	}
	if got := stub.outputRequests[0].maxLines; got != 500 {
		t.Fatalf("entry snapshot maxLines=%d want=500", got)
	}
	if got := stub.outputRequests[1].maxLines; got != 7 {
		t.Fatalf("explicit read maxLines=%d want=7", got)
	}
}

// TestUnitUnsetStartupBudgetUsesTheDefault proves an unset budget resolves to the
// documented default rather than to the standalone logs default.
func TestUnitUnsetStartupBudgetUsesTheDefault(t *testing.T) {
	stub := scopeStub()
	if _, diagnostics := runScopeWithOptions(t, stub, "cd host-one/endpoint-1/res-1\nexit\n", InteractiveOptions{}); diagnostics != "" {
		t.Fatalf("unexpected diagnostics: %q", diagnostics)
	}
	if len(stub.outputRequests) != 1 {
		t.Fatalf("output requests=%+v", stub.outputRequests)
	}
	if got := stub.outputRequests[0].maxLines; got != DefaultInteractiveMaxLines {
		t.Fatalf("entry snapshot maxLines=%d want=%d", got, DefaultInteractiveMaxLines)
	}
}
