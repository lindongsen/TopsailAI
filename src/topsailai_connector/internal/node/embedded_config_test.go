package node

import (
	"encoding/base64"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"topsailai_connector/internal/node/embedded"
	"topsailai_connector/internal/protocol"
)

// setEmbedded installs an embedded configuration for one test and restores the
// previous values when the test ends.
//
// The values live in package-level variables because that is how the linker
// writes them, so a test has to mutate them. The restore is not optional: a test
// that left a tunnel token in place would make every later test in the package
// behave as if it were an embedded build, and the failure would appear in an
// unrelated test.
func setEmbedded(t *testing.T, serverURL string, tunnelToken string, policyDocument string) {
	t.Helper()

	previousURL := embedded.ServerURL
	previousToken := embedded.TunnelToken
	previousPolicy := embedded.PolicyBase64
	t.Cleanup(func() {
		embedded.ServerURL = previousURL
		embedded.TunnelToken = previousToken
		embedded.PolicyBase64 = previousPolicy
	})

	embedded.ServerURL = serverURL
	embedded.TunnelToken = tunnelToken
	if policyDocument == "" {
		embedded.PolicyBase64 = ""
		return
	}
	embedded.PolicyBase64 = base64.StdEncoding.EncodeToString([]byte(policyDocument))
}

// TestLoadConfigUsesEmbeddedValuesWhenTheEnvironmentIsEmpty checks that a build
// with a compiled-in configuration starts with no environment at all.
//
// This is the whole point of the feature: the person receiving the binary runs it
// and it connects. A test that supplied the environment would prove nothing about
// that case.
func TestLoadConfigUsesEmbeddedValuesWhenTheEnvironmentIsEmpty(t *testing.T) {
	configDir := t.TempDir()
	setEmbedded(t, "wss://embedded.example.com:8443/channel", "embedded-tunnel-token-of-length", "version: 1\nscopes: {}\ngrants: []\n")

	config, err := LoadConfig(lookupFrom(map[string]string{
		"CONNECTOR_NODE_CONFIG_DIR": configDir,
	}))
	if err != nil {
		t.Fatalf("LoadConfig() = %v, want nil", err)
	}

	if config.ServerURL != "wss://embedded.example.com:8443/channel" {
		t.Fatalf("ServerURL = %q, want the embedded value", config.ServerURL)
	}
	if !config.TunnelToken.Equal("embedded-tunnel-token-of-length") {
		t.Fatal("TunnelToken does not match the embedded value")
	}
	if config.PolicyBytes == nil {
		t.Fatal("PolicyBytes = nil, want the embedded policy")
	}
	if config.PolicyPath != "" {
		t.Fatalf("PolicyPath = %q, want empty for an embedded policy", config.PolicyPath)
	}
}

// TestLoadConfigPrefersTheEnvironmentOverEmbeddedValues checks that an operator
// can point the same binary at a different Server without a rebuild.
//
// The precedence is field by field, so overriding the token does not discard the
// embedded Server URL. A whole-config override would be a second way to configure
// the Node, and the two would eventually disagree.
func TestLoadConfigPrefersTheEnvironmentOverEmbeddedValues(t *testing.T) {
	configDir := t.TempDir()
	setEmbedded(t, "wss://embedded.example.com:8443/channel", "embedded-tunnel-token-of-length", "version: 1\nscopes: {}\ngrants: []\n")

	config, err := LoadConfig(lookupFrom(map[string]string{
		"CONNECTOR_NODE_CONFIG_DIR":   configDir,
		"CONNECTOR_NODE_TUNNEL_TOKEN": "environment-token-of-sufficient-length",
	}))
	if err != nil {
		t.Fatalf("LoadConfig() = %v, want nil", err)
	}

	if !config.TunnelToken.Equal("environment-token-of-sufficient-length") {
		t.Fatal("TunnelToken did not take the environment value")
	}
	if config.ServerURL != "wss://embedded.example.com:8443/channel" {
		t.Fatalf("ServerURL = %q, want the embedded value to survive a token override", config.ServerURL)
	}
}

