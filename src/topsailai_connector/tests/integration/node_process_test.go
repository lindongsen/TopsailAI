//go:build integration

package integration

import (
	"bytes"
	"context"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"sync"
	"syscall"
	"testing"
	"time"
)

// runOnceTimeout bounds a child process that is expected to exit on its own. It
// is generous, because the point is to catch a child that never exits rather
// than to measure how fast a correct one is.
const runOnceTimeout = 30 * time.Second

// nodeBinary is the path to the built Node binary. TestMain builds it once so a
// suite of process tests does not pay the compiler cost per test.
var nodeBinary string

// TestMain builds the Node binary into a temporary directory and removes it
// afterwards. The build output goes to a temporary directory rather than bin/ so
// an integration run does not overwrite a binary an operator is using.
func TestMain(m *testing.M) {
	directory, err := os.MkdirTemp("", "connector-integration-*")
	if err != nil {
		os.Stderr.WriteString("create temporary directory: " + err.Error() + "\n")
		os.Exit(1)
	}

	nodeBinary = filepath.Join(directory, "connector-node")
	build := exec.Command("go", "build", "-o", nodeBinary, "topsailai_connector/cmd/connector-node")
	build.Stderr = os.Stderr
	if err := build.Run(); err != nil {
		os.RemoveAll(directory)
		os.Stderr.WriteString("build connector-node: " + err.Error() + "\n")
		os.Exit(1)
	}

	code := m.Run()
	os.RemoveAll(directory)
	os.Exit(code)
}

// environment is the fixed environment a Node process is started with. It is
// built per test rather than inherited, so a variable in the developer's shell
// cannot change what the test proves.
type environment struct {
	configDir   string
	policyPath  string
	scopeDir    string
	serverURL   string
	tunnelToken string
}

// newEnvironment creates a config directory, a scope directory and a policy file
// that grants read on that scope.
func newEnvironment(t *testing.T) environment {
	t.Helper()
	base := t.TempDir()
	configDir := filepath.Join(base, "config")
	scopeDir := filepath.Join(base, "project")
	if err := os.MkdirAll(configDir, 0o700); err != nil {
		t.Fatalf("create config directory: %v", err)
	}
	if err := os.MkdirAll(scopeDir, 0o755); err != nil {
		t.Fatalf("create scope directory: %v", err)
	}
	if err := os.WriteFile(filepath.Join(scopeDir, "note.txt"), []byte("hello\n"), 0o644); err != nil {
		t.Fatalf("write scope file: %v", err)
	}

	policyPath := filepath.Join(configDir, "policy.yaml")
	document := "version: 1\nscopes:\n  project:\n    path: " + scopeDir +
		"\ngrants:\n  - scope: project\n    permissions: [read]\n"
	if err := os.WriteFile(policyPath, []byte(document), 0o600); err != nil {
		t.Fatalf("write policy file: %v", err)
	}

	return environment{
		configDir:   configDir,
		policyPath:  policyPath,
		scopeDir:    scopeDir,
		serverURL:   "wss://server.example:8443/channel",
		tunnelToken: "tunnel-token-for-integration",
	}
}

// vars returns the environment as a slice of KEY=VALUE strings.
func (e environment) vars() []string {
	return []string{
		"CONNECTOR_NODE_SERVER_URL=" + e.serverURL,
		"CONNECTOR_NODE_TUNNEL_TOKEN=" + e.tunnelToken,
		"CONNECTOR_NODE_CONFIG_DIR=" + e.configDir,
		"CONNECTOR_NODE_POLICY_FILE=" + e.policyPath,
	}
}

// baseEnvironment is the minimum a child process needs to run at all. The
// developer's own CONNECTOR_ variables are deliberately not inherited.
func baseEnvironment() []string {
	return []string{"PATH=" + os.Getenv("PATH"), "HOME=" + os.Getenv("HOME")}
}

// start launches the Node with the given subcommand and returns the process plus
// a buffer that collects its output.
func start(t *testing.T, environment []string, arguments ...string) (*exec.Cmd, *syncBuffer) {
	t.Helper()
	command := exec.Command(nodeBinary, arguments...)
	command.Env = append(baseEnvironment(), environment...)
	output := &syncBuffer{}
	command.Stdout = output
	command.Stderr = output
	if err := command.Start(); err != nil {
		t.Fatalf("start connector-node: %v", err)
	}
	return command, output
}

