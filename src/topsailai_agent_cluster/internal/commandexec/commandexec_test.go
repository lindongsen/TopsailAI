package commandexec

import (
	"context"
	"encoding/json"
	"errors"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"topsailai_agent_cluster/internal/protocol"
)

// TestSessionDirectoryResolvesARealDirectory proves the resolver returns the
// symlink-free path of an existing directory, so the confinement decision is made
// on the real location rather than on a link that points elsewhere.
func TestSessionDirectoryResolvesARealDirectory(t *testing.T) {
	directory := t.TempDir()
	resolved, err := SessionDirectory(directory, "")
	if err != nil {
		t.Fatalf("resolve directory: %v", err)
	}
	want, err := filepath.EvalSymlinks(directory)
	if err != nil {
		t.Fatalf("eval symlinks: %v", err)
	}
	if resolved != want {
		t.Fatalf("directory = %q, want %q", resolved, want)
	}
}

// TestSessionDirectoryFailsClosed proves every unusable workspace is refused
// instead of falling back to the Endpoint's own working directory.
func TestSessionDirectoryFailsClosed(t *testing.T) {
	file := filepath.Join(t.TempDir(), "regular-file")
	if err := os.WriteFile(file, []byte("x"), 0o600); err != nil {
		t.Fatalf("write file: %v", err)
	}
	cases := map[string]string{
		"empty":           "",
		"blank":           "   ",
		"relative":        "relative/path",
		"missing":         filepath.Join(t.TempDir(), "absent"),
		"regular file":    file,
		"dot relative":    ".",
		"parent relative": "../",
	}
	for name, workspace := range cases {
		t.Run(name, func(t *testing.T) {
			if _, err := SessionDirectory(workspace, ""); !errors.Is(err, ErrDirectoryUnresolved) {
				t.Fatalf("error = %v, want %v", err, ErrDirectoryUnresolved)
			}
		})
	}
}

// TestSessionDirectoryFallsBackToPwd proves the second candidate keeps a command
// runnable when the project workspace does not resolve on this host.
//
// A session whose project lives on another machine still reports the directory it
// was started from. Refusing the command because the project workspace is absent
// would remove a capability the operator had before, so the fallback is required.
func TestSessionDirectoryFallsBackToPwd(t *testing.T) {
	pwd := t.TempDir()
	absent := filepath.Join(t.TempDir(), "absent")
	resolved, err := SessionDirectory(absent, pwd)
	if err != nil {
		t.Fatalf("resolve directory: %v", err)
	}
	want, err := filepath.EvalSymlinks(pwd)
	if err != nil {
		t.Fatalf("eval symlinks: %v", err)
	}
	if resolved != want {
		t.Fatalf("directory = %q, want %q", resolved, want)
	}
}

// TestSessionDirectoryPrefersTheProjectWorkspace proves the fallback does not
// change which directory wins.
//
// The project workspace is the stable location the operator means by "the
// session's folder", so a session started from a subdirectory must still run in
// the project. A resolver that tried pwd first would silently move every command.
func TestSessionDirectoryPrefersTheProjectWorkspace(t *testing.T) {
	project := t.TempDir()
	pwd := t.TempDir()
	resolved, err := SessionDirectory(project, pwd)
	if err != nil {
		t.Fatalf("resolve directory: %v", err)
	}
	want, err := filepath.EvalSymlinks(project)
	if err != nil {
		t.Fatalf("eval symlinks: %v", err)
	}
	if resolved != want {
		t.Fatalf("directory = %q, want %q", resolved, want)
	}
}

// TestSessionDirectoryRefusesWhenNeitherCandidateResolves proves the fallback is
// not a licence to run somewhere arbitrary.
func TestSessionDirectoryRefusesWhenNeitherCandidateResolves(t *testing.T) {
	absent := filepath.Join(t.TempDir(), "absent")
	other := filepath.Join(t.TempDir(), "also-absent")
	if _, err := SessionDirectory(absent, other); !errors.Is(err, ErrDirectoryUnresolved) {
		t.Fatalf("error = %v, want %v", err, ErrDirectoryUnresolved)
	}
}

// TestConfineArgumentsRejectsEscapes proves an absolute argument and a
// parent-traversal element are refused, while an ordinary relative argument and a
// shell metacharacter stay literal.
func TestConfineArgumentsRejectsEscapes(t *testing.T) {
	rejected := [][]string{
		{"cat", "/etc/passwd"},
		{"cat", "../../etc/passwd"},
		{"cat", "a/../../b"},
		{},
	}
	for _, argv := range rejected {
		if err := ConfineArguments(argv); err == nil {
			t.Fatalf("argv %v was accepted", argv)
		}
	}
	accepted := [][]string{
		{"git", "status", "--short"},
		{"git", "log", "--grep=$(id)", "a;b", "c|d"},
		{"cat", "notes.txt"},
	}
	for _, argv := range accepted {
		if err := ConfineArguments(argv); err != nil {
			t.Fatalf("argv %v was refused: %v", argv, err)
		}
	}
}