// TestLoadConfigRefusesAPolicyFileWhenThePolicyIsEmbedded checks that the two
// policy sources cannot both be configured.
//
// An embedded policy is a whole document. Letting a file path replace it would
// silently swap every scope and every grant, and the operator would be debugging
// a permission problem in a policy they did not write.
func TestLoadConfigRefusesAPolicyFileWhenThePolicyIsEmbedded(t *testing.T) {
	configDir := t.TempDir()
	setEmbedded(t, "wss://embedded.example.com:8443/channel", "embedded-tunnel-token-of-length", "version: 1\nscopes: {}\ngrants: []\n")

	_, err := LoadConfig(lookupFrom(map[string]string{
		"CONNECTOR_NODE_CONFIG_DIR":  configDir,
		"CONNECTOR_NODE_POLICY_FILE": filepath.Join(configDir, "policy.yaml"),
	}))
	if err == nil {
		t.Fatal("LoadConfig() = nil error, want a refusal for two policy sources")
	}
	if !strings.Contains(err.Error(), "compiled its policy in") {
		t.Fatalf("LoadConfig() = %v, want a message naming the embedded policy", err)
	}
}

// TestLoadConfigRefusesAMalformedEmbeddedPolicy checks that a packaging mistake
// surfaces as a startup failure with a message rather than as a crash.
//
// The value is base64 because a YAML document does not survive a linker flag
// intact. A value that is not base64 is therefore the most likely packaging
// mistake, and it must be reported by name.
func TestLoadConfigRefusesAMalformedEmbeddedPolicy(t *testing.T) {
	configDir := t.TempDir()
	setEmbedded(t, "wss://embedded.example.com:8443/channel", "embedded-tunnel-token-of-length", "")
	embedded.PolicyBase64 = "not base64!!"

	_, err := LoadConfig(lookupFrom(map[string]string{
		"CONNECTOR_NODE_CONFIG_DIR": configDir,
	}))
	if err == nil {
		t.Fatal("LoadConfig() = nil error, want a refusal for a malformed embedded policy")
	}
	if !strings.Contains(err.Error(), "embedded policy") {
		t.Fatalf("LoadConfig() = %v, want a message naming the embedded policy", err)
	}
}

// TestLoadConfigStillRequiresASecretWithoutAnEmbeddedOne checks that a normal
// build keeps its startup refusal.
//
// The embedded path must not become a way to start a Node with no secret: a Node
// that started without one would be a Node whose operator believes it is serving
// something it is not.
func TestLoadConfigStillRequiresASecretWithoutAnEmbeddedOne(t *testing.T) {
	configDir := t.TempDir()
	setEmbedded(t, "", "", "")

	// The Server URL is supplied so the failure under test is the missing token.
	// With both absent the URL check runs first, and a test that accepted either
	// message would pass even if the token check had been deleted.
	_, err := LoadConfig(lookupFrom(map[string]string{
		"CONNECTOR_NODE_CONFIG_DIR": configDir,
		"CONNECTOR_NODE_SERVER_URL": "wss://127.0.0.1:8443/channel",
	}))
	if err == nil {
		t.Fatal("LoadConfig() = nil error, want a refusal for a missing secret")
	}
	if !strings.Contains(err.Error(), "CONNECTOR_NODE_TUNNEL_TOKEN") {
		t.Fatalf("LoadConfig() = %v, want a message naming the missing variable", err)
	}
}

