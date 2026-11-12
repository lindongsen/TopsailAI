package topsailai

import (
	"context"
	"encoding/json"
	"errors"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"topsailai_agent_cluster/internal/protocol"
)

// fakeExecRunner records one local command invocation instead of running it.
type fakeExecRunner struct {
	calls      int
	executable string
	argv       []string
	dir        string
	outcome    commandExecOutcome
	err        error
}

func (f *fakeExecRunner) RunCommand(_ context.Context, executable string, argv []string, dir string) (commandExecOutcome, error) {
	f.calls++
	f.executable = executable
	f.argv = append([]string(nil), argv...)
	f.dir = dir
	return f.outcome, f.err
}

// resolvedTempDir returns the temp directory with symlinks resolved, because
// sessionDirectory reports the resolved location rather than the requested one.
func resolvedTempDir(t *testing.T) string {
	t.Helper()
	directory := t.TempDir()
	resolved, err := filepath.EvalSymlinks(directory)
	if err != nil {
		t.Fatalf("resolve temp directory: %v", err)
	}
	return resolved
}

func TestSessionDirectoryPrefersProjectWorkspace(t *testing.T) {
	project := resolvedTempDir(t)
	pwd := resolvedTempDir(t)
	directory, err := sessionDirectory(project, pwd)
	if err != nil {
		t.Fatalf("sessionDirectory: %v", err)
	}
	if directory != project {
		t.Fatalf("directory = %q, want project workspace %q", directory, project)
	}
}

func TestSessionDirectoryFallsBackToPwd(t *testing.T) {
	pwd := resolvedTempDir(t)
	cases := map[string]string{
		"empty project workspace":     "",
		"missing project workspace":   filepath.Join(pwd, "absent"),
		"relative project workspace":  "relative/workspace",
		"project workspace is a file": filepath.Join(pwd, "file"),
	}
	filePath := filepath.Join(pwd, "file")
	if err := os.WriteFile(filePath, []byte("x"), 0o600); err != nil {
		t.Fatalf("write file: %v", err)
	}
	for name, project := range cases {
		t.Run(name, func(t *testing.T) {
			directory, err := sessionDirectory(project, pwd)
			if err != nil {
				t.Fatalf("sessionDirectory: %v", err)
			}
			if directory != pwd {
				t.Fatalf("directory = %q, want pwd %q", directory, pwd)
			}
		})
	}
}

func TestSessionDirectoryFailsClosed(t *testing.T) {
	directory := resolvedTempDir(t)
	cases := map[string][2]string{
		"both empty":            {"", ""},
		"both missing":          {filepath.Join(directory, "absent"), filepath.Join(directory, "absent2")},
		"both relative":         {"relative/one", "relative/two"},
		"whitespace only":       {"   ", "\t"},
		"pwd is a regular file": {"", filepath.Join(directory, "regular")},
	}
	regular := filepath.Join(directory, "regular")
	if err := os.WriteFile(regular, []byte("x"), 0o600); err != nil {
		t.Fatalf("write file: %v", err)
	}
	for name, pair := range cases {
		t.Run(name, func(t *testing.T) {
			if _, err := sessionDirectory(pair[0], pair[1]); !errors.Is(err, errDirectoryUnresolved) {
				t.Fatalf("error = %v, want errDirectoryUnresolved", err)
			}
		})
	}
}

func TestConfineArgumentsRejectsEscapes(t *testing.T) {
	cases := map[string][]string{
		"absolute path":       {"cat", "/etc/passwd"},
		"parent traversal":    {"ls", "../../etc"},
		"embedded traversal":  {"ls", "a/../b"},
		"trailing traversal":  {"ls", "sub/.."},
		"absolute second arg": {"git", "status", "/tmp"},
	}
	for name, argv := range cases {
		t.Run(name, func(t *testing.T) {
			if err := confineArguments(argv); !errors.Is(err, errArgumentNotConfined) {
				t.Fatalf("error = %v, want errArgumentNotConfined", err)
			}
		})
	}
}

