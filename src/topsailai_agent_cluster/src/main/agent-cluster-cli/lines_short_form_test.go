package main

import (
	"bytes"
	"flag"
	"strings"
	"testing"
)

// newLinesFlagSet builds the two spellings of the output line budget exactly as the
// real parser registers them, so the reconciliation is exercised against the same
// defaults the binary uses.
//
// The defaults matter: --lines carries 100, so a value comparison cannot tell "not
// supplied" from "supplied the default". Only the parser's explicit-set record can,
// which is why the test drives a real flag set instead of calling the helper with
// two integers.
func newLinesFlagSet() (*flag.FlagSet, *int, *int) {
	flags := flag.NewFlagSet("agent-cluster-cli", flag.ContinueOnError)
	lines := flags.Int("lines", 100, "trailing output lines")
	linesShort := flags.Int("n", 0, "short form of --lines")
	return flags, lines, linesShort
}

// TestReconcileLinesAcceptsTheDocumentedShortForm proves -n is a real spelling of
// --lines rather than a word in the help text.
//
// The help entry advertised "-n, --lines" while the standalone parser registered
// only --lines, so every documented short form failed with "flag provided but not
// defined". The failure was invisible in the REPL, where -n is parsed by a
// different flag set, so a command copied out of an interactive session broke in a
// script.
func TestReconcileLinesAcceptsTheDocumentedShortForm(t *testing.T) {
	cases := []struct {
		name string
		args []string
		want int
	}{
		{name: "short form alone", args: []string{"-n", "3"}, want: 3},
		{name: "long form alone", args: []string{"--lines", "7"}, want: 7},
		{name: "both agreeing", args: []string{"-n", "5", "--lines", "5"}, want: 5},
		{name: "neither selects the default", args: nil, want: 100},
	}

	for _, testCase := range cases {
		t.Run(testCase.name, func(t *testing.T) {
			flags, lines, linesShort := newLinesFlagSet()
			if err := flags.Parse(testCase.args); err != nil {
				t.Fatalf("Parse(%q): %v", testCase.args, err)
			}
			got, err := reconcileLines(flags, *lines, *linesShort)
			if err != nil {
				t.Fatalf("unexpected error: %v", err)
			}
			if got != testCase.want {
				t.Fatalf("lines=%d want=%d", got, testCase.want)
			}
		})
	}
}

// TestReconcileLinesRejectsDisagreeingSpellings proves two different stated bounds
// are refused instead of resolved by precedence.
//
// Either precedence rule would silently ignore a bound the operator stated, and the
// ignored bound is the one that decides how much output a script receives.
func TestReconcileLinesRejectsDisagreeingSpellings(t *testing.T) {
	flags, lines, linesShort := newLinesFlagSet()
	if err := flags.Parse([]string{"-n", "3", "--lines", "5"}); err != nil {
		t.Fatalf("Parse: %v", err)
	}
	_, err := reconcileLines(flags, *lines, *linesShort)
	if err == nil {
		t.Fatalf("-n 3 and --lines 5 were accepted, so one stated bound was silently ignored")
	}
	if want := "--lines 5 and -n 3 disagree; state the bound once"; err.Error() != want {
		t.Fatalf("error=%q want %q", err.Error(), want)
	}
}

// TestResolveInteractiveLinesTreatsTheShortFormAsExplicit proves a REPL started with
// -n keeps that value instead of silently receiving the interactive default.
//
// The interactive resolver treats an absent --lines as "use the interactive
// default". If -n did not count as explicit, `-n 300` would be parsed, reconciled,
// and then discarded, so the operator's stated bound would be replaced by a value
// they never asked for.
func TestResolveInteractiveLinesTreatsTheShortFormAsExplicit(t *testing.T) {
	flags, lines, linesShort := newLinesFlagSet()
	if err := flags.Parse([]string{"-n", "300"}); err != nil {
		t.Fatalf("Parse: %v", err)
	}
	budget, err := reconcileLines(flags, *lines, *linesShort)
	if err != nil {
		t.Fatalf("reconcileLines: %v", err)
	}
	got, err := resolveInteractiveLines(flags, budget)
	if err != nil {
		t.Fatalf("resolveInteractiveLines: %v", err)
	}
	if got != 300 {
		t.Fatalf("interactive lines=%d want 300; the short form was discarded", got)
	}
}

