package main

import (
	"strings"
	"testing"
)

// TestHoistTrailingFlags pins the rewrite that lets an operator write a global
// option after the subcommand. Go's flag package stops parsing at the first
// positional argument, so without this rewrite the option is silently swallowed
// as data: --yes becomes message text and --endpoint stops narrowing the scope.
func TestHoistTrailingFlags(t *testing.T) {
	for _, tc := range []struct {
		name string
		args []string
		want []string
	}{
		{
			name: "confirmation flag after message text",
			args: []string{"send", "ep", "res", "probe", "--yes"},
			want: []string{"--yes", "send", "ep", "res", "probe"},
		},
		{
			name: "confirmation flag in the message position",
			args: []string{"send", "ep", "res", "--yes"},
			want: []string{"--yes", "send", "ep", "res"},
		},
		{
			name: "boolean flag does not swallow the following argument",
			args: []string{"send", "ep", "res", "--yes", "probe"},
			want: []string{"--yes", "send", "ep", "res", "probe"},
		},
		{
			name: "filter after the subcommand",
			args: []string{"list", "--endpoint", "ep"},
			want: []string{"--endpoint", "ep", "list"},
		},
		{
			name: "value taking option carries its separate value",
			args: []string{"send", "ep", "res", "probe", "--lines", "50"},
			want: []string{"--lines", "50", "send", "ep", "res", "probe"},
		},
		{
			name: "attached value form",
			args: []string{"send", "ep", "res", "probe", "--max-bytes=1024"},
			want: []string{"--max-bytes=1024", "send", "ep", "res", "probe"},
		},
		{
			name: "several trailing options keep their order",
			args: []string{"send", "ep", "res", "probe", "--yes", "--json"},
			want: []string{"--yes", "--json", "send", "ep", "res", "probe"},
		},
		{
			name: "subcommand owned option keeps its position",
			args: []string{"list", "--clean"},
			want: []string{"list", "--clean"},
		},
		{
			name: "terminator still ends option parsing",
			args: []string{"send", "ep", "res", "--", "--yes"},
			want: []string{"send", "ep", "res", "--", "--yes"},
		},
		{
			name: "leading options are left untouched",
			args: []string{"--json", "list"},
			want: []string{"--json", "list"},
		},
		{
			name: "no options at all",
			args: []string{"list"},
			want: []string{"list"},
		},
	} {
		t.Run(tc.name, func(t *testing.T) {
			got := hoistTrailingFlags(tc.args)
			if strings.Join(got, " ") != strings.Join(tc.want, " ") {
				t.Fatalf("hoistTrailingFlags(%v)=%v want=%v", tc.args, got, tc.want)
			}
		})
	}
}

// TestTrailingGlobalFlagsAreHonoured proves the rewrite reaches the real entry
// point: a confirmation flag written after the message text must pass the
// confirmation gate instead of being delivered as message content. The Server
// URL is unreachable on purpose, so the only observable difference is which
// error the command reports.
func TestTrailingGlobalFlagsAreHonoured(t *testing.T) {
	deadServer := []string{"--server-url", "http://127.0.0.1:1"}

	trailing := append(append([]string{}, deadServer...), "send", "ep", "res", "probe", "--yes")
	var output, diagnostics strings.Builder
	err := runWithIO(trailing, strings.NewReader(""), &output, &diagnostics, false, nil)
	if err == nil {
		t.Fatal("send against an unreachable Server unexpectedly succeeded")
	}
	if strings.Contains(err.Error(), "confirmation required") {
		t.Fatalf("trailing --yes did not pass the confirmation gate: %v", err)
	}

	control := append(append([]string{}, deadServer...), "send", "ep", "res", "probe")
	output.Reset()
	diagnostics.Reset()
	err = runWithIO(control, strings.NewReader(""), &output, &diagnostics, false, nil)
	if err == nil {
		t.Fatal("unconfirmed send unexpectedly succeeded")
	}
	if !strings.Contains(err.Error(), "confirmation required for send target=res") {
		t.Fatalf("control case lost the confirmation gate: %v", err)
	}
}

