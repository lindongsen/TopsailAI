package node

import (
	"encoding/base64"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"topsailai_connector/internal/node/embedded"
	"topsailai_connector/internal/security"
)

// setEmbeddedIdentity installs an embedded node id and credential for one test and
// restores the previous values when the test ends.
//
// The values live in package-level variables because that is how the linker writes
// them, so a test has to mutate them. The restore is not optional: a test that left a
// credential in place would make every later test in the package behave as if it were
// an embedded build, and the failure would appear in an unrelated test.
func setEmbeddedIdentity(t *testing.T, nodeID string, credential string) {
	t.Helper()

	previousID := embedded.NodeID
	previousCredential := embedded.Credential
	t.Cleanup(func() {
		embedded.NodeID = previousID
		embedded.Credential = previousCredential
	})

	embedded.NodeID = nodeID
	embedded.Credential = credential
}

// setEmbeddedPolicy installs an embedded policy document for one test and restores
// the previous value when the test ends.
func setEmbeddedPolicy(t *testing.T, document string) {
	t.Helper()

	previous := embedded.PolicyBase64
	t.Cleanup(func() { embedded.PolicyBase64 = previous })

	if document == "" {
		embedded.PolicyBase64 = ""
		return
	}
	embedded.PolicyBase64 = base64.StdEncoding.EncodeToString([]byte(document))
}

// statelessEnvironment returns an environment that asks for stateless mode and names
// a config directory that does not exist, so a test can prove the directory is never
// created.
//
// The config directory is deliberately a path under a directory that does exist, so a
// creation attempt would succeed and be observable. A path whose parent is missing
// would fail for the wrong reason and prove nothing about the mode.
func statelessEnvironment(t *testing.T) (map[string]string, string) {
	t.Helper()

	configDir := filepath.Join(t.TempDir(), "never-created")
	return map[string]string{
		"CONNECTOR_NODE_SERVER_URL":   "wss://127.0.0.1:8443/channel",
		"CONNECTOR_NODE_TUNNEL_TOKEN": "tunnel-token-of-sufficient-length",
		"CONNECTOR_NODE_CONFIG_DIR":   configDir,
		"CONNECTOR_NODE_STATELESS":    "1",
	}, configDir
}

// TestLoadConfigStatelessCreatesNoDirectory pins the property the mode exists for: a
// Node started on a read-only filesystem must not create the config directory.
//
// The assertion is on the filesystem rather than on the returned value, because a
// Config that reported an empty directory while the directory had been created would
// satisfy a value-only check and still fail on the machine the mode is for.
func TestLoadConfigStatelessCreatesNoDirectory(t *testing.T) {
	environment, configDir := statelessEnvironment(t)
	setEmbeddedPolicy(t, "version: 1\nscopes: {}\ngrants: []\n")

	config, err := LoadConfig(lookupFrom(environment))
	if err != nil {
		t.Fatalf("LoadConfig() = %v, want nil", err)
	}

	if !config.Stateless {
		t.Fatal("Stateless = false, want true for CONNECTOR_NODE_STATELESS=1")
	}
	if config.ConfigDir != "" {
		t.Fatalf("ConfigDir = %q, want empty in stateless mode", config.ConfigDir)
	}
	if config.CredentialsPath != "" {
		t.Fatalf("CredentialsPath = %q, want empty in stateless mode", config.CredentialsPath)
	}

	if _, err := os.Stat(configDir); !os.IsNotExist(err) {
		t.Fatalf("stat %q = %v, want the directory not to exist", configDir, err)
	}
}

// TestLoadConfigStatelessIgnoresTheConfigDirectoryVariable checks that the variable is
// not read in this mode, so an operator who has it exported from an earlier file-backed
// run does not accidentally get a directory created.
func TestLoadConfigStatelessIgnoresTheConfigDirectoryVariable(t *testing.T) {
	environment, configDir := statelessEnvironment(t)
	setEmbeddedPolicy(t, "version: 1\nscopes: {}\ngrants: []\n")

	// A directory that already exists must not be adopted either: the mode has no
	// directory, so a value that happens to name one is not a value the mode uses.
	if err := os.Mkdir(configDir, 0o700); err != nil {
		t.Fatalf("mkdir %q: %v", configDir, err)
	}

	config, err := LoadConfig(lookupFrom(environment))
	if err != nil {
		t.Fatalf("LoadConfig() = %v, want nil", err)
	}
	if config.ConfigDir != "" {
		t.Fatalf("ConfigDir = %q, want empty even though the directory exists", config.ConfigDir)
	}
}

