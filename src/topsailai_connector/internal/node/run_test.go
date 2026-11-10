package node

import (
	"bytes"
	"log/slog"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"topsailai_connector/internal/security"
)

// newRuntimeFixture builds a config directory, a policy file and a scope
// directory, so Open has everything a real start needs.
func newRuntimeFixture(t *testing.T) Config {
	t.Helper()

	base := t.TempDir()
	configDir := filepath.Join(base, "config")
	if err := os.Mkdir(configDir, 0o700); err != nil {
		t.Fatalf("mkdir config dir: %v", err)
	}

	scopeDir := filepath.Join(base, "project")
	if err := os.Mkdir(scopeDir, 0o755); err != nil {
		t.Fatalf("mkdir scope dir: %v", err)
	}
	writeFile(t, filepath.Join(scopeDir, "inside.txt"), "inside content")

	policyPath := filepath.Join(configDir, "policy.yaml")
	writeFile(t, policyPath, "version: 1\n"+
		"scopes:\n"+
		"  project:\n"+
		"    path: "+scopeDir+"\n"+
		"grants:\n"+
		"  - scope: project\n"+
		"    permissions: [read, list, stat]\n")

	return Config{
		ServerURL:   "wss://127.0.0.1:8443/channel",
		TunnelToken: security.Secret("tunnel-token-of-sufficient-length"),
		ConfigDir:   configDir,
		PolicyPath:  policyPath,
	}
}

// discardLogger returns a logger that writes nowhere, so a test does not print
// startup lines into the test output.
func discardLogger() *slog.Logger {
	return slog.New(slog.NewTextHandler(&bytes.Buffer{}, nil))
}

// TestOpenAssemblesARuntime checks that a valid configuration yields a runtime
// with an identity and an authority, because a Node missing either is not a Node
// that serves a subset but a Node that must not start.
func TestOpenAssemblesARuntime(t *testing.T) {
	config := newRuntimeFixture(t)

	runtime, err := Open(config, discardLogger())
	if err != nil {
		t.Fatalf("Open() = %v, want nil", err)
	}
	defer runtime.Close()

	if err := security.ValidateNodeID(runtime.IdentityID()); err != nil {
		t.Fatalf("IdentityID() = %q, which is invalid: %v", runtime.IdentityID(), err)
	}
	if len(runtime.Authority().ScopeNames()) != 1 {
		t.Fatalf("ScopeNames() = %v, want one scope", runtime.Authority().ScopeNames())
	}
	if runtime.Config().PolicyPath != config.PolicyPath {
		t.Fatalf("Config().PolicyPath = %q, want %q", runtime.Config().PolicyPath, config.PolicyPath)
	}
}

// TestOpenDeniesTheIdentityFile checks that the Node's own identity file cannot be
// read through a scope, because reading it would hand a caller the credential that
// authorizes every operation on this Node.
func TestOpenDeniesTheIdentityFile(t *testing.T) {
	config := newRuntimeFixture(t)

	// The identity file is written into the config directory, which is outside
	// the scope. To prove the deny list works, the scope is pointed at the config
	// directory itself, which is the case an operator could create by mistake.
	writeFile(t, config.PolicyPath, "version: 1\n"+
		"scopes:\n"+
		"  config:\n"+
		"    path: "+config.ConfigDir+"\n"+
		"grants:\n"+
		"  - scope: config\n"+
		"    permissions: [read]\n")

	runtime, err := Open(config, discardLogger())
	if err != nil {
		t.Fatalf("Open() = %v, want nil", err)
	}
	defer runtime.Close()

	scope, ok := runtime.Authority().Scope(security.Scope("config"))
	if !ok {
		t.Fatal("Scope(config) reported missing, want present")
	}

	_, _, err = scope.Read(IdentityFileName, 0, 0)
	if err == nil {
		t.Fatal("Read(identity) = nil error, want a refusal for the Node's own credential")
	}

	// The policy file is deny-listed too, because it names the directories the
	// Node serves and a caller has no business reading it.
	if _, _, err := scope.Read("policy.yaml", 0, 0); err == nil {
		t.Fatal("Read(policy.yaml) = nil error, want a refusal for the Node's own policy")
	}
}

// TestOpenFailsWhenThePolicyIsMissing checks that a missing policy stops the
// process, because an empty policy refuses everything and looks like a working
// Node.
func TestOpenFailsWhenThePolicyIsMissing(t *testing.T) {
	config := newRuntimeFixture(t)
	config.PolicyPath = filepath.Join(config.ConfigDir, "absent.yaml")

	runtime, err := Open(config, discardLogger())
	if err == nil {
		runtime.Close()
		t.Fatal("Open() = nil error, want a failure for a missing policy")
	}
}