func TestConfineArgumentsAllowsRelativeTokens(t *testing.T) {
	cases := map[string][]string{
		"program only":        {"ls"},
		"subcommand":          {"git", "status"},
		"flag":                {"git", "status", "--short"},
		"relative path":       {"ls", "sub/dir"},
		"dot relative":        {"ls", "./sub"},
		"double dot in name":  {"ls", "a..b"},
		"config override":     {"git", "-c", "core.fsmonitor=x"},
		"shell metacharacter": {"echo", "a;b"},
	}
	for name, argv := range cases {
		t.Run(name, func(t *testing.T) {
			if err := confineArguments(argv); err != nil {
				t.Fatalf("confineArguments(%v) = %v, want nil", argv, err)
			}
		})
	}
}

func TestConfineArgumentsRequiresArgv(t *testing.T) {
	if err := confineArguments(nil); err == nil {
		t.Fatal("expected an error for an empty argv")
	}
}

func TestResolveCommandExecutableRejectsPathSeparator(t *testing.T) {
	for _, name := range []string{"/bin/git", "bin/git", "./git"} {
		if _, err := resolveCommandExecutable(name); err == nil {
			t.Fatalf("resolveCommandExecutable(%q) accepted a path separator", name)
		}
	}
	if _, err := resolveCommandExecutable(""); err == nil {
		t.Fatal("resolveCommandExecutable accepted an empty name")
	}
}

func TestResolveCommandExecutableUsesLookPath(t *testing.T) {
	original := lookPath
	defer func() { lookPath = original }()
	lookPath = func(name string) (string, error) { return "/usr/bin/" + name, nil }
	path, err := resolveCommandExecutable("git")
	if err != nil {
		t.Fatalf("resolveCommandExecutable: %v", err)
	}
	if path != "/usr/bin/git" {
		t.Fatalf("path = %q, want /usr/bin/git", path)
	}
	lookPath = func(string) (string, error) { return "", errors.New("not found") }
	if _, err := resolveCommandExecutable("absent"); err == nil {
		t.Fatal("expected an error when the program cannot be resolved")
	}
}

func TestCommandEnvironmentExcludesSecrets(t *testing.T) {
	t.Setenv("AGENT_CLUSTER_DATABASE_DSN", "postgres://user:secret@host/db")
	t.Setenv("AGENT_CLUSTER_SERVER_AUTH_TOKEN", "token-value")
	t.Setenv("AGENT_CLUSTER_AUTH_TOKEN", "deprecated-token-value")
	t.Setenv("PATH", "/usr/bin:/bin")
	environment := commandEnvironment()
	joined := strings.Join(environment, "\n")
	for _, secret := range []string{"AGENT_CLUSTER_DATABASE_DSN", "AGENT_CLUSTER_SERVER_AUTH_TOKEN", "AGENT_CLUSTER_AUTH_TOKEN", "secret", "token-value", "deprecated-token-value"} {
		if strings.Contains(joined, secret) {
			t.Fatalf("environment leaked %q: %v", secret, environment)
		}
	}
	if !strings.Contains(joined, "PATH=/usr/bin:/bin") {
		t.Fatalf("environment did not forward PATH: %v", environment)
	}
	if !strings.Contains(joined, "TERM=dumb") {
		t.Fatalf("environment did not set TERM=dumb: %v", environment)
	}
}