// TestLoadAuthorityBytesAppliesTheSameValidationAsTheFile checks that an embedded
// policy is not a more trusted policy.
//
// The embedded document is written by the same person as a file and is subject to
// the same mistakes, so it goes through the same strict decoding. A second, looser
// parser would be a second definition of a valid policy.
func TestLoadAuthorityBytesAppliesTheSameValidationAsTheFile(t *testing.T) {
	cases := []struct {
		name     string
		document string
		want     string
	}{
		{
			name:     "unknown key",
			document: "version: 1\nscopes: {}\ngrants: []\nunknown_key: true\n",
			want:     "unknown_key",
		},
		{
			name:     "empty document",
			document: "",
			want:     "empty",
		},
		{
			name:     "grant names an undefined scope",
			document: "version: 1\nscopes: {}\ngrants:\n  - scope: missing\n    permissions: [read]\n",
			want:     "missing",
		},
	}

	for _, testCase := range cases {
		t.Run(testCase.name, func(t *testing.T) {
			authority, err := LoadAuthorityBytes([]byte(testCase.document), nil, "")
			if err == nil {
				authority.Close()
				t.Fatalf("LoadAuthorityBytes(%q) = nil error, want a refusal", testCase.name)
			}
			if !strings.Contains(err.Error(), testCase.want) {
				t.Fatalf("LoadAuthorityBytes(%q) = %v, want a message containing %q", testCase.name, err, testCase.want)
			}
		})
	}
}

// TestLoadAuthorityBytesOpensTheScopesItDefines checks that the embedded path
// produces a working authority rather than only a validated document.
//
// A test that stopped at "no error" would pass for an authority with no scopes,
// which is the failure mode that looks like a working Node denying everything.
func TestLoadAuthorityBytesOpensTheScopesItDefines(t *testing.T) {
	base := t.TempDir()
	scopeRoot := filepath.Join(base, "project")
	if err := os.MkdirAll(scopeRoot, 0o755); err != nil {
		t.Fatalf("create scope root: %v", err)
	}
	writeFile(t, filepath.Join(scopeRoot, "notes.md"), "hello\n")

	document := "version: 1\n" +
		"scopes:\n" +
		"  project:\n" +
		"    path: " + scopeRoot + "\n" +
		"grants:\n" +
		"  - scope: project\n" +
		"    permissions: [read]\n"

	authority, err := LoadAuthorityBytes([]byte(document), nil, "")
	if err != nil {
		t.Fatalf("LoadAuthorityBytes() = %v, want nil", err)
	}
	defer authority.Close()

	scope, err := authority.AuthorizeOperation(protocol.OperationFileRead, "project")
	if err != nil {
		t.Fatalf("AuthorizeOperation(file.read) = %v, want nil", err)
	}
	content, _, err := scope.Read("notes.md", 0, 0)
	if err != nil {
		t.Fatalf("Read(notes.md) = %v, want nil", err)
	}
	if string(content) != "hello\n" {
		t.Fatalf("Read(notes.md) = %q, want %q", content, "hello\n")
	}
}

