package provider

import (
	"context"
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

// writeFakeProvider writes an executable shell script that answers the protocol
// with the supplied replies, and returns its path.
//
// A shell script is used rather than a Go helper binary because the point of the
// seam is that a provider is an independent program: the test proves the adapter
// talks to a foreign executable, not to a Go value.
func writeFakeProvider(t *testing.T, startReply, pollReply string) string {
	t.Helper()

	dir := t.TempDir()
	path := filepath.Join(dir, "fake-provider")

	script := "#!/bin/sh\n" +
		"operation=\"$1\"\n" +
		"cat > /dev/null\n" +
		"case \"$operation\" in\n" +
		"  start) printf '%s' '" + startReply + "' ;;\n" +
		"  poll) printf '%s' '" + pollReply + "' ;;\n" +
		"  stop) exit 0 ;;\n" +
		"  *) echo \"unknown operation $operation\" >&2; exit 2 ;;\n" +
		"esac\n"

	if err := os.WriteFile(path, []byte(script), 0o755); err != nil {
		t.Fatalf("write fake provider: %v", err)
	}
	return path
}

// newTestCLI returns an adapter for the fake provider.
func newTestCLI(t *testing.T, command string) *CLI {
	t.Helper()

	adapter, err := NewCLI(CLIOptions{
		Name:    "fake",
		Command: command,
		Timeout: 10 * time.Second,
	})
	if err != nil {
		t.Fatalf("new CLI: %v", err)
	}
	return adapter
}

// TestStartReturnsHandle proves a start receipt becomes a handle.
func TestStartReturnsHandle(t *testing.T) {
	command := writeFakeProvider(t,
		`{"protocol_version":1,"run_id":"sess-abc","pid":4242,"detail":"ok"}`,
		`{"state":"running"}`)
	adapter := newTestCLI(t, command)

	handle, err := adapter.Start(context.Background(), Request{
		TaskID:    "data/work",
		TaskPath:  "/srv/tasks/data/work.md",
		Workspace: t.TempDir(),
		Timeout:   30 * time.Minute,
	})
	if err != nil {
		t.Fatalf("start: %v", err)
	}
	if handle.ID != "sess-abc" {
		t.Errorf("handle id = %q, want %q", handle.ID, "sess-abc")
	}
	if handle.PID != 4242 {
		t.Errorf("handle pid = %d, want 4242", handle.PID)
	}
	if handle.Provider != "fake" {
		t.Errorf("handle provider = %q, want %q", handle.Provider, "fake")
	}
	if handle.StartedAt.IsZero() {
		t.Error("handle started at is zero")
	}
}

// TestStartRejectsEmptyRunID proves a receipt without an identity is refused.
//
// Without a run id a later poll cannot be answered, so accepting the receipt
// would create a run the scheduler can never observe.
func TestStartRejectsEmptyRunID(t *testing.T) {
	command := writeFakeProvider(t, `{"protocol_version":1,"run_id":""}`, `{"state":"running"}`)
	adapter := newTestCLI(t, command)

	_, err := adapter.Start(context.Background(), Request{TaskID: "data/work"})
	if err == nil {
		t.Fatal("start accepted a receipt with no run_id")
	}
	if !strings.Contains(err.Error(), "run_id") {
		t.Errorf("error %q does not name run_id", err.Error())
	}
}

// TestStartRejectsUnknownProtocolVersion proves a future protocol is refused
// rather than misread as the current one.
func TestStartRejectsUnknownProtocolVersion(t *testing.T) {
	command := writeFakeProvider(t, `{"protocol_version":99,"run_id":"sess-abc"}`, `{"state":"running"}`)
	adapter := newTestCLI(t, command)

	_, err := adapter.Start(context.Background(), Request{TaskID: "data/work"})
	if err == nil {
		t.Fatal("start accepted an unsupported protocol version")
	}
	if !strings.Contains(err.Error(), "protocol version") {
		t.Errorf("error %q does not name the protocol version", err.Error())
	}
}

// TestStartRejectsNonJSONReply proves a provider that prints a log line before
// its JSON is reported as malformed rather than silently accepted.
func TestStartRejectsNonJSONReply(t *testing.T) {
	command := writeFakeProvider(t, `starting up\n{"run_id":"sess-abc"}`, `{"state":"running"}`)
	adapter := newTestCLI(t, command)

	_, err := adapter.Start(context.Background(), Request{TaskID: "data/work"})
	if err == nil {
		t.Fatal("start accepted a reply that is not one JSON document")
	}
	if !strings.Contains(err.Error(), "invalid JSON") {
		t.Errorf("error %q does not report invalid JSON", err.Error())
	}
}

// TestPollReportsEachState proves every documented state is parsed.
func TestPollReportsEachState(t *testing.T) {
	cases := []struct {
		name  string
		reply string
		want  State
	}{
		{name: "running", reply: `{"state":"running"}`, want: StateRunning},
		{name: "finished", reply: `{"state":"finished","exit_code":0}`, want: StateFinished},
		{name: "unknown", reply: `{"state":"unknown"}`, want: StateUnknown},
	}

	for _, testCase := range cases {
		t.Run(testCase.name, func(t *testing.T) {
			command := writeFakeProvider(t, `{"run_id":"sess-abc"}`, testCase.reply)
			adapter := newTestCLI(t, command)

			observation, err := adapter.Poll(context.Background(), Handle{ID: "sess-abc"})
			if err != nil {
				t.Fatalf("poll: %v", err)
			}
			if observation.State != testCase.want {
				t.Errorf("state = %q, want %q", observation.State, testCase.want)
			}
		})
	}
}

// TestPollRejectsUnknownState proves an unrecognised state is an error.
//
// Reading an unknown word as finished would end supervision of a run that may
// still be working, so the adapter must refuse to guess.
func TestPollRejectsUnknownState(t *testing.T) {
	command := writeFakeProvider(t, `{"run_id":"sess-abc"}`, `{"state":"succeeded"}`)
	adapter := newTestCLI(t, command)

	_, err := adapter.Poll(context.Background(), Handle{ID: "sess-abc"})
	if err == nil {
		t.Fatal("poll accepted an unknown state")
	}
	if !strings.Contains(err.Error(), "unknown run state") {
		t.Errorf("error %q does not report an unknown state", err.Error())
	}
}

// TestPollRequiresHandleID proves a handle without an identity is refused before
// the provider is invoked.
func TestPollRequiresHandleID(t *testing.T) {
	command := writeFakeProvider(t, `{"run_id":"sess-abc"}`, `{"state":"running"}`)
	adapter := newTestCLI(t, command)

	_, err := adapter.Poll(context.Background(), Handle{})
	if err == nil {
		t.Fatal("poll accepted a handle with no run id")
	}
	if !strings.Contains(err.Error(), "run id") {
		t.Errorf("error %q does not name the run id", err.Error())
	}
}

// TestStopIsAccepted proves a stop reaches the provider.
func TestStopIsAccepted(t *testing.T) {
	command := writeFakeProvider(t, `{"run_id":"sess-abc"}`, `{"state":"running"}`)
	adapter := newTestCLI(t, command)

	if err := adapter.Stop(context.Background(), Handle{ID: "sess-abc"}); err != nil {
		t.Fatalf("stop: %v", err)
	}
}

// TestStopRequiresHandleID proves a stop without an identity is refused.
func TestStopRequiresHandleID(t *testing.T) {
	command := writeFakeProvider(t, `{"run_id":"sess-abc"}`, `{"state":"running"}`)
	adapter := newTestCLI(t, command)

	if err := adapter.Stop(context.Background(), Handle{}); err == nil {
		t.Fatal("stop accepted a handle with no run id")
	}
}

// TestCallFailureIsReported proves a non-zero provider exit is an error naming
// the operation and the provider's own message.
func TestCallFailureIsReported(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, "failing-provider")
	script := "#!/bin/sh\ncat > /dev/null\necho 'provider exploded' >&2\nexit 3\n"
	if err := os.WriteFile(path, []byte(script), 0o755); err != nil {
		t.Fatalf("write failing provider: %v", err)
	}
	adapter := newTestCLI(t, path)

	_, err := adapter.Start(context.Background(), Request{TaskID: "data/work"})
	if err == nil {
		t.Fatal("start accepted a provider that exited non-zero")
	}
	if !strings.Contains(err.Error(), "exited 3") {
		t.Errorf("error %q does not report the exit status", err.Error())
	}
	if !strings.Contains(err.Error(), "provider exploded") {
		t.Errorf("error %q does not include the provider's message", err.Error())
	}
}

