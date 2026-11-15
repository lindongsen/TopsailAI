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

// TestOpenRefusesAScopeThatOverlapsTheConfigDirectory checks that a scope which
// contains, sits inside or equals the Node's config directory stops startup.
//
// The deny list protects the contents of the Node's own files, but a listing of
// the config directory still reports their names and sizes. Refusing the overlap
// removes that metadata leak as well, which is why the design requires a startup
// refusal rather than relying on the deny list alone.
func TestOpenRefusesAScopeThatOverlapsTheConfigDirectory(t *testing.T) {
	cases := []struct {
		name      string
		scopePath func(config Config) string
	}{
		{
			name:      "scope equals the config directory",
			scopePath: func(config Config) string { return config.ConfigDir },
		},
		{
			name:      "scope contains the config directory",
			scopePath: func(config Config) string { return filepath.Dir(config.ConfigDir) },
		},
		{
			name: "scope sits inside the config directory",
			scopePath: func(config Config) string {
				inside := filepath.Join(config.ConfigDir, "inner")
				if err := os.Mkdir(inside, 0o700); err != nil {
					t.Fatalf("mkdir inner scope: %v", err)
				}
				return inside
			},
		},
	}

	for _, testCase := range cases {
		t.Run(testCase.name, func(t *testing.T) {
			config := newRuntimeFixture(t)
			scopePath := testCase.scopePath(config)

			writeFile(t, config.PolicyPath, "version: 1\n"+
				"scopes:\n"+
				"  project:\n"+
				"    path: "+scopePath+"\n"+
				"grants:\n"+
				"  - scope: project\n"+
				"    permissions: [read, list, stat]\n")

			runtime, err := Open(config, discardLogger())
			if err == nil {
				runtime.Close()
				t.Fatal("Open() = nil error, want a refusal for a scope overlapping the config directory")
			}
			if !strings.Contains(err.Error(), "overlaps the Node's config directory") {
				t.Fatalf("Open() = %v, want a message naming the config-directory overlap", err)
			}
		})
	}
}

// TestOpenDeniesThePolicyFileInsideAScope checks that the deny list still refuses
// the Node's own policy file when that file legitimately sits inside a scope.
//
// The policy path is configurable, so an operator may keep it beside the files it
// governs. The identity file cannot reach this situation any more, because no
// scope may overlap the config directory, so the policy file is the deny entry
// that still carries weight.
func TestOpenDeniesThePolicyFileInsideAScope(t *testing.T) {
	config := newRuntimeFixture(t)

	// Move the policy file into the scope directory, which is a layout the
	// operator can choose through CONNECTOR_NODE_POLICY_FILE.
	scopeDir := filepath.Join(filepath.Dir(config.ConfigDir), "project")
	config.PolicyPath = filepath.Join(scopeDir, "policy.yaml")
	writeFile(t, config.PolicyPath, "version: 1\n"+
		"scopes:\n"+
		"  project:\n"+
		"    path: "+scopeDir+"\n"+
		"grants:\n"+
		"  - scope: project\n"+
		"    permissions: [read]\n")

	runtime, err := Open(config, discardLogger())
	if err != nil {
		t.Fatalf("Open() = %v, want nil", err)
	}
	defer runtime.Close()

	scope, ok := runtime.Authority().Scope(security.Scope("project"))
	if !ok {
		t.Fatal("Scope(project) reported missing, want present")
	}

	// The policy file names the directories the Node serves, so a caller has no
	// business reading it even though it sits inside the scope.
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