// runOnce runs the binary to completion and returns its combined output.
//
// The child is bounded by a deadline. Without one, a child that does not exit
// blocks this call forever, and `go test -timeout` does not help: it panics the
// test binary and reparents the child to PID 1, so the process outlives the run
// with its binary already deleted. A test that expects a failure is exactly the
// case where the child may not exit, so the bound is not optional here.
func runOnce(t *testing.T, environment []string, arguments ...string) (string, error) {
	t.Helper()
	ctx, cancel := context.WithTimeout(context.Background(), runOnceTimeout)
	t.Cleanup(cancel)

	command := exec.CommandContext(ctx, nodeBinary, arguments...)
	command.Env = append(baseEnvironment(), environment...)
	output, err := command.CombinedOutput()
	if ctx.Err() != nil {
		t.Fatalf("connector-node %v did not exit within %s; output:\n%s",
			arguments, runOnceTimeout, output)
	}
	return string(output), err
}

// syncBuffer is a bytes.Buffer that a test can read while the child process is
// still writing to it.
type syncBuffer struct {
	mutex sync.Mutex
	data  bytes.Buffer
}

// Write appends to the buffer under a lock.
func (b *syncBuffer) Write(p []byte) (int, error) {
	b.mutex.Lock()
	defer b.mutex.Unlock()
	return b.data.Write(p)
}

// String returns everything written so far.
func (b *syncBuffer) String() string {
	b.mutex.Lock()
	defer b.mutex.Unlock()
	return b.data.String()
}

// waitForOutput polls until the buffer contains the marker or the deadline
// passes. Polling rather than sleeping a fixed time keeps the test fast when the
// process is fast and tolerant when it is slow.
func waitForOutput(t *testing.T, output *syncBuffer, marker string, timeout time.Duration) string {
	t.Helper()
	deadline := time.Now().Add(timeout)
	for time.Now().Before(deadline) {
		if strings.Contains(output.String(), marker) {
			return output.String()
		}
		time.Sleep(10 * time.Millisecond)
	}
	t.Fatalf("output never contained %q; got:\n%s", marker, output.String())
	return ""
}

// stop sends SIGTERM and waits for the process to exit, so a test never leaves a
// child process behind.
func stop(t *testing.T, command *exec.Cmd) {
	t.Helper()
	if command.Process == nil {
		return
	}
	if err := command.Process.Signal(syscall.SIGTERM); err != nil {
		command.Process.Kill()
	}
	command.Wait()
}

// TestNodeStartsAndReportsReadiness proves the process reaches readiness with a
// valid configuration and prints the scope it will serve.
func TestNodeStartsAndReportsReadiness(t *testing.T) {
	env := newEnvironment(t)
	command, output := start(t, env.vars(), "run")
	defer stop(t, command)

	text := waitForOutput(t, output, "connector-node ready", 20*time.Second)
	if !strings.Contains(text, "project") {
		t.Fatalf("readiness line does not name the scope; got:\n%s", text)
	}
}

// TestNodePrintsTheGeneratedPairOnce proves a first start prints the pair, and
// that the printed value is the pair the identity file now holds.
func TestNodePrintsTheGeneratedPairOnce(t *testing.T) {
	env := newEnvironment(t)
	command, output := start(t, env.vars(), "run")
	defer stop(t, command)

	text := waitForOutput(t, output, "node identity generated", 20*time.Second)
	if strings.Count(text, "node identity generated") != 1 {
		t.Fatalf("pair printed %d times, want once; got:\n%s",
			strings.Count(text, "node identity generated"), text)
	}

	identity, err := os.ReadFile(filepath.Join(env.configDir, "identity"))
	if err != nil {
		t.Fatalf("read identity file: %v", err)
	}
	printed := strings.SplitN(text, "node identity generated: ", 2)[1]
	printed = strings.SplitN(printed, "\n", 2)[0]
	if printed != strings.TrimSpace(string(identity)) {
		t.Fatalf("printed pair %q differs from the stored pair %q", printed, strings.TrimSpace(string(identity)))
	}
}

// TestNodeDoesNotPrintThePairOnASecondStart proves the credential is printed only
// when it is created. Printing it on every start would put it into every log.
func TestNodeDoesNotPrintThePairOnASecondStart(t *testing.T) {
	env := newEnvironment(t)
	first, firstOutput := start(t, env.vars(), "run")
	defer stop(t, first)
	waitForOutput(t, firstOutput, "connector-node ready", 20*time.Second)

	second, secondOutput := start(t, env.vars(), "run")
	defer stop(t, second)
	text := waitForOutput(t, secondOutput, "connector-node ready", 20*time.Second)
	if strings.Contains(text, "node identity generated") {
		t.Fatalf("second start printed the pair again; got:\n%s", text)
	}
}