// TestCallTimeoutIsReported proves a provider that never answers is bounded.
func TestCallTimeoutIsReported(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, "slow-provider")
	script := "#!/bin/sh\ncat > /dev/null\nsleep 30\n"
	if err := os.WriteFile(path, []byte(script), 0o755); err != nil {
		t.Fatalf("write slow provider: %v", err)
	}

	adapter, err := NewCLI(CLIOptions{Name: "slow", Command: path, Timeout: 300 * time.Millisecond})
	if err != nil {
		t.Fatalf("new CLI: %v", err)
	}

	_, err = adapter.Start(context.Background(), Request{TaskID: "data/work"})
	if err == nil {
		t.Fatal("start accepted a provider that never answered")
	}
	if !strings.Contains(err.Error(), "did not answer") {
		t.Errorf("error %q does not report the timeout", err.Error())
	}
}

// TestNewCLIValidation proves an adapter cannot be built without a name or a
// command.
func TestNewCLIValidation(t *testing.T) {
	if _, err := NewCLI(CLIOptions{Command: "/bin/true"}); err == nil {
		t.Error("NewCLI accepted an empty name")
	}
	if _, err := NewCLI(CLIOptions{Name: "fake"}); err == nil {
		t.Error("NewCLI accepted an empty command")
	}
}