// TestResolveExecutableRejectsAPath proves a program name carrying a path
// separator is refused, because the allowlist matches a name and a path would let
// the caller choose the program.
func TestResolveExecutableRejectsAPath(t *testing.T) {
	for _, name := range []string{"", "/bin/sh", "./script", "dir/program"} {
		if _, err := ResolveExecutable(name); err == nil {
			t.Fatalf("program name %q was accepted", name)
		}
	}
	resolved, err := ResolveExecutable("sh")
	if err != nil {
		t.Fatalf("resolve sh: %v", err)
	}
	if !filepath.IsAbs(resolved) {
		t.Fatalf("resolved path %q is not absolute", resolved)
	}
}

// TestReceiptClassifiesEveryOutcome proves the three effect classes stay distinct:
// a completed command is acknowledged, a timeout is unknown, and a start failure
// is not applied.
func TestReceiptClassifiesEveryOutcome(t *testing.T) {
	intent := protocol.ImmutableIntent{CommandID: "cmd-1"}
	cases := []struct {
		name      string
		result    protocol.CommandExecResult
		runErr    error
		boundary  protocol.DeliveryBoundary
		certainty protocol.EffectCertainty
		outcome   string
		code      string
		confirmed bool
	}{
		{name: "success", result: protocol.CommandExecResult{ExitCode: 0, Stdout: "ok\n"}, boundary: protocol.DeliverySubmitted, certainty: protocol.EffectAcknowledged, outcome: "succeeded", confirmed: true},
		{name: "non-zero exit", result: protocol.CommandExecResult{ExitCode: 2}, boundary: protocol.DeliverySubmitted, certainty: protocol.EffectAcknowledged, outcome: "failed", code: "command_exit_nonzero", confirmed: true},
		{name: "timeout", runErr: ErrTimeout, boundary: protocol.DeliverySubmitted, certainty: protocol.EffectUnknown, outcome: "unconfirmed", code: "command_timeout"},
		{name: "start failure", runErr: errors.New("exec: not found"), boundary: protocol.DeliveryNotStarted, certainty: protocol.EffectNotApplied, outcome: "failed", code: "command_not_started"},
	}
	for _, test := range cases {
		t.Run(test.name, func(t *testing.T) {
			receipt := Receipt(intent, test.result, test.runErr)
			if receipt.DeliveryBoundary != test.boundary || receipt.EffectCertainty != test.certainty {
				t.Fatalf("receipt = %+v, want boundary %q certainty %q", receipt, test.boundary, test.certainty)
			}
			if receipt.Outcome != test.outcome || receipt.ErrorCode != test.code {
				t.Fatalf("receipt = %+v, want outcome %q code %q", receipt, test.outcome, test.code)
			}
			if receipt.ExitConfirmed != test.confirmed {
				t.Fatalf("exit confirmed = %v, want %v", receipt.ExitConfirmed, test.confirmed)
			}
			if receipt.CommandID != "cmd-1" || receipt.Phase != protocol.PhaseReceiptRecorded {
				t.Fatalf("receipt identity = %+v", receipt)
			}
			var decoded protocol.CommandExecResult
			if err := json.Unmarshal([]byte(receipt.ProviderResponse), &decoded); err != nil {
				t.Fatalf("decode provider response %q: %v", receipt.ProviderResponse, err)
			}
		})
	}
}

// TestFailedReceiptIsNotApplied proves a refusal before the command ran reports a
// definite not-applied effect, so a caller never mistakes it for an unknown one.
func TestFailedReceiptIsNotApplied(t *testing.T) {
	receipt := FailedReceipt(protocol.ImmutableIntent{CommandID: "cmd-2"}, "argument_not_confined")
	if receipt.EffectCertainty != protocol.EffectNotApplied || receipt.Outcome != "failed" || receipt.ErrorCode != "argument_not_confined" {
		t.Fatalf("receipt = %+v", receipt)
	}
	if receipt.ExitConfirmed {
		t.Fatal("a refused command reported a confirmed exit")
	}
}