// TestResolveStatelessRejectsAnUnknownValue checks that a value the mode does not
// understand is refused rather than read as "off".
//
// A switch that decides whether the process may write to disk is a switch whose state
// must be statable. Reading `true` as "off" would start a file-backed Node on a machine
// the operator believed was running stateless, and the failure would appear as a
// permission error at startup rather than as a rejected configuration.
func TestResolveStatelessRejectsAnUnknownValue(t *testing.T) {
	accepted := map[string]bool{"": false, "0": false, "1": true}
	for value, want := range accepted {
		got, err := resolveStateless(value)
		if err != nil {
			t.Fatalf("resolveStateless(%q) = %v, want nil", value, err)
		}
		if got != want {
			t.Fatalf("resolveStateless(%q) = %v, want %v", value, got, want)
		}
	}

	for _, value := range []string{"true", "yes", "on", "2", " 1", "1 "} {
		if _, err := resolveStateless(value); err == nil {
			t.Fatalf("resolveStateless(%q) = nil error, want a refusal", value)
		} else if !strings.Contains(err.Error(), "1, 0 or empty") {
			t.Fatalf("resolveStateless(%q) = %q, want it to name the accepted values", value, err)
		}
	}
}

// TestLoadConfigStatelessRefusesAMissingPolicy checks that a stateless build with no
// embedded policy and no policy file is refused, naming both ways to supply one.
//
// The default policy path lives inside the config directory, which does not exist in
// this mode, so there is no default to fall back to. A Node that started with no policy
// would refuse every request while looking like a working Node.
func TestLoadConfigStatelessRefusesAMissingPolicy(t *testing.T) {
	environment, _ := statelessEnvironment(t)
	setEmbeddedPolicy(t, "")

	_, err := LoadConfig(lookupFrom(environment))
	if err == nil {
		t.Fatal("LoadConfig() = nil error, want a refusal for a stateless node with no policy")
	}
	for _, want := range []string{"CONNECTOR_NODE_POLICY_FILE", "compiled"} {
		if !strings.Contains(err.Error(), want) {
			t.Fatalf("LoadConfig() = %q, want it to mention %q", err, want)
		}
	}
}

// TestLoadConfigStatelessAcceptsAPolicyFile checks that the operator's absolute policy
// path is still honoured in this mode, because it is the only way to supply a policy to
// a build that embedded none.
func TestLoadConfigStatelessAcceptsAPolicyFile(t *testing.T) {
	environment, _ := statelessEnvironment(t)
	setEmbeddedPolicy(t, "")

	policyPath := filepath.Join(t.TempDir(), "policy.yaml")
	writeFile(t, policyPath, "version: 1\nscopes: {}\ngrants: []\n")
	environment["CONNECTOR_NODE_POLICY_FILE"] = policyPath

	config, err := LoadConfig(lookupFrom(environment))
	if err != nil {
		t.Fatalf("LoadConfig() = %v, want nil", err)
	}
	if config.PolicyPath != policyPath {
		t.Fatalf("PolicyPath = %q, want %q", config.PolicyPath, policyPath)
	}
	if config.PolicyBytes != nil {
		t.Fatal("PolicyBytes is set, want nil when the policy comes from a file")
	}
}

// TestLoadConfigStatelessRefusesARelativePolicyFile checks that the relative-path rule
// still applies in this mode, because a relative path resolves differently per launch
// and the mode does not change that.
func TestLoadConfigStatelessRefusesARelativePolicyFile(t *testing.T) {
	environment, _ := statelessEnvironment(t)
	setEmbeddedPolicy(t, "")
	environment["CONNECTOR_NODE_POLICY_FILE"] = "policy.yaml"

	if _, err := LoadConfig(lookupFrom(environment)); err == nil {
		t.Fatal("LoadConfig() = nil error, want a refusal for a relative policy path")
	}
}