// TestRegistryRejectsDuplicate proves two implementations of one name cannot
// coexist, because the effective behaviour would depend on init order.
func TestRegistryRejectsDuplicate(t *testing.T) {
	registry := NewRegistry()
	factory := func() Provider { return nil }

	if err := registry.Register("fake", factory); err != nil {
		t.Fatalf("register: %v", err)
	}
	if err := registry.Register("fake", factory); err == nil {
		t.Fatal("registry accepted a duplicate name")
	}
}

// TestRegistryRejectsInvalidRegistration proves empty names and nil factories
// are refused.
func TestRegistryRejectsInvalidRegistration(t *testing.T) {
	registry := NewRegistry()

	if err := registry.Register("", func() Provider { return nil }); err == nil {
		t.Error("registry accepted an empty name")
	}
	if err := registry.Register("fake", nil); err == nil {
		t.Error("registry accepted a nil factory")
	}
}

// TestRegistryGetUnknownNamesAvailable proves an unknown provider reports what is
// available, so a typo in a task YAML is diagnosable.
func TestRegistryGetUnknownNamesAvailable(t *testing.T) {
	registry := NewRegistry()
	if err := registry.Register("alpha", func() Provider { return nil }); err != nil {
		t.Fatalf("register: %v", err)
	}

	_, err := registry.Get("beta")
	if err == nil {
		t.Fatal("registry returned an unknown provider")
	}
	if !strings.Contains(err.Error(), "alpha") {
		t.Errorf("error %q does not list the available providers", err.Error())
	}
}

// TestRegistryNamesAreSorted proves the reported names are deterministic.
func TestRegistryNamesAreSorted(t *testing.T) {
	registry := NewRegistry()
	for _, name := range []string{"gamma", "alpha", "beta"} {
		if err := registry.Register(name, func() Provider { return nil }); err != nil {
			t.Fatalf("register %q: %v", name, err)
		}
	}

	names := registry.Names()
	want := []string{"alpha", "beta", "gamma"}
	if len(names) != len(want) {
		t.Fatalf("names = %v, want %v", names, want)
	}
	for index, name := range names {
		if name != want[index] {
			t.Errorf("names[%d] = %q, want %q", index, name, want[index])
		}
	}
}

// TestParseStateTrimsWhitespace proves a provider's incidental whitespace does
// not make a valid state unreadable.
func TestParseStateTrimsWhitespace(t *testing.T) {
	state, err := ParseState("  running\n")
	if err != nil {
		t.Fatalf("parse state: %v", err)
	}
	if state != StateRunning {
		t.Errorf("state = %q, want %q", state, StateRunning)
	}
}