// TestRealParserAcceptsTheShortLinesForm proves the registration exists in the
// binary's own flag set, not only in a test double.
//
// The reconciliation test above builds its own flag set, so it would keep passing
// if main.go forgot to register -n: the double would supply the very flag the
// binary lacks. That is the recorded trap where a test double omits the behaviour
// under test and certifies a defect it cannot see. This test therefore drives
// runWithIO, which is the real parser, and asserts the parse itself succeeded.
//
// The command is expected to fail afterwards, because no Server is reachable. The
// assertion is on the failure kind: a flag-parse failure means the documented
// spelling does not exist, while any later failure means the spelling was accepted
// and the command proceeded.
func TestRealParserAcceptsTheShortLinesForm(t *testing.T) {
	var output, errorOutput bytes.Buffer
	err := runWithIO([]string{"-n", "3", "logs", "endpoint-1", "res-1"}, strings.NewReader(""), &output, &errorOutput, false, nil)

	if err == nil {
		t.Fatalf("the command unexpectedly succeeded without a Server")
	}
	if strings.Contains(err.Error(), "flag provided but not defined") {
		t.Fatalf("-n was rejected by the real parser, so the documented short form cannot run: %v", err)
	}
}

// TestRealParserRejectsDisagreeingLinesSpellings proves the reconciliation is wired
// into the real parser, not only into the helper.
//
// A helper that is correct but never called is the recorded "parameter threaded
// through every layer with no consumer" defect. This drives the binary's own entry
// point so the wiring is part of the assertion.
func TestRealParserRejectsDisagreeingLinesSpellings(t *testing.T) {
	var output, errorOutput bytes.Buffer
	err := runWithIO([]string{"-n", "3", "--lines", "5", "logs", "endpoint-1", "res-1"}, strings.NewReader(""), &output, &errorOutput, false, nil)

	if err == nil {
		t.Fatalf("two disagreeing line bounds were accepted")
	}
	if want := "--lines 5 and -n 3 disagree; state the bound once"; err.Error() != want {
		t.Fatalf("error=%q want %q", err.Error(), want)
	}
}

// TestRealParserAcceptsATrailingShortLinesForm proves the short form works where an
// operator actually types it: after the command.
//
// This is the exact reported failure. The parser stops at the first positional
// argument, so a trailing option is only accepted because hoistTrailingFlags moves
// it in front of the subcommand. That hoisting consults a registry of global option
// names, and -n was absent from it, so the option was hoisted while its value was
// left behind as a positional. The command then reported a usage error that named
// neither the flag nor the real problem.
//
// The assertion is on the failure kind rather than on success, because no Server is
// reachable here. A parse or usage failure means the spelling was not accepted; a
// transport failure means it was accepted and the command proceeded.
func TestRealParserAcceptsATrailingShortLinesForm(t *testing.T) {
	var output, errorOutput bytes.Buffer
	err := runWithIO([]string{"logs", "endpoint-1", "res-1", "-n", "3"}, strings.NewReader(""), &output, &errorOutput, false, nil)

	if err == nil {
		t.Fatalf("the command unexpectedly succeeded without a Server")
	}
	if strings.Contains(err.Error(), "flag provided but not defined") {
		t.Fatalf("a trailing -n was rejected by the parser: %v", err)
	}
	if strings.Contains(err.Error(), "usage: logs") {
		t.Fatalf("a trailing -n was read as a positional argument: %v", err)
	}
}