// TestConfigRedactedReportsStateless checks that a log line names the mode instead of
// printing two empty values, because an empty config_dir= reads as a configuration
// mistake and sends the operator looking for a directory the mode avoids creating.
func TestConfigRedactedReportsStateless(t *testing.T) {
	environment, _ := statelessEnvironment(t)
	setEmbeddedPolicy(t, "version: 1\nscopes: {}\ngrants: []\n")

	config, err := LoadConfig(lookupFrom(environment))
	if err != nil {
		t.Fatalf("LoadConfig() = %v, want nil", err)
	}

	rendered := config.Redacted()
	if !strings.Contains(rendered, "config_dir=stateless") {
		t.Fatalf("Redacted() = %q, want it to report the mode", rendered)
	}
	if !strings.Contains(rendered, "credentials=stateless") {
		t.Fatalf("Redacted() = %q, want it to report the mode for the credentials", rendered)
	}
	if strings.Contains(rendered, environment["CONNECTOR_NODE_TUNNEL_TOKEN"]) {
		t.Fatalf("Redacted() = %q, want it to hide the tunnel token", rendered)
	}
}

// TestStatelessRequestedReportsTheMode checks the helper a subcommand uses to refuse
// before it resolves a config directory.
//
// The helper exists because resolving a directory creates it, so a subcommand that
// resolved first and checked afterwards would have created the directory the mode
// exists to avoid.
func TestStatelessRequestedReportsTheMode(t *testing.T) {
	stateless, err := StatelessRequested(lookupFrom(map[string]string{"CONNECTOR_NODE_STATELESS": "1"}))
	if err != nil {
		t.Fatalf("StatelessRequested() = %v, want nil", err)
	}
	if !stateless {
		t.Fatal("StatelessRequested() = false, want true")
	}

	stateless, err = StatelessRequested(lookupFrom(map[string]string{}))
	if err != nil {
		t.Fatalf("StatelessRequested() = %v, want nil", err)
	}
	if stateless {
		t.Fatal("StatelessRequested() = true for an unset variable, want false")
	}

	if _, err := StatelessRequested(lookupFrom(map[string]string{"CONNECTOR_NODE_STATELESS": "true"})); err == nil {
		t.Fatal("StatelessRequested() = nil error, want a refusal for an unknown value")
	}
	if _, err := StatelessRequested(nil); err == nil {
		t.Fatal("StatelessRequested(nil) = nil error, want a refusal")
	}
}

// newStatelessFixture builds a stateless configuration whose policy names one real
// scope directory, so Open has something to serve without a config directory.
//
// The base directory is returned alongside the configuration so a test can prove the
// start added no entry to the tree, rather than only checking the paths it expected.
func newStatelessFixture(t *testing.T) (Config, string) {
	t.Helper()

	base := t.TempDir()
	scopeDir := filepath.Join(base, "project")
	if err := os.Mkdir(scopeDir, 0o755); err != nil {
		t.Fatalf("mkdir scope dir: %v", err)
	}
	writeFile(t, filepath.Join(scopeDir, "inside.txt"), "inside content")

	document := "version: 1\n" +
		"scopes:\n" +
		"  project:\n" +
		"    path: " + scopeDir + "\n" +
		"grants:\n" +
		"  - scope: project\n" +
		"    permissions: [read, list, stat]\n"

	return Config{
		ServerURL:      "wss://127.0.0.1:8443/channel",
		TunnelToken:    security.Secret("tunnel-token-of-sufficient-length"),
		PolicyBytes:    []byte(document),
		Stateless:      true,
		ReplayWindow:   security.DefaultReplayWindow,
		ReplayCapacity: security.DefaultReplayCapacity,
	}, base
}