func TestCommandExecReceiptMapsOutcomes(t *testing.T) {
	intent := protocol.ImmutableIntent{CommandID: "cmd_1"}
	result := protocol.CommandExecResult{Argv: []string{"git", "status"}, ExitCode: 0}
	cases := []struct {
		name      string
		result    protocol.CommandExecResult
		runErr    error
		boundary  protocol.DeliveryBoundary
		certainty protocol.EffectCertainty
		outcome   string
		errorCode string
		exitKnown bool
	}{
		{
			name:      "success",
			result:    result,
			boundary:  protocol.DeliverySubmitted,
			certainty: protocol.EffectAcknowledged,
			outcome:   "succeeded",
			exitKnown: true,
		},
		{
			name:      "non-zero exit",
			result:    protocol.CommandExecResult{Argv: []string{"git", "diff"}, ExitCode: 1},
			boundary:  protocol.DeliverySubmitted,
			certainty: protocol.EffectAcknowledged,
			outcome:   "failed",
			errorCode: "command_exit_nonzero",
			exitKnown: true,
		},
		{
			name:      "timeout",
			result:    result,
			runErr:    errCommandTimeout,
			boundary:  protocol.DeliverySubmitted,
			certainty: protocol.EffectUnknown,
			outcome:   "unconfirmed",
			errorCode: "command_timeout",
		},
		{
			name:      "start failure",
			result:    protocol.CommandExecResult{Argv: []string{"git", "status"}},
			runErr:    errors.New("start command: boom"),
			boundary:  protocol.DeliveryNotStarted,
			certainty: protocol.EffectNotApplied,
			outcome:   "failed",
			errorCode: "command_not_started",
		},
	}
	for _, testCase := range cases {
		t.Run(testCase.name, func(t *testing.T) {
			receipt := commandExecReceipt(intent, testCase.result, testCase.runErr)
			if receipt.CommandID != intent.CommandID {
				t.Fatalf("command ID = %q, want %q", receipt.CommandID, intent.CommandID)
			}
			if receipt.DeliveryBoundary != testCase.boundary {
				t.Fatalf("delivery boundary = %q, want %q", receipt.DeliveryBoundary, testCase.boundary)
			}
			if receipt.EffectCertainty != testCase.certainty {
				t.Fatalf("effect certainty = %q, want %q", receipt.EffectCertainty, testCase.certainty)
			}
			if receipt.Outcome != testCase.outcome {
				t.Fatalf("outcome = %q, want %q", receipt.Outcome, testCase.outcome)
			}
			if receipt.ErrorCode != testCase.errorCode {
				t.Fatalf("error code = %q, want %q", receipt.ErrorCode, testCase.errorCode)
			}
			if receipt.ExitConfirmed != testCase.exitKnown {
				t.Fatalf("exit confirmed = %v, want %v", receipt.ExitConfirmed, testCase.exitKnown)
			}
			if receipt.ProviderResponse == "" {
				t.Fatal("receipt did not carry the bounded result document")
			}
			if !strings.Contains(receipt.ProviderResponse, "exit_code") {
				t.Fatalf("receipt document missing exit_code: %s", receipt.ProviderResponse)
			}
		})
	}
}

func TestSessionInfoPathRequiresSibling(t *testing.T) {
	if _, err := sessionInfoPath("topsailai"); !errors.Is(err, errSessionInfoUnavailable) {
		t.Fatalf("relative executable error = %v, want errSessionInfoUnavailable", err)
	}
	directory := resolvedTempDir(t)
	if _, err := sessionInfoPath(filepath.Join(directory, "topsailai")); !errors.Is(err, errSessionInfoUnavailable) {
		t.Fatalf("missing sibling error = %v, want errSessionInfoUnavailable", err)
	}
	sibling := filepath.Join(directory, sessionInfoExecutable)
	if err := os.WriteFile(sibling, []byte("#!/bin/sh\n"), 0o755); err != nil {
		t.Fatalf("write sibling: %v", err)
	}
	path, err := sessionInfoPath(filepath.Join(directory, "topsailai"))
	if err != nil {
		t.Fatalf("sessionInfoPath: %v", err)
	}
	if path != sibling {
		t.Fatalf("path = %q, want %q", path, sibling)
	}
}