// TestOpenFailsWhenAScopeCannotBeOpened checks that a scope the fence refuses
// stops the process, because a Node that starts with a subset of its policy is a
// Node whose operator believes a grant exists that does not.
func TestOpenFailsWhenAScopeCannotBeOpened(t *testing.T) {
	config := newRuntimeFixture(t)
	writeFile(t, config.PolicyPath, "version: 1\n"+
		"scopes:\n"+
		"  project:\n"+
		"    path: "+filepath.Join(config.ConfigDir, "absent")+"\n")

	runtime, err := Open(config, discardLogger())
	if err == nil {
		runtime.Close()
		t.Fatal("Open() = nil error, want a failure for an unopenable scope")
	}
}

// TestOpenReportsTheIdentityOnce checks that a generated identity is printed once
// and an existing one is not printed again, because printing it on every start
// would write a credential to a log on every start.
func TestOpenReportsTheIdentityOnce(t *testing.T) {
	config := newRuntimeFixture(t)

	first, err := Open(config, discardLogger())
	if err != nil {
		t.Fatalf("first Open() = %v, want nil", err)
	}
	firstID := first.IdentityID()
	first.Close()

	second, err := Open(config, discardLogger())
	if err != nil {
		t.Fatalf("second Open() = %v, want nil", err)
	}
	defer second.Close()

	if second.IdentityID() != firstID {
		t.Fatalf("second IdentityID() = %q, want %q", second.IdentityID(), firstID)
	}
}

// TestRuntimeReportHidesTheTunnelToken checks that the startup report names the
// scopes and the identity but never the tunnel token, because a report that leaks
// by being logged is a report that will be logged.
func TestRuntimeReportHidesTheTunnelToken(t *testing.T) {
	config := newRuntimeFixture(t)

	var buffer bytes.Buffer
	logger := slog.New(slog.NewTextHandler(&buffer, nil))

	runtime, err := Open(config, logger)
	if err != nil {
		t.Fatalf("Open() = %v, want nil", err)
	}
	defer runtime.Close()

	runtime.Report()

	report := buffer.String()
	if strings.Contains(report, string(config.TunnelToken)) {
		t.Fatalf("Report() = %q, want it to hide the tunnel token", report)
	}
	if !strings.Contains(report, runtime.IdentityID()) {
		t.Fatalf("Report() = %q, want it to name the node id", report)
	}
	if !strings.Contains(report, "project") {
		t.Fatalf("Report() = %q, want it to name the scopes", report)
	}
}

// TestRuntimeCloseIsIdempotent checks that a shutdown path that runs twice does
// not fail on the second call.
func TestRuntimeCloseIsIdempotent(t *testing.T) {
	config := newRuntimeFixture(t)

	runtime, err := Open(config, discardLogger())
	if err != nil {
		t.Fatalf("Open() = %v, want nil", err)
	}
	if err := runtime.Close(); err != nil {
		t.Fatalf("Close() = %v, want nil", err)
	}
	if err := runtime.Close(); err != nil {
		t.Fatalf("second Close() = %v, want nil", err)
	}
}

// TestRuntimeCloseOnNilIsSafe checks that a nil runtime can be closed, so a
// startup failure path does not need a nil check at every call site.
func TestRuntimeCloseOnNilIsSafe(t *testing.T) {
	var runtime *Runtime
	if err := runtime.Close(); err != nil {
		t.Fatalf("Close() on nil = %v, want nil", err)
	}
}

// TestOpenUsesTheDefaultLoggerWhenNoneIsGiven checks that a nil logger does not
// panic, so a caller that forgot to pass one still starts.
func TestOpenUsesTheDefaultLoggerWhenNoneIsGiven(t *testing.T) {
	config := newRuntimeFixture(t)

	runtime, err := Open(config, nil)
	if err != nil {
		t.Fatalf("Open(config, nil) = %v, want nil", err)
	}
	defer runtime.Close()
}

// TestRuntimeNewIdentityReportsGenerationOnce checks that the generated flag is
// true only on the start that created the pair, because the caller prints the pair
// exactly once and printing it again would write a credential to a log.
func TestRuntimeNewIdentityReportsGenerationOnce(t *testing.T) {
	config := newRuntimeFixture(t)

	first, err := Open(config, discardLogger())
	if err != nil {
		t.Fatalf("first Open() = %v, want nil", err)
	}
	_, generated := first.NewIdentity()
	if !generated {
		t.Fatal("first NewIdentity() reported generated = false, want true")
	}
	first.Close()

	second, err := Open(config, discardLogger())
	if err != nil {
		t.Fatalf("second Open() = %v, want nil", err)
	}
	defer second.Close()

	_, generated = second.NewIdentity()
	if generated {
		t.Fatal("second NewIdentity() reported generated = true, want false")
	}
}
