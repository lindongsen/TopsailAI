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

// runBudgetREPL drives the REPL with both the watch reader and an explicit line
// budget. The watch reader is required because a client that cannot observe a
// keypress cannot stop a live tail, so without it every case would silently
// exercise the degradation path instead of the tail the operator gets.
func runBudgetREPL(t *testing.T, stub InteractiveAPI, lines []string, maxLines int) (string, string) {
	t.Helper()
	reader := &watchRecordingReader{lines: lines}
	var out, diagnostics strings.Builder
	options := InteractiveOptions{
		ReadLine: func(ctx context.Context, prompt string, history bool, limit int) (string, bool, error) {
			return reader.ReadLineWithWatch(ctx, prompt, history, limit, nil)
		},
		WatchReader: reader,
		MaxLines:    maxLines,
	}
	if err := RunInteractive(context.Background(), stub, noPromptStream{t}, &out, &diagnostics, options); err != nil {
		t.Fatalf("RunInteractive: %v", err)
	}
	return out.String(), diagnostics.String()
}

// TestUnitStartupBudgetReachesTheEntryTail proves the startup budget is the
// single source of truth: the automatic entry tail and a bare logs command both
// read the configured count instead of two independent literals. The stub serves
// the streaming seam, so this exercises the tail the operator actually gets
// rather than the degradation path.
func TestUnitStartupBudgetReachesTheEntryTail(t *testing.T) {
	cases := []struct {
		name  string
		input []string
	}{
		{name: "entry tail only", input: []string{"cd host-one/endpoint-1/res-1", "exit"}},
		{name: "entry tail then bare logs", input: []string{"cd host-one/endpoint-1/res-1", "logs", "exit"}},
	}

	for _, testCase := range cases {
		t.Run(testCase.name, func(t *testing.T) {
			stub := newSendFollowStub()
			if _, diagnostics := runBudgetREPL(t, stub, testCase.input, 500); diagnostics != "" {
				t.Fatalf("unexpected diagnostics: %q", diagnostics)
			}
			follows := stub.followRequests()
			if len(follows) != 1 {
				t.Fatalf("entry follow requests=%+v want exactly one", follows)
			}
			if got := follows[0].maxLines; got != 500 {
				t.Fatalf("entry tail maxLines=%d want=500", got)
			}
			for index, request := range stub.outputRequests {
				if request.maxLines != 500 {
					t.Fatalf("output request %d maxLines=%d want=500", index, request.maxLines)
				}
			}
		})
	}
}

// TestUnitStartupBudgetKeepsThePerCommandOverride proves the startup budget does
// not swallow an explicit per-command count: a deliberate read still wins, while
// the automatic entry tail keeps the configured budget.
func TestUnitStartupBudgetKeepsThePerCommandOverride(t *testing.T) {
	stub := newSendFollowStub()
	lines := []string{"cd host-one/endpoint-1/res-1", "logs -n 7", "exit"}
	if _, diagnostics := runBudgetREPL(t, stub, lines, 500); diagnostics != "" {
		t.Fatalf("unexpected diagnostics: %q", diagnostics)
	}
	follows := stub.followRequests()
	if len(follows) != 1 {
		t.Fatalf("entry follow requests=%+v want exactly one", follows)
	}
	if got := follows[0].maxLines; got != 500 {
		t.Fatalf("entry tail maxLines=%d want=500", got)
	}
	if len(stub.outputRequests) != 1 {
		t.Fatalf("output requests=%+v want exactly one explicit read", stub.outputRequests)
	}
	if got := stub.outputRequests[0].maxLines; got != 7 {
		t.Fatalf("explicit read maxLines=%d want=7", got)
	}
}

// TestUnitUnsetStartupBudgetUsesTheDefault proves an unset budget resolves to the
// documented default rather than to the standalone logs default.
func TestUnitUnsetStartupBudgetUsesTheDefault(t *testing.T) {
	stub := newSendFollowStub()
	if _, diagnostics := runBudgetREPL(t, stub, []string{"cd host-one/endpoint-1/res-1", "exit"}, 0); diagnostics != "" {
		t.Fatalf("unexpected diagnostics: %q", diagnostics)
	}
	follows := stub.followRequests()
	if len(follows) != 1 {
		t.Fatalf("entry follow requests=%+v want exactly one", follows)
	}
	if got := follows[0].maxLines; got != DefaultInteractiveMaxLines {
		t.Fatalf("entry tail maxLines=%d want=%d", got, DefaultInteractiveMaxLines)
	}
}

// TestUnitStartupBudgetReachesTheDegradedEntrySnapshot proves the same budget
// reaches the fallback path. A client without the streaming seam renders one
// bounded snapshot, so the two paths cannot disagree about the bound. The
// degradation notice is written to the trusted output, not to diagnostics.
func TestUnitStartupBudgetReachesTheDegradedEntrySnapshot(t *testing.T) {
	stub := scopeStub()
	output, _ := runBudgetREPL(t, stub, []string{"cd host-one/endpoint-1/res-1", "exit"}, 500)
	if !strings.Contains(output, "automatic follow unavailable") {
		t.Fatalf("want a degradation notice in the output, got %q", output)
	}
	if len(stub.outputRequests) != 1 {
		t.Fatalf("output requests=%+v want exactly one snapshot", stub.outputRequests)
	}
	if got := stub.outputRequests[0].maxLines; got != 500 {
		t.Fatalf("degraded entry snapshot maxLines=%d want=500", got)
	}
}