// TestExecRunnerRunsInTheGivenDirectory proves the runner executes the resolved
// program in the requested directory and reports the real exit status.
func TestExecRunnerRunsInTheGivenDirectory(t *testing.T) {
	directory := t.TempDir()
	resolved, err := filepath.EvalSymlinks(directory)
	if err != nil {
		t.Fatalf("eval symlinks: %v", err)
	}
	executable, err := ResolveExecutable("pwd")
	if err != nil {
		t.Fatalf("resolve pwd: %v", err)
	}
	outcome, err := ExecRunner{}.Run(context.Background(), executable, []string{"pwd"}, resolved)
	if err != nil {
		t.Fatalf("run pwd: %v", err)
	}
	if strings.TrimSpace(string(outcome.Stdout)) != resolved {
		t.Fatalf("stdout = %q, want %q", outcome.Stdout, resolved)
	}
	if outcome.ExitCode != 0 {
		t.Fatalf("exit code = %d, want 0", outcome.ExitCode)
	}
}

// TestExecRunnerReportsANonZeroExitAsAResult proves a failing program is a
// completed observation rather than a runner error, because the operator needs the
// exit status instead of a claim that nothing ran.
func TestExecRunnerReportsANonZeroExitAsAResult(t *testing.T) {
	executable, err := ResolveExecutable("sh")
	if err != nil {
		t.Fatalf("resolve sh: %v", err)
	}
	outcome, err := ExecRunner{}.Run(context.Background(), executable, []string{"sh", "-c", "echo boom >&2; exit 3"}, t.TempDir())
	if err != nil {
		t.Fatalf("run sh: %v", err)
	}
	if outcome.ExitCode != 3 {
		t.Fatalf("exit code = %d, want 3", outcome.ExitCode)
	}
	if !strings.Contains(string(outcome.Stderr), "boom") {
		t.Fatalf("stderr = %q, want the program diagnostic", outcome.Stderr)
	}
}

// TestExecRunnerBoundsOutput proves an oversized stream is truncated and reported
// as truncated, so a chatty program cannot grow the receipt without limit.
func TestExecRunnerBoundsOutput(t *testing.T) {
	executable, err := ResolveExecutable("sh")
	if err != nil {
		t.Fatalf("resolve sh: %v", err)
	}
	script := "head -c " + itoa(MaxStreamBytes+1024) + " /dev/zero | tr '\\0' 'a'"
	outcome, err := ExecRunner{}.Run(context.Background(), executable, []string{"sh", "-c", script}, t.TempDir())
	if err != nil {
		t.Fatalf("run sh: %v", err)
	}
	if !outcome.Truncated {
		t.Fatal("oversized output was not reported as truncated")
	}
	if len(outcome.Stdout) > MaxStreamBytes {
		t.Fatalf("stdout length = %d, want at most %d", len(outcome.Stdout), MaxStreamBytes)
	}
}

// TestExecRunnerKillsACommandThatOutlivesItsBudget proves a command exceeding its
// bounded lifetime is reported as a timeout, which is an unknown effect.
func TestExecRunnerKillsACommandThatOutlivesItsBudget(t *testing.T) {
	executable, err := ResolveExecutable("sh")
	if err != nil {
		t.Fatalf("resolve sh: %v", err)
	}
	started := time.Now()
	outcome, err := ExecRunner{Timeout: 200 * time.Millisecond}.Run(context.Background(), executable, []string{"sh", "-c", "sleep 30"}, t.TempDir())
	if !errors.Is(err, ErrTimeout) {
		t.Fatalf("error = %v, want %v", err, ErrTimeout)
	}
	if elapsed := time.Since(started); elapsed > 10*time.Second {
		t.Fatalf("timeout took %s, want a bounded stop", elapsed)
	}
	if outcome.ExitCode != 0 {
		t.Fatalf("exit code = %d, want the zero value for a killed command", outcome.ExitCode)
	}
}

// TestEnvironmentForwardsOnlyTheMinimalSet proves the child does not inherit the
// Endpoint environment, which carries provider credentials, DSNs and tokens.
func TestEnvironmentForwardsOnlyTheMinimalSet(t *testing.T) {
	t.Setenv("AGENT_CLUSTER_SERVER_AUTH_TOKEN", "secret")
	environment := Environment()
	for _, entry := range environment {
		if strings.HasPrefix(entry, "AGENT_CLUSTER_") {
			t.Fatalf("environment leaked %q", entry)
		}
	}
	joined := strings.Join(environment, "\n")
	if !strings.Contains(joined, "TERM=dumb") {
		t.Fatalf("environment = %v, want TERM=dumb", environment)
	}
}

// itoa renders a small positive integer without importing strconv into the test
// for a single call site.
func itoa(value int) string {
	if value == 0 {
		return "0"
	}
	digits := ""
	for value > 0 {
		digits = string(rune('0'+value%10)) + digits
		value /= 10
	}
	return digits
}
