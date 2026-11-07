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