// TestOpenStatelessWritesNothing pins the whole point of the mode: a start leaves no
// file behind anywhere.
//
// The check walks the temporary tree rather than naming the three files, because a
// write to a path the test did not think of would pass a check that only looked at the
// paths it expected.
func TestOpenStatelessWritesNothing(t *testing.T) {
	config, base := newStatelessFixture(t)

	before := countEntries(t, base)

	runtime, err := Open(config, discardLogger())
	if err != nil {
		t.Fatalf("Open() = %v, want nil", err)
	}
	defer runtime.Close()

	after := countEntries(t, base)
	if after != before {
		t.Fatalf("the tree held %d entries before the start and %d after, want no new entry", before, after)
	}
	if runtime.Config().ConfigDir != "" {
		t.Fatalf("Config().ConfigDir = %q, want empty", runtime.Config().ConfigDir)
	}
}

// TestOpenStatelessUsesTheEmbeddedIdentityAndCredential checks that a build which
// carries an identity and a credential answers to them without writing a file.
//
// This is the combination the mode is most useful for: a read-only machine that must
// still have a stable address and a known secret.
func TestOpenStatelessUsesTheEmbeddedIdentityAndCredential(t *testing.T) {
	config, _ := newStatelessFixture(t)

	nodeID, err := security.NewNodeID()
	if err != nil {
		t.Fatalf("generate a node id: %v", err)
	}
	credential, err := security.NewCredentialWithKeyID("bundle-caller")
	if err != nil {
		t.Fatalf("generate a credential: %v", err)
	}
	setEmbeddedIdentity(t, nodeID, credential.String())

	runtime, err := Open(config, discardLogger())
	if err != nil {
		t.Fatalf("Open() = %v, want nil", err)
	}
	defer runtime.Close()

	if runtime.IdentityID() != nodeID {
		t.Fatalf("IdentityID() = %q, want the embedded %q", runtime.IdentityID(), nodeID)
	}
	// An embedded id is the same value on every start, so this start did not create it.
	// Reporting it as created would tell the operator to expect a different address after
	// a restart, which is the opposite of what an embedded id does.
	if _, created := runtime.NewIdentity(); created {
		t.Fatal("NewIdentity() reports the id as created, want false because the id was embedded rather than generated")
	}
	if runtime.NewCredential() != nil {
		t.Fatal("NewCredential() is set, want nil because the credential was embedded rather than generated")
	}

	list, err := runtime.CredentialList()
	if err != nil {
		t.Fatalf("CredentialList() = %v, want nil", err)
	}
	if len(list) != 1 {
		t.Fatalf("CredentialList() = %d entries, want 1", len(list))
	}
	if list[0].KeyID != "bundle-caller" {
		t.Fatalf("CredentialList()[0].KeyID = %q, want bundle-caller", list[0].KeyID)
	}
	if !list[0].Secret.Equal(credential.Secret) {
		t.Fatal("CredentialList()[0].Secret does not match the embedded secret")
	}

	// The credential must actually verify, not merely be reported: a set built from a
	// value the verifier cannot use would pass a comparison and refuse every caller.
	if _, ok := runtime.IdentityHolder().Credentials().Lookup("bundle-caller"); !ok {
		t.Fatal("Lookup(bundle-caller) = false, want the embedded credential to be usable")
	}
}

// TestOpenStatelessGeneratesInMemoryWhenNothingIsEmbedded checks that a build with
// nothing embedded still starts, generating both values in memory.
//
// The generated credential is returned once so the caller can print it. A stateless Node
// that generated a credential and did not report it would be a Node nobody can reach,
// because there is no file to read it back from.
func TestOpenStatelessGeneratesInMemoryWhenNothingIsEmbedded(t *testing.T) {
	config, _ := newStatelessFixture(t)
	setEmbeddedIdentity(t, "", "")

	runtime, err := Open(config, discardLogger())
	if err != nil {
		t.Fatalf("Open() = %v, want nil", err)
	}
	defer runtime.Close()

	if err := security.ValidateNodeID(runtime.IdentityID()); err != nil {
		t.Fatalf("IdentityID() = %q, which is invalid: %v", runtime.IdentityID(), err)
	}

	// A random id is new on every start, so this start did create it. The startup summary
	// relies on this to say "created in memory" rather than "written", and a stateless
	// Node that reported false here would print nothing about the id at all.
	if _, created := runtime.NewIdentity(); !created {
		t.Fatal("NewIdentity() reports the id as not created, want true because a random id was generated in memory")
	}

	created := runtime.NewCredential()
	if created == nil {
		t.Fatal("NewCredential() = nil, want the credential this start generated")
	}
	if created.KeyID == "" || created.Secret == "" {
		t.Fatalf("NewCredential() = %+v, want both halves set", created)
	}
	if _, ok := runtime.IdentityHolder().Credentials().Lookup(created.KeyID); !ok {
		t.Fatalf("Lookup(%q) = false, want the generated credential to be usable", created.KeyID)
	}

	// The value is returned once and never stored, so a second call reports nothing.
	if runtime.NewCredential() != nil {
		t.Fatal("NewCredential() returned a value twice, want it to be released after the first call")
	}
}