func TestReadSessionInfoRejectsMismatchedSession(t *testing.T) {
	directory := resolvedTempDir(t)
	sibling := filepath.Join(directory, sessionInfoExecutable)
	if err := os.WriteFile(sibling, []byte("#!/bin/sh\n"), 0o755); err != nil {
		t.Fatalf("write sibling: %v", err)
	}
	config := Config{AdapterID: "a1", Executable: filepath.Join(directory, "topsailai"), MaxOutput: 4096, ResourceMapper: newFakeMapper()}
	adapter, err := newWithRunner(config, &fakeRunner{out: []byte(`{"session_id":"other","project_workspace":"/tmp","pwd":"/tmp"}`)})
	if err != nil {
		t.Fatalf("newWithRunner: %v", err)
	}
	if _, err := adapter.readSessionInfo(context.Background(), "sess1"); err == nil {
		t.Fatal("expected an error for a mismatched session document")
	}
	adapter, err = newWithRunner(config, &fakeRunner{out: []byte(`{"session_id":"sess1","project_workspace":"/tmp","pwd":"/var"}`)})
	if err != nil {
		t.Fatalf("newWithRunner: %v", err)
	}
	info, err := adapter.readSessionInfo(context.Background(), "sess1")
	if err != nil {
		t.Fatalf("readSessionInfo: %v", err)
	}
	if info.ProjectWorkspace != "/tmp" || info.Pwd != "/var" {
		t.Fatalf("session info = %+v, want project workspace /tmp and pwd /var", info)
	}
}

// newCommandExecAdapter builds an adapter whose provider executable has a real
// session inspection sibling, so the directory resolution path is exercised.
func newCommandExecAdapter(t *testing.T, execRunner commandExecRunner, sessionDocument string) (*Adapter, string) {
	t.Helper()
	directory := resolvedTempDir(t)
	sibling := filepath.Join(directory, sessionInfoExecutable)
	if err := os.WriteFile(sibling, []byte("#!/bin/sh\n"), 0o755); err != nil {
		t.Fatalf("write sibling: %v", err)
	}
	config := Config{AdapterID: "a1", Executable: filepath.Join(directory, "topsailai"), MaxOutput: 4096, ResourceMapper: newFakeMapper()}
	adapter, err := newWithRunner(config, &fakeRunner{out: []byte(sessionDocument)})
	if err != nil {
		t.Fatalf("newWithRunner: %v", err)
	}
	adapter.execRunner = execRunner
	return adapter, directory
}

// commandExecIntent builds one command.exec intent targeting a mapped session.
func commandExecIntent(t *testing.T, adapter *Adapter, argv []string) protocol.ImmutableIntent {
	t.Helper()
	if _, err := adapter.mapper.GetOrCreateResourceID(context.Background(), "a1", "sess1", 0); err != nil {
		t.Fatalf("map resource: %v", err)
	}
	payload, err := json.Marshal(protocol.CommandExecRequest{Argv: argv})
	if err != nil {
		t.Fatalf("marshal payload: %v", err)
	}
	return protocol.ImmutableIntent{
		CommandID:        "cmd_1",
		Operation:        protocol.OperationCommandExec,
		OperationVersion: protocol.CommandExecPayloadVersion,
		Target:           &protocol.CommandTarget{Kind: "session", ResourceID: "res_sess1", ProviderGeneration: "g1"},
		Payload:          payload,
	}
}

func TestExecuteCommandRunsInSessionDirectory(t *testing.T) {
	original := lookPath
	defer func() { lookPath = original }()
	lookPath = func(name string) (string, error) { return "/usr/bin/" + name, nil }
	project := resolvedTempDir(t)
	runner := &fakeExecRunner{outcome: commandExecOutcome{Stdout: []byte("clean\n")}}
	document := `{"session_id":"sess1","project_workspace":"` + project + `","pwd":"/var"}`
	adapter, _ := newCommandExecAdapter(t, runner, document)
	result, err := adapter.executeCommand(context.Background(), commandExecIntent(t, adapter, []string{"git", "status"}))
	if err != nil {
		t.Fatalf("executeCommand: %v", err)
	}
	if runner.calls != 1 {
		t.Fatalf("runner calls = %d, want 1", runner.calls)
	}
	if runner.dir != project {
		t.Fatalf("runner directory = %q, want project workspace %q", runner.dir, project)
	}
	if runner.executable != "/usr/bin/git" {
		t.Fatalf("runner executable = %q, want the resolved path", runner.executable)
	}
	if strings.Join(runner.argv, " ") != "git status" {
		t.Fatalf("runner argv = %v, want [git status]", runner.argv)
	}
	if result.Receipt.Outcome != "succeeded" {
		t.Fatalf("outcome = %q, want succeeded", result.Receipt.Outcome)
	}
	if !strings.Contains(result.Receipt.ProviderResponse, "clean") {
		t.Fatalf("receipt did not carry stdout: %s", result.Receipt.ProviderResponse)
	}
}