// TestGlobalOptionNamesCoverEveryRegisteredFlag pins the invariant that made
// --max-chars, --limit and --no-truncate unusable after the subcommand.
//
// The three flags were registered on the top-level flag set and documented in the
// help text, but they were absent from globalOptionNames, so hoistTrailingFlags
// left them in place. Go's flag package stops parsing at the first positional
// argument, so "messages ep session --max-chars 50" parsed the flag as data and
// then failed the arity check with a usage string that did not mention the flag.
// The operator saw "usage: messages <endpoint> <session>" for a documented option,
// which reads as "the flag does not exist".
//
// The check is derived from the real flag set rather than from a hand-written
// list, because a hand-written list is exactly what drifted. A new flag now fails
// this test until its author decides whether it is hoistable.
//
// The flag set is rebuilt here by running the entry point with a help request,
// because the registrations live inline in runWithIO and there is no separate
// constructor to call. Parsing the rendered help is the same source the operator
// reads, so a flag that is documented but not hoistable is caught, and a flag that
// is hoistable but undocumented is caught too.
func TestGlobalOptionNamesCoverEveryRegisteredFlag(t *testing.T) {
	var output, diagnostics strings.Builder
	if err := runWithIO([]string{"--help"}, strings.NewReader(""), &output, &diagnostics, false, nil); err != nil {
		t.Fatalf("--help failed: %v", err)
	}
	help := output.String() + diagnostics.String()
	registered := parseHelpOptionNames(help)
	if len(registered) == 0 {
		t.Fatalf("the help output listed no options, so this check proves nothing:\n%s", help)
	}
	for name := range registered {
		if !globalOptionNames[name] {
			t.Errorf("flag --%s is registered but missing from globalOptionNames, so it is rejected after the subcommand", name)
		}
	}
	for name := range globalOptionNames {
		if !registered[name] {
			t.Errorf("globalOptionNames lists --%s but the help output does not document it", name)
		}
	}
	// A boolean option that is not marked boolean would swallow the following
	// positional argument during hoisting, silently deleting a target.
	for name := range booleanGlobalOptions {
		if !globalOptionNames[name] {
			t.Errorf("booleanGlobalOptions lists --%s which is not a global option", name)
		}
	}
}

// parseHelpOptionNames extracts the option names from the "Options:" block that
// writeUsage renders through flag.PrintDefaults. Each entry begins with one or two
// dashes at the start of a line, so a dash inside a description is not mistaken
// for an option.
func parseHelpOptionNames(help string) map[string]bool {
	names := make(map[string]bool)
	inOptions := false
	for _, line := range strings.Split(help, "\n") {
		if strings.TrimSpace(line) == "Options:" {
			inOptions = true
			continue
		}
		if !inOptions {
			continue
		}
		trimmed := strings.TrimLeft(line, " \t")
		if !strings.HasPrefix(trimmed, "-") {
			continue
		}
		name := strings.TrimLeft(trimmed, "-")
		if idx := strings.IndexAny(name, " =\t"); idx >= 0 {
			name = name[:idx]
		}
		if name != "" {
			names[name] = true
		}
	}
	return names
}