// TestStartSendsRequestOnStdin proves the request document reaches the provider.
//
// Every other test discards stdin, so without this one the transport itself is
// unproven: the adapter could send an empty document and the receipts would still
// parse.
func TestStartSendsRequestOnStdin(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, "capturing-provider")
	// A capturing provider writes stdin to a file so the test can read it after
	// the call, which avoids depending on shell quoting of the payload.
	capture := filepath.Join(dir, "captured.json")
	script := "#!/bin/sh\n" +
		"cat > " + capture + "\n" +
		"printf '{\"run_id\":\"sess-abc\"}'\n"
	if err := os.WriteFile(path, []byte(script), 0o755); err != nil {
		t.Fatalf("write capturing provider: %v", err)
	}

	adapter := newTestCLI(t, path)
	workspace := t.TempDir()
	_, err := adapter.Start(context.Background(), Request{
		TaskID:    "data/work",
		TaskPath:  "/srv/tasks/data/work.md",
		TaskDir:   "/srv/tasks/data",
		Workspace: workspace,
		Args:      []string{"--flag", "value with spaces"},
		Env:       map[string]string{"MY_VAR": "my value"},
		Timeout:   30 * time.Minute,
	})
	if err != nil {
		t.Fatalf("start: %v", err)
	}

	sent, err := os.ReadFile(capture)
	if err != nil {
		t.Fatalf("read captured request: %v", err)
	}

	var document startRequest
	if err := json.Unmarshal(sent, &document); err != nil {
		t.Fatalf("decode captured request %q: %v", string(sent), err)
	}

	if document.ProtocolVersion != ProtocolVersion {
		t.Errorf("protocol_version = %d, want %d", document.ProtocolVersion, ProtocolVersion)
	}
	if document.TaskID != "data/work" {
		t.Errorf("task_id = %q, want %q", document.TaskID, "data/work")
	}
	if document.TaskPath != "/srv/tasks/data/work.md" {
		t.Errorf("task_path = %q, want %q", document.TaskPath, "/srv/tasks/data/work.md")
	}
	if document.TaskDir != "/srv/tasks/data" {
		t.Errorf("task_dir = %q, want %q", document.TaskDir, "/srv/tasks/data")
	}
	if document.Workspace != workspace {
		t.Errorf("workspace = %q, want %q", document.Workspace, workspace)
	}
	if len(document.Args) != 2 || document.Args[1] != "value with spaces" {
		t.Errorf("args = %v, want the value with spaces preserved as one argument", document.Args)
	}
	if document.Env["MY_VAR"] != "my value" {
		t.Errorf("env = %v, want MY_VAR preserved", document.Env)
	}
	if document.TimeoutMS != (30 * time.Minute).Milliseconds() {
		t.Errorf("timeout_ms = %d, want %d", document.TimeoutMS, (30 * time.Minute).Milliseconds())
	}
}

// TestPollSendsHandleOnStdin proves the handle identity reaches the provider, so
// a provider can look up the run it is being asked about.
func TestPollSendsHandleOnStdin(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, "capturing-provider")
	capture := filepath.Join(dir, "captured.json")
	script := "#!/bin/sh\n" +
		"cat > " + capture + "\n" +
		"printf '{\"state\":\"running\"}'\n"
	if err := os.WriteFile(path, []byte(script), 0o755); err != nil {
		t.Fatalf("write capturing provider: %v", err)
	}

	adapter := newTestCLI(t, path)
	if _, err := adapter.Poll(context.Background(), Handle{ID: "sess-abc", PID: 4242}); err != nil {
		t.Fatalf("poll: %v", err)
	}

	sent, err := os.ReadFile(capture)
	if err != nil {
		t.Fatalf("read captured handle: %v", err)
	}

	var document handleDocument
	if err := json.Unmarshal(sent, &document); err != nil {
		t.Fatalf("decode captured handle %q: %v", string(sent), err)
	}
	if document.RunID != "sess-abc" {
		t.Errorf("run_id = %q, want %q", document.RunID, "sess-abc")
	}
	if document.PID != 4242 {
		t.Errorf("pid = %d, want 4242", document.PID)
	}
	if document.ProtocolVersion != ProtocolVersion {
		t.Errorf("protocol_version = %d, want %d", document.ProtocolVersion, ProtocolVersion)
	}
}

// TestStderrDiagnosticsDoNotCorruptReply proves a provider may log to stderr
// while its JSON reply on stdout stays readable.
//
// The contract tells providers to send diagnostics to stderr. If the adapter
// merged the two streams, a single log line would make every reply unparseable,
// so the documented advice would be impossible to follow.
func TestStderrDiagnosticsDoNotCorruptReply(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, "chatty-provider")
	script := "#!/bin/sh\n" +
		"cat > /dev/null\n" +
		"echo 'connecting to backend' >&2\n" +
		"echo 'retrying once' >&2\n" +
		"printf '{\"run_id\":\"sess-abc\",\"pid\":4242}'\n"
	if err := os.WriteFile(path, []byte(script), 0o755); err != nil {
		t.Fatalf("write chatty provider: %v", err)
	}

	adapter := newTestCLI(t, path)
	handle, err := adapter.Start(context.Background(), Request{TaskID: "data/work"})
	if err != nil {
		t.Fatalf("start with stderr diagnostics: %v", err)
	}
	if handle.ID != "sess-abc" {
		t.Errorf("handle id = %q, want %q", handle.ID, "sess-abc")
	}
}