// TestNodeRefusesToStartWithoutAPolicy proves a missing policy file is a startup
// failure rather than an implicit allow-all.
func TestNodeRefusesToStartWithoutAPolicy(t *testing.T) {
	env := newEnvironment(t)
	if err := os.Remove(env.policyPath); err != nil {
		t.Fatalf("remove policy file: %v", err)
	}

	text, err := runOnce(t, env.vars(), "run")
	if err == nil {
		t.Fatalf("process exited 0 with no policy file; output:\n%s", text)
	}
	if !strings.Contains(text, "policy") {
		t.Fatalf("failure does not mention the policy; got:\n%s", text)
	}
}

// TestNodeRefusesToStartWithoutATunnelToken proves an absent secret fails startup
// instead of falling back to an unauthenticated mode.
func TestNodeRefusesToStartWithoutATunnelToken(t *testing.T) {
	env := newEnvironment(t)
	vars := env.vars()
	vars[1] = "CONNECTOR_NODE_TUNNEL_TOKEN="

	text, err := runOnce(t, vars, "run")
	if err == nil {
		t.Fatalf("process exited 0 with an empty tunnel token; output:\n%s", text)
	}
	if !strings.Contains(text, "CONNECTOR_NODE_TUNNEL_TOKEN") {
		t.Fatalf("failure does not name the variable; got:\n%s", text)
	}
}

// TestNodeIDPrintsOnlyThePair proves the `id` subcommand is scriptable: its
// stdout is the pair and nothing else.
func TestNodeIDPrintsOnlyThePair(t *testing.T) {
	env := newEnvironment(t)
	text, err := runOnce(t, env.vars(), "id")
	if err != nil {
		t.Fatalf("run connector-node id: %v; output:\n%s", err, text)
	}

	lines := strings.Split(strings.TrimSpace(text), "\n")
	if len(lines) != 1 {
		t.Fatalf("id printed %d lines, want 1; got:\n%s", len(lines), text)
	}
	if !strings.Contains(lines[0], ".") {
		t.Fatalf("id printed %q, which is not a pair", lines[0])
	}
}

// TestNodeRegenerateReplacesThePair proves regeneration changes the pair.
func TestNodeRegenerateReplacesThePair(t *testing.T) {
	env := newEnvironment(t)
	before, err := runOnce(t, env.vars(), "id")
	if err != nil {
		t.Fatalf("run connector-node id: %v", err)
	}

	after, err := runOnce(t, env.vars(), "regenerate")
	if err != nil {
		t.Fatalf("run connector-node regenerate: %v", err)
	}

	if strings.TrimSpace(before) == strings.TrimSpace(after) {
		t.Fatalf("regenerate returned the same pair %q", strings.TrimSpace(after))
	}
}

// TestNodeRegenerateKeepIDKeepsTheIdentifier proves --keep-id keeps the routing
// target valid while replacing the secret.
func TestNodeRegenerateKeepIDKeepsTheIdentifier(t *testing.T) {
	env := newEnvironment(t)
	before, err := runOnce(t, env.vars(), "id")
	if err != nil {
		t.Fatalf("run connector-node id: %v", err)
	}

	after, err := runOnce(t, env.vars(), "regenerate", "--keep-id")
	if err != nil {
		t.Fatalf("run connector-node regenerate --keep-id: %v", err)
	}

	beforeID := strings.SplitN(strings.TrimSpace(before), ".", 2)[0]
	afterID := strings.SplitN(strings.TrimSpace(after), ".", 2)[0]
	if beforeID != afterID {
		t.Fatalf("--keep-id changed the identifier from %q to %q", beforeID, afterID)
	}
	if strings.TrimSpace(before) == strings.TrimSpace(after) {
		t.Fatal("--keep-id did not replace the token")
	}
}

// TestNodeRejectsAnUnknownSubcommand proves a typo is a failure rather than a
// silent start of the default subcommand.
func TestNodeRejectsAnUnknownSubcommand(t *testing.T) {
	env := newEnvironment(t)
	text, err := runOnce(t, env.vars(), "serve")
	if err == nil {
		t.Fatalf("process exited 0 for an unknown subcommand; output:\n%s", text)
	}
	if !strings.Contains(text, "unknown command") {
		t.Fatalf("failure does not name the problem; got:\n%s", text)
	}
}

// TestNodeRejectsAnArgumentAfterRun proves a leftover positional argument is a
// failure rather than a silently ignored word. `run serve` used to start the
// Node, because flag.Parse accepts a positional argument and nothing checked it:
// the word was dropped and the default subcommand ran.
func TestNodeRejectsAnArgumentAfterRun(t *testing.T) {
	env := newEnvironment(t)
	text, err := runOnce(t, env.vars(), "run", "serve")
	if err == nil {
		t.Fatalf("process exited 0 for a stray argument after run; output:\n%s", text)
	}
	if !strings.Contains(text, "unexpected argument") {
		t.Fatalf("failure does not name the problem; got:\n%s", text)
	}
}