// TestTrailingCommandFlagsAreHonoured proves the three previously broken flags
// reach their command when written after the subcommand. The Server is
// unreachable on purpose, so a usage error is distinguishable from a transport
// error: the flag was parsed if and only if the command got past its arity check.
func TestTrailingCommandFlagsAreHonoured(t *testing.T) {
	deadServer := []string{"--server-url", "http://127.0.0.1:1"}
	for _, tc := range []struct {
		name string
		args []string
	}{
		{"max-chars after the session", []string{"messages", "ep", "session", "--max-chars", "50"}},
		{"max-chars attached", []string{"messages", "ep", "session", "--max-chars=50"}},
		{"max-chars before the endpoint", []string{"messages", "--max-chars", "50", "ep", "session"}},
		{"limit after the endpoint", []string{"history", "ep", "--limit", "5"}},
		{"no-truncate after the command", []string{"list", "--no-truncate"}},
	} {
		t.Run(tc.name, func(t *testing.T) {
			args := append(append([]string{}, deadServer...), tc.args...)
			var output, diagnostics strings.Builder
			err := runWithIO(args, strings.NewReader(""), &output, &diagnostics, false, nil)
			if err == nil {
				t.Fatalf("%v unexpectedly succeeded against an unreachable Server", tc.args)
			}
			if strings.Contains(err.Error(), "usage:") {
				t.Fatalf("%v was rejected as a usage error, so the trailing flag was not hoisted: %v", tc.args, err)
			}
		})
	}
}

// TestNegativeNumericFlagsAreRejected pins the boundary check that refuses a
// negative numeric option.
//
// Every consumer of these options reads a non-positive value as "no bound", so a
// negative value would widen the result instead of narrowing it: the operator
// would see a complete conversation while believing it was bounded. The check
// must therefore reject the value and name the option, rather than passing it
// down to a layer that silently treats it as unlimited.
func TestNegativeNumericFlagsAreRejected(t *testing.T) {
	deadServer := []string{"--server-url", "http://127.0.0.1:1"}
	for _, tc := range []struct {
		name string
		args []string
		want string
	}{
		{"max-chars negative", []string{"messages", "ep", "session", "--max-chars", "-5"}, "--max-chars -5 is negative"},
		{"max-chars negative attached", []string{"messages", "ep", "session", "--max-chars=-5"}, "--max-chars -5 is negative"},
		{"limit negative", []string{"history", "ep", "--limit", "-1"}, "--limit -1 is negative"},
		{"max-bytes negative", []string{"logs", "ep", "session", "--max-bytes", "-1"}, "--max-bytes -1 is negative"},
		{"lines negative", []string{"logs", "ep", "session", "--lines", "-1"}, "--lines -1 is negative"},
	} {
		t.Run(tc.name, func(t *testing.T) {
			args := append(append([]string{}, deadServer...), tc.args...)
			var output, diagnostics strings.Builder
			err := runWithIO(args, strings.NewReader(""), &output, &diagnostics, false, nil)
			if err == nil {
				t.Fatalf("%v unexpectedly succeeded", tc.args)
			}
			if !strings.Contains(err.Error(), tc.want) {
				t.Fatalf("%v error=%q want it to contain %q", tc.args, err.Error(), tc.want)
			}
			// A negative value must be reported as a value error, never as a usage
			// error: a usage message would send the operator looking for a missing
			// argument instead of the invalid one.
			if strings.Contains(err.Error(), "usage:") {
				t.Fatalf("%v was reported as a usage error instead of a value error: %v", tc.args, err)
			}
		})
	}
}

// TestMaxCharsShortFormIsHonoured pins the -c spelling of the per-message bound.
//
// -c exists so an operator who learned the short form in the interactive REPL can
// use it in a script. It is a separate flag rather than an alias entry because
// Go's flag package has no alias mechanism, so it must be hoisted like any other
// value-taking option; a missing entry in globalOptionNames would make it work
// only before the subcommand.
func TestMaxCharsShortFormIsHonoured(t *testing.T) {
	deadServer := []string{"--server-url", "http://127.0.0.1:1"}
	for _, tc := range []struct {
		name string
		args []string
	}{
		{"short form after the session", []string{"messages", "ep", "session", "-c", "40"}},
		{"short form attached", []string{"messages", "ep", "session", "-c=40"}},
		{"short form before the endpoint", []string{"messages", "-c", "40", "ep", "session"}},
	} {
		t.Run(tc.name, func(t *testing.T) {
			args := append(append([]string{}, deadServer...), tc.args...)
			var output, diagnostics strings.Builder
			err := runWithIO(args, strings.NewReader(""), &output, &diagnostics, false, nil)
			if err == nil {
				t.Fatalf("%v unexpectedly succeeded against an unreachable Server", tc.args)
			}
			if strings.Contains(err.Error(), "usage:") {
				t.Fatalf("%v was rejected as a usage error, so -c was not hoisted: %v", tc.args, err)
			}
		})
	}
}

