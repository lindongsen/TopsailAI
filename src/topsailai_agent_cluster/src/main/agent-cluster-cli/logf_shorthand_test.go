package main

import (
	"strings"
	"testing"

	"topsailai_agent_cluster/internal/tui"
)

// TestLogfShorthandUsageNamesItsOwnSpelling proves the standalone shorthand
// reports the spelling the operator typed, so a usage error never answers with a
// command they did not run.
func TestLogfShorthandUsageNamesItsOwnSpelling(t *testing.T) {
	cases := []struct {
		name    string
		args    []string
		wantErr string
	}{
		{
			name:    "missing arguments",
			args:    []string{"--server-url", "http://127.0.0.1:1", tui.LogsFollowAlias},
			wantErr: "usage: logf <endpoint-id> <session-id>",
		},
		{
			name:    "one argument",
			args:    []string{"--server-url", "http://127.0.0.1:1", tui.LogsFollowAlias, "ep"},
			wantErr: "usage: logf <endpoint-id> <session-id>",
		},
		{
			name:    "surplus argument",
			args:    []string{"--server-url", "http://127.0.0.1:1", tui.LogsFollowAlias, "ep", "res", "extra"},
			wantErr: "usage: logf <endpoint-id> <session-id>",
		},
	}
	for _, testCase := range cases {
		t.Run(testCase.name, func(t *testing.T) {
			var output, diagnostics strings.Builder
			err := runWithIO(testCase.args, strings.NewReader(""), &output, &diagnostics, false, nil)
			if err == nil || err.Error() != testCase.wantErr {
				t.Fatalf("error=%v want=%q", err, testCase.wantErr)
			}
		})
	}
}

// TestLogsUsageKeepsItsOwnSpelling proves the canonical spelling still answers
// with its own usage line, so the shorthand did not rename the command.
func TestLogsUsageKeepsItsOwnSpelling(t *testing.T) {
	var output, diagnostics strings.Builder
	err := runWithIO([]string{"--server-url", "http://127.0.0.1:1", "logs"}, strings.NewReader(""), &output, &diagnostics, false, nil)
	if err == nil || err.Error() != "usage: logs <endpoint-id> <session-id>" {
		t.Fatalf("error=%v", err)
	}
}

// TestLogfShorthandRejectsRepeatedFollowFlag proves the shorthand refuses a
// follow flag it already implies, because the combination is a contradiction
// rather than a harmless duplicate.
func TestLogfShorthandRejectsRepeatedFollowFlag(t *testing.T) {
	for _, flag := range []string{"--follow", "-f"} {
		t.Run(flag, func(t *testing.T) {
			var output, diagnostics strings.Builder
			args := []string{"--server-url", "http://127.0.0.1:1", tui.LogsFollowAlias, "ep", "res", flag}
			err := runWithIO(args, strings.NewReader(""), &output, &diagnostics, false, nil)
			if err == nil || !strings.Contains(err.Error(), "follow is implied; drop --follow") {
				t.Fatalf("error=%v", err)
			}
		})
	}
}

// TestLogfShorthandIsAdvertisedInHelp proves the shorthand is discoverable from
// the standalone help, so an operator can find it without reading the source.
func TestLogfShorthandIsAdvertisedInHelp(t *testing.T) {
	var output, diagnostics strings.Builder
	if err := runWithIO([]string{"help", tui.LogsFollowAlias}, strings.NewReader(""), &output, &diagnostics, false, nil); err != nil {
		t.Fatalf("help %s: %v", tui.LogsFollowAlias, err)
	}
	rendered := output.String()
	if !strings.HasPrefix(rendered, tui.LogsFollowAlias+"\n") {
		t.Fatalf("help heading does not keep the typed spelling: %q", rendered)
	}
	if !strings.Contains(rendered, "Alias of: logs") {
		t.Fatalf("help does not name the canonical command: %q", rendered)
	}
	if !strings.Contains(rendered, tui.LogsFollowAlias+": shorthand for logs -f") {
		t.Fatalf("help does not document the shorthand: %q", rendered)
	}
}

// TestLogfShorthandStaysOffTheOverview proves the shorthand is not advertised as
// a separate command, because it is a form of logs rather than a command of its
// own and the overview keeps one spelling per command.
func TestLogfShorthandStaysOffTheOverview(t *testing.T) {
	var output, diagnostics strings.Builder
	if err := runWithIO([]string{"help"}, strings.NewReader(""), &output, &diagnostics, false, nil); err != nil {
		t.Fatalf("help: %v", err)
	}
	if strings.Contains(output.String(), tui.LogsFollowAlias) {
		t.Fatalf("overview advertises the shorthand: %q", output.String())
	}
}