func TestExecuteCommandRejectsUnconfinedArguments(t *testing.T) {
	runner := &fakeExecRunner{}
	adapter, _ := newCommandExecAdapter(t, runner, `{"session_id":"sess1","project_workspace":"/tmp","pwd":"/tmp"}`)
	result, err := adapter.executeCommand(context.Background(), commandExecIntent(t, adapter, []string{"cat", "/etc/passwd"}))
	if err == nil {
		t.Fatal("expected an error for an absolute argument")
	}
	if runner.calls != 0 {
		t.Fatalf("runner calls = %d, want 0", runner.calls)
	}
	if result.Receipt.ErrorCode != "argument_not_confined" {
		t.Fatalf("error code = %q, want argument_not_confined", result.Receipt.ErrorCode)
	}
	if result.Receipt.EffectCertainty != protocol.EffectNotApplied {
		t.Fatalf("effect certainty = %q, want not_applied", result.Receipt.EffectCertainty)
	}
}

func TestExecuteCommandRejectsInvalidPayload(t *testing.T) {
	runner := &fakeExecRunner{}
	adapter, _ := newCommandExecAdapter(t, runner, `{"session_id":"sess1","project_workspace":"/tmp","pwd":"/tmp"}`)
	intent := commandExecIntent(t, adapter, []string{"git", "status"})
	intent.Payload = json.RawMessage(`{"argv":[]}`)
	result, err := adapter.executeCommand(context.Background(), intent)
	if err == nil {
		t.Fatal("expected an error for an empty argv payload")
	}
	if runner.calls != 0 {
		t.Fatalf("runner calls = %d, want 0", runner.calls)
	}
	if result.Receipt.ErrorCode != "invalid_payload" {
		t.Fatalf("error code = %q, want invalid_payload", result.Receipt.ErrorCode)
	}
}

func TestExecuteCommandReportsUnresolvedDirectory(t *testing.T) {
	runner := &fakeExecRunner{}
	adapter, _ := newCommandExecAdapter(t, runner, `{"session_id":"sess1","project_workspace":"","pwd":""}`)
	result, err := adapter.executeCommand(context.Background(), commandExecIntent(t, adapter, []string{"git", "status"}))
	if err == nil {
		t.Fatal("expected an error when no session directory resolves")
	}
	if runner.calls != 0 {
		t.Fatalf("runner calls = %d, want 0", runner.calls)
	}
	if result.Receipt.ErrorCode != "session_directory_unavailable" {
		t.Fatalf("error code = %q, want session_directory_unavailable", result.Receipt.ErrorCode)
	}
}

func TestReadBoundedTruncates(t *testing.T) {
	exact := strings.Repeat("a", commandExecMaxStreamBytes)
	data, truncated := readBounded(strings.NewReader(exact))
	if len(data) != commandExecMaxStreamBytes || truncated {
		t.Fatalf("exact read: length = %d, truncated = %v", len(data), truncated)
	}
	oversized := strings.Repeat("a", commandExecMaxStreamBytes+10)
	data, truncated = readBounded(strings.NewReader(oversized))
	if len(data) != commandExecMaxStreamBytes || !truncated {
		t.Fatalf("oversized read: length = %d, truncated = %v", len(data), truncated)
	}
}