// TestMaxCharsSpellingsAreReconciled pins the rule that folds -c and --max-chars
// into one value.
//
// Two different non-zero values are rejected instead of resolved by precedence,
// because either choice would silently ignore a bound the operator stated. Zero
// means "not supplied" for both spellings, so the two agree and both mean "no
// bound", which is the meaning every consumer already applies.
func TestMaxCharsSpellingsAreReconciled(t *testing.T) {
	for _, tc := range []struct {
		name      string
		long      int
		short     int
		want      int
		wantError bool
	}{
		{"neither stated", 0, 0, 0, false},
		{"long only", 40, 0, 40, false},
		{"short only", 0, 40, 40, false},
		{"both agree", 40, 40, 40, false},
		{"both zero", 0, 0, 0, false},
		{"both disagree", 40, 50, 0, true},
	} {
		t.Run(tc.name, func(t *testing.T) {
			got, err := reconcileMaxChars(tc.long, tc.short)
			if tc.wantError {
				if err == nil {
					t.Fatalf("reconcileMaxChars(%d, %d) unexpectedly succeeded", tc.long, tc.short)
				}
				// The message must name both values, so the operator can see which
				// two bounds disagreed instead of guessing.
				if !strings.Contains(err.Error(), "--max-chars") || !strings.Contains(err.Error(), "-c") {
					t.Fatalf("error=%q want it to name both spellings", err.Error())
				}
				return
			}
			if err != nil {
				t.Fatalf("reconcileMaxChars(%d, %d) failed: %v", tc.long, tc.short, err)
			}
			if got != tc.want {
				t.Fatalf("reconcileMaxChars(%d, %d)=%d want %d", tc.long, tc.short, got, tc.want)
			}
		})
	}
}

// TestMaxCharsAboveMaximumIsRejected pins the upper bound on the per-message
// character request.
//
// The adapter clamps a value above the protocol maximum, so a caller who asked for
// 999999999 receives a 100000 bound while the command reports success and prints
// no diagnostic. The operator then believes a bound was honoured that was silently
// replaced. The interactive surface already rejects this value, so accepting it
// here made the same request succeed in a script and fail in the REPL.
func TestMaxCharsAboveMaximumIsRejected(t *testing.T) {
	deadServer := []string{"--server-url", "http://127.0.0.1:1"}
	for _, tc := range []struct {
		name string
		args []string
	}{
		{"one above the maximum", []string{"messages", "ep", "session", "--max-chars", "100001"}},
		{"far above the maximum", []string{"messages", "ep", "session", "--max-chars", "999999999"}},
		{"short form above the maximum", []string{"messages", "ep", "session", "-c", "100001"}},
	} {
		t.Run(tc.name, func(t *testing.T) {
			args := append(append([]string{}, deadServer...), tc.args...)
			var output, diagnostics strings.Builder
			err := runWithIO(args, strings.NewReader(""), &output, &diagnostics, false, nil)
			if err == nil {
				t.Fatalf("%v unexpectedly succeeded, so the bound was silently clamped", tc.args)
			}
			if !strings.Contains(err.Error(), "exceeds the maximum") {
				t.Fatalf("%v error=%q want it to report the maximum", tc.args, err.Error())
			}
			// A rejected bound must not be reported as a usage error, because the
			// grammar was correct and only the value was out of range.
			if strings.Contains(err.Error(), "usage:") {
				t.Fatalf("%v was reported as a usage error instead of a value error: %v", tc.args, err)
			}
		})
	}
}