// TestOpenRefusesTheRunningExecutableWhenTheBinaryCarriesASecret checks the
// protection that makes an embedded tunnel token survivable.
//
// The tunnel token is Server-wide: a caller who reads it can open a channel and
// impersonate any Node, not just this one. A build that carries it therefore
// refuses to serve its own executable, and the refusal must hold for read, list
// and stat alike, because a listing that reports the binary's size is already a
// disclosure.
func TestOpenRefusesTheRunningExecutableWhenTheBinaryCarriesASecret(t *testing.T) {
	executable, err := os.Executable()
	if err != nil {
		t.Fatalf("os.Executable() = %v", err)
	}
	executableDir := filepath.Dir(executable)

	// The scope is the directory holding the test binary, so the executable is a
	// legitimate entry inside it. That is the case the deny list has to catch: a
	// scope that contains the binary is exactly what a whole-volume scope is.
	document := "version: 1\n" +
		"scopes:\n" +
		"  bin:\n" +
		"    path: " + executableDir + "\n" +
		"grants:\n" +
		"  - scope: bin\n" +
		"    permissions: [read, list, stat]\n"

	setEmbedded(t, "wss://embedded.example.com:8443/channel", "embedded-tunnel-token-of-length", document)

	configDir := t.TempDir()
	config, err := LoadConfig(lookupFrom(map[string]string{
		"CONNECTOR_NODE_CONFIG_DIR": configDir,
	}))
	if err != nil {
		t.Fatalf("LoadConfig() = %v, want nil", err)
	}

	runtime, err := Open(config, nil)
	if err != nil {
		t.Fatalf("Open() = %v, want nil", err)
	}
	defer runtime.Close()

	scope, err := runtime.Authority().AuthorizeOperation(protocol.OperationFileRead, "bin")
	if err != nil {
		t.Fatalf("AuthorizeOperation(file.read) = %v, want nil", err)
	}

	name := filepath.Base(executable)
	if _, _, err := scope.Read(name, 0, 0); err == nil {
		t.Fatal("Read(executable) = nil error, want a refusal: the binary carries the tunnel token")
	} else if CodeOf(err) != protocol.CodeDenied {
		t.Fatalf("Read(executable) = %v, want code denied", err)
	}

	if _, err := scope.Stat(name); err == nil {
		t.Fatal("Stat(executable) = nil error, want a refusal")
	} else if CodeOf(err) != protocol.CodeDenied {
		t.Fatalf("Stat(executable) = %v, want code denied", err)
	}

	entries, err := scope.List("")
	if err != nil {
		t.Fatalf("List() = %v, want nil", err)
	}
	for _, entry := range entries {
		if entry.Name == name {
			t.Fatalf("List() reported %q, want the executable omitted", name)
		}
	}
}

// TestOpenServesTheRunningExecutableWhenTheBinaryCarriesNoSecret checks that a
// normal build is not refused.
//
// The deny entry exists because the binary holds a secret. A normal build holds
// none, so reading it discloses nothing a caller could not read from the source,
// and refusing it would break a legitimate use such as serving the directory the
// Node was installed in.
func TestOpenServesTheRunningExecutableWhenTheBinaryCarriesNoSecret(t *testing.T) {
	executable, err := os.Executable()
	if err != nil {
		t.Fatalf("os.Executable() = %v", err)
	}
	executableDir := filepath.Dir(executable)

	base := t.TempDir()
	policyPath := filepath.Join(base, "policy.yaml")
	writeFile(t, policyPath, "version: 1\n"+
		"scopes:\n"+
		"  bin:\n"+
		"    path: "+executableDir+"\n"+
		"grants:\n"+
		"  - scope: bin\n"+
		"    permissions: [read, list, stat]\n")

	setEmbedded(t, "", "", "")

	configDir := t.TempDir()
	config, err := LoadConfig(lookupFrom(map[string]string{
		"CONNECTOR_NODE_CONFIG_DIR":   configDir,
		"CONNECTOR_NODE_SERVER_URL":   "wss://127.0.0.1:8443/channel",
		"CONNECTOR_NODE_TUNNEL_TOKEN": "environment-token-of-sufficient-length",
		"CONNECTOR_NODE_POLICY_FILE":  policyPath,
	}))
	if err != nil {
		t.Fatalf("LoadConfig() = %v, want nil", err)
	}

	runtime, err := Open(config, nil)
	if err != nil {
		t.Fatalf("Open() = %v, want nil", err)
	}
	defer runtime.Close()

	scope, err := runtime.Authority().AuthorizeOperation(protocol.OperationFileStat, "bin")
	if err != nil {
		t.Fatalf("AuthorizeOperation(file.stat) = %v, want nil", err)
	}

	entry, err := scope.Stat(filepath.Base(executable))
	if err != nil {
		t.Fatalf("Stat(executable) = %v, want nil for a build that carries no secret", err)
	}
	if entry.Type != "file" {
		t.Fatalf("Stat(executable).Type = %q, want file", entry.Type)
	}
}