// TestStderrIsReportedOnFailure proves a provider's own error message is
// surfaced when it exits non-zero, so the operator sees the real reason.
func TestStderrIsReportedOnFailure(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, "failing-provider")
	script := "#!/bin/sh\n" +
		"cat > /dev/null\n" +
		"echo 'backend unreachable' >&2\n" +
		"exit 4\n"
	if err := os.WriteFile(path, []byte(script), 0o755); err != nil {
		t.Fatalf("write failing provider: %v", err)
	}

	adapter := newTestCLI(t, path)
	_, err := adapter.Start(context.Background(), Request{TaskID: "data/work"})
	if err == nil {
		t.Fatal("start accepted a provider that exited non-zero")
	}
	if !strings.Contains(err.Error(), "backend unreachable") {
		t.Errorf("error %q does not include the provider's stderr message", err.Error())
	}
}

// TestStartRunsProviderInWorkspace proves the provider process starts in the
// workspace the scheduler resolved.
//
// The scheduler owns the workspace: a task's YAML, or the scheduler default,
// decides it. A provider that resolved its own directory would disagree with
// that decision, and a provider-specific environment variable would only work
// for one provider implementation. The working directory is therefore part of
// the seam, and this test proves the adapter actually applies it rather than
// only forwarding it in the request document.
func TestStartRunsProviderInWorkspace(t *testing.T) {
	dir := t.TempDir()
	workspace := filepath.Join(dir, "workspace")
	if err := os.MkdirAll(workspace, 0o755); err != nil {
		t.Fatalf("create workspace: %v", err)
	}

	path := filepath.Join(dir, "pwd-provider")
	// The provider reports its own working directory, so the assertion is about
	// the process the scheduler started, not about the document it sent.
	capture := filepath.Join(dir, "cwd.txt")
	script := "#!/bin/sh\n" +
		"cat > /dev/null\n" +
		"pwd > " + capture + "\n" +
		"printf '{\"run_id\":\"sess-abc\"}'\n"
	if err := os.WriteFile(path, []byte(script), 0o755); err != nil {
		t.Fatalf("write pwd provider: %v", err)
	}

	adapter := newTestCLI(t, path)
	handle, err := adapter.Start(context.Background(), Request{
		TaskID:    "data/work",
		Workspace: workspace,
	})
	if err != nil {
		t.Fatalf("start: %v", err)
	}
	if handle.ID != "sess-abc" {
		t.Fatalf("handle id = %q, want %q", handle.ID, "sess-abc")
	}

	reported, err := os.ReadFile(capture)
	if err != nil {
		t.Fatalf("read reported directory: %v", err)
	}
	if got := strings.TrimSpace(string(reported)); got != workspace {
		t.Errorf("provider working directory = %q, want %q", got, workspace)
	}
}

// TestPollAndStopKeepSchedulerDirectory proves poll and stop are not moved into
// the workspace.
//
// They only read the provider's own state, so running them in the workspace
// would make a provider's relative state path resolve differently between start
// and poll. An empty workspace must therefore leave the scheduler's directory in
// place rather than fail.
func TestPollAndStopKeepSchedulerDirectory(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, "cwd-provider")
	capture := filepath.Join(dir, "cwd.txt")
	script := "#!/bin/sh\n" +
		"operation=\"$1\"\n" +
		"cat > /dev/null\n" +
		"pwd >> " + capture + "\n" +
		"case \"$operation\" in\n" +
		"  start) printf '{\"run_id\":\"sess-abc\"}' ;;\n" +
		"  poll) printf '{\"state\":\"running\"}' ;;\n" +
		"  stop) exit 0 ;;\n" +
		"esac\n"
	if err := os.WriteFile(path, []byte(script), 0o755); err != nil {
		t.Fatalf("write cwd provider: %v", err)
	}

	adapter := newTestCLI(t, path)
	handle, err := adapter.Start(context.Background(), Request{TaskID: "data/work"})
	if err != nil {
		t.Fatalf("start: %v", err)
	}
	if _, err := adapter.Poll(context.Background(), handle); err != nil {
		t.Fatalf("poll: %v", err)
	}
	if err := adapter.Stop(context.Background(), handle); err != nil {
		t.Fatalf("stop: %v", err)
	}

	reported, err := os.ReadFile(capture)
	if err != nil {
		t.Fatalf("read reported directories: %v", err)
	}
	lines := strings.Split(strings.TrimSpace(string(reported)), "\n")
	if len(lines) != 3 {
		t.Fatalf("reported directories = %v, want three entries", lines)
	}
	schedulerDir, err := os.Getwd()
	if err != nil {
		t.Fatalf("get scheduler directory: %v", err)
	}
	for index, line := range lines {
		if strings.TrimSpace(line) != schedulerDir {
			t.Errorf("call %d ran in %q, want the scheduler directory %q",
				index, strings.TrimSpace(line), schedulerDir)
		}
	}
}
