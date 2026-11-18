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

	"topsailai_connector/internal/node"
	"topsailai_connector/internal/security"
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

// TestNodePrintsTheGeneratedIdentityOnce proves a first start prints the node id,
// and that the printed value is the value the identity file now holds.
//
// The identifier is an address, not a secret, so printing it once is a convenience
// for the operator rather than a leak. It is still printed only when it is created,
// because printing it on every start would fill a log with a value that never
// changes.
func TestNodePrintsTheGeneratedIdentityOnce(t *testing.T) {
	env := newEnvironment(t)
	command, output := start(t, env.vars(), "run")
	defer stop(t, command)

	text := waitForOutput(t, output, "node id generated: ", 20*time.Second)
	if strings.Count(text, "node id generated: ") != 1 {
		t.Fatalf("node id printed %d times, want once; got:\n%s",
			strings.Count(text, "node id generated: "), text)
	}

	identity, err := os.ReadFile(filepath.Join(env.configDir, "identity"))
	if err != nil {
		t.Fatalf("read identity file: %v", err)
	}
	printed := strings.SplitN(text, "node id generated: ", 2)[1]
	printed = strings.SplitN(printed, "\n", 2)[0]
	if printed != strings.TrimSpace(string(identity)) {
		t.Fatalf("printed node id %q differs from the stored value %q", printed, strings.TrimSpace(string(identity)))
	}
}

// TestNodePrintsTheGeneratedCredentialOnce proves a first start prints the
// credential, and that the printed value is the credential the file now holds.
//
// The credential is a secret that never expires, so it is printed exactly once, at
// the moment it is created. A second print would put it into a log.
func TestNodePrintsTheGeneratedCredentialOnce(t *testing.T) {
	env := newEnvironment(t)
	command, output := start(t, env.vars(), "run")
	defer stop(t, command)

	text := waitForOutput(t, output, "node credential generated: ", 20*time.Second)
	if strings.Count(text, "node credential generated: ") != 1 {
		t.Fatalf("credential printed %d times, want once; got:\n%s",
			strings.Count(text, "node credential generated: "), text)
	}

	printed := strings.SplitN(text, "node credential generated: ", 2)[1]
	printed = strings.SplitN(printed, "\n", 2)[0]

	// The printed value must be a credential the Node actually accepts, which is
	// proved by parsing it and by finding its key identifier in the file. Comparing
	// the whole value against the file would require reading a secret back, which the
	// credential set deliberately does not allow.
	credential, err := security.ParseCredential(strings.TrimSpace(printed))
	if err != nil {
		t.Fatalf("the printed credential %q does not parse: %v", printed, err)
	}
	stored, err := node.LoadCredentials(node.CredentialsPath(env.configDir))
	if err != nil {
		t.Fatalf("load the credential file: %v", err)
	}
	if _, present := stored.Lookup(credential.KeyID); !present {
		t.Fatalf("the printed credential names key id %q, which the file does not hold", credential.KeyID)
	}
}

// TestNodeDoesNotPrintTheCredentialOnASecondStart proves the credential is printed
// only when it is created. Printing it on every start would put it into every log.
func TestNodeDoesNotPrintTheCredentialOnASecondStart(t *testing.T) {
	env := newEnvironment(t)
	first, firstOutput := start(t, env.vars(), "run")
	defer stop(t, first)
	waitForOutput(t, firstOutput, "connector-node ready", 20*time.Second)

	second, secondOutput := start(t, env.vars(), "run")
	defer stop(t, second)
	text := waitForOutput(t, secondOutput, "connector-node ready", 20*time.Second)
	if strings.Contains(text, "node credential generated: ") {
		t.Fatalf("second start printed the credential again; got:\n%s", text)
	}
	if strings.Contains(text, "node id generated: ") {
		t.Fatalf("second start printed the node id again; got:\n%s", text)
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

// TestNodeIDPrintsOnlyTheIdentifier proves the `id` subcommand is scriptable: its
// stdout is the node id and nothing else.
//
// The identifier is an address, so it is safe to print and safe to paste into a
// script. The credential is not printed here, because a command that printed a
// secret would be a command whose output is a credential.
func TestNodeIDPrintsOnlyTheIdentifier(t *testing.T) {
	env := newEnvironment(t)
	text, err := runOnce(t, env.vars(), "id")
	if err != nil {
		t.Fatalf("run connector-node id: %v; output:\n%s", err, text)
	}

	lines := strings.Split(strings.TrimSpace(text), "\n")
	if len(lines) != 1 {
		t.Fatalf("id printed %d lines, want 1; got:\n%s", len(lines), text)
	}
	if err := security.ValidateNodeID(lines[0]); err != nil {
		t.Fatalf("id printed %q, which is not a node id: %v", lines[0], err)
	}
	if strings.Contains(lines[0], ".") {
		t.Fatalf("id printed %q, which looks like a credential pair rather than an address", lines[0])
	}
}

// TestNodeRegenerateReplacesTheIdentifier proves regeneration changes the address.
func TestNodeRegenerateReplacesTheIdentifier(t *testing.T) {
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
		t.Fatalf("regenerate returned the same node id %q", strings.TrimSpace(after))
	}
	if err := security.ValidateNodeID(strings.TrimSpace(after)); err != nil {
		t.Fatalf("regenerate printed %q, which is not a node id: %v", strings.TrimSpace(after), err)
	}
}

// TestNodeRegenerateKeepsTheCredential proves regeneration does not touch the
// credential file.
//
// The two values answer different questions, so a routine address change must not
// revoke a caller. This is the property that makes regeneration safe to run without
// coordinating with every CLI.
func TestNodeRegenerateKeepsTheCredential(t *testing.T) {
	env := newEnvironment(t)
	command, output := start(t, env.vars(), "run")
	defer stop(t, command)
	waitForOutput(t, output, "connector-node ready", 20*time.Second)

	before, err := node.LoadCredentials(node.CredentialsPath(env.configDir))
	if err != nil {
		t.Fatalf("load the credential file before regeneration: %v", err)
	}

	if _, err := runOnce(t, env.vars(), "regenerate"); err != nil {
		t.Fatalf("run connector-node regenerate: %v", err)
	}

	after, err := node.LoadCredentials(node.CredentialsPath(env.configDir))
	if err != nil {
		t.Fatalf("load the credential file after regeneration: %v", err)
	}

	beforeIDs := strings.Join(before.KeyIDs(), ",")
	afterIDs := strings.Join(after.KeyIDs(), ",")
	if beforeIDs != afterIDs {
		t.Fatalf("regenerate changed the credential key ids from %q to %q", beforeIDs, afterIDs)
	}
}

// TestNodeRegenerateRejectsKeepID proves the retired flag is refused rather than
// silently ignored.
//
// `--keep-id` existed when the identity and the credential were one value. Now that
// they are separate, keeping the identifier is what regeneration already does, so
// the flag has no meaning. A flag that was silently accepted would let an operator
// believe it still selected a behaviour.
func TestNodeRegenerateRejectsKeepID(t *testing.T) {
	env := newEnvironment(t)
	text, err := runOnce(t, env.vars(), "regenerate", "--keep-id")
	if err == nil {
		t.Fatalf("process exited 0 for the retired --keep-id flag; output:\n%s", text)
	}
	if !strings.Contains(text, "keep-id") {
		t.Fatalf("failure does not name the flag; got:\n%s", text)
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