// TestOpenStatelessRefusesAMalformedEmbeddedIdentity checks that a packaging mistake is
// a startup failure rather than a silent fallback to a random address.
//
// A fallback would produce a Node that works and answers to an address the operator
// cannot find, which is the failure the packaging feature exists to prevent.
func TestOpenStatelessRefusesAMalformedEmbeddedIdentity(t *testing.T) {
	config, _ := newStatelessFixture(t)
	setEmbeddedIdentity(t, "not-a-node-id", "")

	if _, err := Open(config, discardLogger()); err == nil {
		t.Fatal("Open() = nil error, want a refusal for a malformed embedded node id")
	}
}

// TestOpenStatelessRefusesAMalformedEmbeddedCredential checks the same property for the
// credential, because a malformed secret would authenticate nothing while looking
// present.
func TestOpenStatelessRefusesAMalformedEmbeddedCredential(t *testing.T) {
	config, _ := newStatelessFixture(t)
	setEmbeddedIdentity(t, "", "no-dot-in-this-value")

	if _, err := Open(config, discardLogger()); err == nil {
		t.Fatal("Open() = nil error, want a refusal for a malformed embedded credential")
	}
}

// TestOpenStatelessStillRefusesAScopeThatOverlapsTheConfigDirectory is not applicable,
// because the mode has no config directory. The property that replaces it is that the
// deny list carries no empty entry, which would otherwise refuse every path.
func TestOpenStatelessServesAScopeThatWouldOverlapAConfigDirectory(t *testing.T) {
	config, _ := newStatelessFixture(t)
	setEmbeddedIdentity(t, "", "")

	runtime, err := Open(config, discardLogger())
	if err != nil {
		t.Fatalf("Open() = %v, want nil", err)
	}
	defer runtime.Close()

	scope, ok := runtime.Authority().Scope("project")
	if !ok {
		t.Fatal("Scope(project) = false, want the scope to be defined")
	}
	if scope.Absent() {
		t.Fatal("Scope(project).Absent() = true, want the directory to be present")
	}
}

// TestListScopeNamesStatelessCreatesNoDirectory checks that `scope list` does not create
// the config directory in this mode.
//
// The subcommand reads the policy without dialling, and it used to resolve the config
// directory first. A listing that created a directory would be a read-only command with
// a write side effect, which is the defect the mode makes visible.
func TestListScopeNamesStatelessCreatesNoDirectory(t *testing.T) {
	environment, configDir := statelessEnvironment(t)
	setEmbeddedPolicy(t, "version: 1\nscopes:\n  project:\n    path: /tmp\ngrants: []\n")

	names, err := ListScopeNames(lookupFrom(environment))
	if err != nil {
		t.Fatalf("ListScopeNames() = %v, want nil", err)
	}
	if len(names) != 1 || names[0] != "project" {
		t.Fatalf("ListScopeNames() = %v, want [project]", names)
	}

	if _, err := os.Stat(configDir); !os.IsNotExist(err) {
		t.Fatalf("stat %q = %v, want the directory not to exist", configDir, err)
	}
}

// countEntries returns the number of entries in a directory tree, so a test can prove a
// start added nothing without naming the paths it expected.
func countEntries(t *testing.T, root string) int {
	t.Helper()

	total := 0
	err := filepath.Walk(root, func(path string, info os.FileInfo, err error) error {
		if err != nil {
			return err
		}
		if path != root {
			total++
		}
		return nil
	})
	if err != nil {
		t.Fatalf("walk %q: %v", root, err)
	}
	return total
}
