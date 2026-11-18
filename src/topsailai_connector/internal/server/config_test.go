package server

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"topsailai_connector/internal/security"
)

// environment builds a lookup function from a map, so a test never mutates the
// process environment.
func environment(values map[string]string) func(string) string {
	return func(name string) string {
		return values[name]
	}
}

// testClientSecret is the secret the fixture credential file carries.
const testClientSecret = "client-secret-0123456789abcdefghij"

// writeClientCredentialFile writes a credential file and returns its absolute path.
//
// The Server reads its client credentials from a file rather than from an
// environment variable, because one variable cannot express several public key
// identifiers. A test therefore needs a real file, and the file is written under the
// test's own temporary directory so it cannot collide with another test.
func writeClientCredentialFile(t *testing.T, credentials ...security.Credential) string {
	t.Helper()
	if len(credentials) == 0 {
		credential, err := security.NewCredentialWithKeyID("operator")
		if err != nil {
			t.Fatalf("NewCredentialWithKeyID() = %v", err)
		}
		credentials = []security.Credential{credential}
	}
	content, err := security.FormatCredentialSet(credentials)
	if err != nil {
		t.Fatalf("FormatCredentialSet() = %v", err)
	}
	path := filepath.Join(t.TempDir(), "client-credentials.yaml")
	if err := os.WriteFile(path, content, 0o600); err != nil {
		t.Fatalf("write credential file: %v", err)
	}
	return path
}

// validEnvironment is the smallest environment that starts a Server.
func validEnvironment(t *testing.T) map[string]string {
	t.Helper()
	return map[string]string{
		"CONNECTOR_SERVER_TUNNEL_TOKEN":            "tunnel-token-0123456789",
		"CONNECTOR_SERVER_CLIENT_CREDENTIALS_FILE": writeClientCredentialFile(t),
	}
}

func TestLoadConfigAcceptsMinimalEnvironment(t *testing.T) {
	config, err := LoadConfig(environment(validEnvironment(t)))
	if err != nil {
		t.Fatalf("LoadConfig: %v", err)
	}
	if config.Listen != DefaultListenAddress {
		t.Errorf("Listen = %q, want %q", config.Listen, DefaultListenAddress)
	}
	if config.RequestTimeout != DefaultRequestTimeout {
		t.Errorf("RequestTimeout = %s, want %s", config.RequestTimeout, DefaultRequestTimeout)
	}
	if config.TLSEnabled() {
		t.Error("TLSEnabled = true, want false when no certificate is configured")
	}
	if config.TunnelToken != security.Secret("tunnel-token-0123456789") {
		t.Error("TunnelToken was not carried through")
	}
	if config.ClientCredentials == nil {
		t.Fatal("ClientCredentials is nil, want the parsed set")
	}
	if config.ClientCredentials.Len() != 1 {
		t.Errorf("ClientCredentials holds %d entries, want 1", config.ClientCredentials.Len())
	}
	if config.ReplayWindow != security.DefaultReplayWindow {
		t.Errorf("ReplayWindow = %s, want %s", config.ReplayWindow, security.DefaultReplayWindow)
	}
	if config.ReplayCapacity != security.DefaultReplayCapacity {
		t.Errorf("ReplayCapacity = %d, want %d", config.ReplayCapacity, security.DefaultReplayCapacity)
	}
}

func TestLoadConfigRejectsNilLookup(t *testing.T) {
	if _, err := LoadConfig(nil); err == nil {
		t.Fatal("LoadConfig(nil) = nil error, want a failure")
	}
}

func TestLoadConfigRejectsMissingSecrets(t *testing.T) {
	cases := []struct {
		name   string
		remove string
	}{
		{name: "tunnel token missing", remove: "CONNECTOR_SERVER_TUNNEL_TOKEN"},
		{name: "client credential file missing", remove: "CONNECTOR_SERVER_CLIENT_CREDENTIALS_FILE"},
	}
	for _, testCase := range cases {
		t.Run(testCase.name, func(t *testing.T) {
			values := validEnvironment(t)
			delete(values, testCase.remove)
			if _, err := LoadConfig(environment(values)); err == nil {
				t.Fatalf("LoadConfig with %s removed = nil error, want a failure", testCase.remove)
			}
		})
	}
}

// TestLoadConfigRejectsAMissingCredentialFile checks that a path which does not exist
// is a startup failure rather than an empty credential set.
//
// An empty set refuses every caller and looks exactly like a working Server that
// denies everything, which is the failure mode a startup refusal exists to prevent.
func TestLoadConfigRejectsAMissingCredentialFile(t *testing.T) {
	values := validEnvironment(t)
	values["CONNECTOR_SERVER_CLIENT_CREDENTIALS_FILE"] = filepath.Join(t.TempDir(), "absent.yaml")
	_, err := LoadConfig(environment(values))
	if err == nil {
		t.Fatal("LoadConfig with an absent credential file = nil error, want a failure")
	}
	if !strings.Contains(err.Error(), "CONNECTOR_SERVER_CLIENT_CREDENTIALS_FILE") {
		t.Errorf("error %q does not name the offending variable", err)
	}
}

// TestLoadConfigRejectsARelativeCredentialFile checks that the path must be absolute.
//
// A relative path resolves differently per launch, so the same Server started from two
// directories would verify proofs against two different credential sets.
func TestLoadConfigRejectsARelativeCredentialFile(t *testing.T) {
	values := validEnvironment(t)
	values["CONNECTOR_SERVER_CLIENT_CREDENTIALS_FILE"] = "client-credentials.yaml"
	if _, err := LoadConfig(environment(values)); err == nil {
		t.Fatal("LoadConfig with a relative credential file = nil error, want a failure")
	}
}

// TestLoadConfigRejectsADirectoryAsCredentialFile checks that a directory is refused
// rather than read.
func TestLoadConfigRejectsADirectoryAsCredentialFile(t *testing.T) {
	values := validEnvironment(t)
	values["CONNECTOR_SERVER_CLIENT_CREDENTIALS_FILE"] = t.TempDir()
	if _, err := LoadConfig(environment(values)); err == nil {
		t.Fatal("LoadConfig with a directory as the credential file = nil error, want a failure")
	}
}

// TestLoadConfigRejectsAShortCredentialSecret checks that a secret too short to be an
// HMAC key is refused at startup.
func TestLoadConfigRejectsAShortCredentialSecret(t *testing.T) {
	path := filepath.Join(t.TempDir(), "client-credentials.yaml")
	content := "version: 1\ncredentials:\n  - key_id: operator\n    secret: short\n"
	if err := os.WriteFile(path, []byte(content), 0o600); err != nil {
		t.Fatalf("write credential file: %v", err)
	}
	values := validEnvironment(t)
	values["CONNECTOR_SERVER_CLIENT_CREDENTIALS_FILE"] = path
	_, err := LoadConfig(environment(values))
	if err == nil {
		t.Fatal("LoadConfig with a short secret = nil error, want a failure")
	}
	if !strings.Contains(err.Error(), "CONNECTOR_SERVER_CLIENT_CREDENTIALS_FILE") {
		t.Errorf("error %q does not name the offending variable", err)
	}
}

func TestLoadConfigRejectsBadListenAddress(t *testing.T) {
	cases := []struct {
		name   string
		listen string
	}{
		{name: "no port", listen: "127.0.0.1"},
		{name: "empty port", listen: "127.0.0.1:"},
		{name: "non numeric port", listen: "127.0.0.1:http"},
		{name: "port zero", listen: "127.0.0.1:0"},
		{name: "port too large", listen: "127.0.0.1:70000"},
		{name: "garbage", listen: "not an address"},
		{name: "whitespace around host", listen: " 127.0.0.1:8443"},
	}
	for _, testCase := range cases {
		t.Run(testCase.name, func(t *testing.T) {
			values := validEnvironment(t)
			values["CONNECTOR_SERVER_LISTEN"] = testCase.listen
			if _, err := LoadConfig(environment(values)); err == nil {
				t.Fatalf("LoadConfig with listen %q = nil error, want a failure", testCase.listen)
			}
		})
	}
}

func TestLoadConfigAcceptsListenAddresses(t *testing.T) {
	cases := []string{":8443", "127.0.0.1:8443", "[::1]:8443", "0.0.0.0:1", "localhost:65535"}
	for _, listen := range cases {
		t.Run(listen, func(t *testing.T) {
			values := validEnvironment(t)
			values["CONNECTOR_SERVER_LISTEN"] = listen
			config, err := LoadConfig(environment(values))
			if err != nil {
				t.Fatalf("LoadConfig with listen %q: %v", listen, err)
			}
			if config.Listen != listen {
				t.Errorf("Listen = %q, want %q", config.Listen, listen)
			}
		})
	}
}

func TestLoadConfigRejectsHalfConfiguredTLS(t *testing.T) {
	cases := []struct {
		name string
		cert string
		key  string
	}{
		{name: "cert without key", cert: "/etc/tls/cert.pem"},
		{name: "key without cert", key: "/etc/tls/key.pem"},
	}
	for _, testCase := range cases {
		t.Run(testCase.name, func(t *testing.T) {
			values := validEnvironment(t)
			values["CONNECTOR_SERVER_TLS_CERT"] = testCase.cert
			values["CONNECTOR_SERVER_TLS_KEY"] = testCase.key
			if _, err := LoadConfig(environment(values)); err == nil {
				t.Fatal("LoadConfig with half a TLS pair = nil error, want a failure")
			}
		})
	}
}

func TestLoadConfigRejectsRelativeTLSPaths(t *testing.T) {
	cases := []struct {
		name string
		cert string
		key  string
	}{
		{name: "relative cert", cert: "cert.pem", key: "/etc/tls/key.pem"},
		{name: "relative key", cert: "/etc/tls/cert.pem", key: "key.pem"},
	}
	for _, testCase := range cases {
		t.Run(testCase.name, func(t *testing.T) {
			values := validEnvironment(t)
			values["CONNECTOR_SERVER_TLS_CERT"] = testCase.cert
			values["CONNECTOR_SERVER_TLS_KEY"] = testCase.key
			if _, err := LoadConfig(environment(values)); err == nil {
				t.Fatal("LoadConfig with a relative TLS path = nil error, want a failure")
			}
		})
	}
}

func TestLoadConfigAcceptsTLSPair(t *testing.T) {
	values := validEnvironment(t)
	values["CONNECTOR_SERVER_TLS_CERT"] = "/etc/tls/cert.pem"
	values["CONNECTOR_SERVER_TLS_KEY"] = "/etc/tls/key.pem"
	config, err := LoadConfig(environment(values))
	if err != nil {
		t.Fatalf("LoadConfig: %v", err)
	}
	if !config.TLSEnabled() {
		t.Error("TLSEnabled = false, want true")
	}
	if config.TLSCert != "/etc/tls/cert.pem" || config.TLSKey != "/etc/tls/key.pem" {
		t.Errorf("TLS paths = %q, %q", config.TLSCert, config.TLSKey)
	}
}

func TestLoadConfigRejectsBadRequestTimeout(t *testing.T) {
	cases := []string{"0", "-1", "abc", "1.5", "3601"}
	for _, value := range cases {
		t.Run(value, func(t *testing.T) {
			values := validEnvironment(t)
			values["CONNECTOR_SERVER_REQUEST_TIMEOUT_SECONDS"] = value
			if _, err := LoadConfig(environment(values)); err == nil {
				t.Fatalf("LoadConfig with timeout %q = nil error, want a failure", value)
			}
		})
	}
}

func TestLoadConfigAcceptsRequestTimeout(t *testing.T) {
	cases := map[string]time.Duration{
		"1":    time.Second,
		"30":   30 * time.Second,
		"3600": time.Hour,
	}
	for value, want := range cases {
		t.Run(value, func(t *testing.T) {
			values := validEnvironment(t)
			values["CONNECTOR_SERVER_REQUEST_TIMEOUT_SECONDS"] = value
			config, err := LoadConfig(environment(values))
			if err != nil {
				t.Fatalf("LoadConfig: %v", err)
			}
			if config.RequestTimeout != want {
				t.Errorf("RequestTimeout = %s, want %s", config.RequestTimeout, want)
			}
		})
	}
}

// TestLoadConfigRejectsBadReplayWindow checks that a window outside the accepted range
// is a startup failure rather than a clamped value.
//
// A clamped window would silently accept a proof the operator meant to refuse, and a
// window measured in hours is not a freshness check at all.
func TestLoadConfigRejectsBadReplayWindow(t *testing.T) {
	cases := []string{"0", "-1", "abc", "1.5", "601"}
	for _, value := range cases {
		t.Run(value, func(t *testing.T) {
			values := validEnvironment(t)
			values["CONNECTOR_SERVER_REPLAY_WINDOW_SECONDS"] = value
			if _, err := LoadConfig(environment(values)); err == nil {
				t.Fatalf("LoadConfig with replay window %q = nil error, want a failure", value)
			}
		})
	}
}

func TestLoadConfigAcceptsReplayWindow(t *testing.T) {
	cases := map[string]time.Duration{
		"1":   time.Second,
		"60":  60 * time.Second,
		"600": 10 * time.Minute,
	}
	for value, want := range cases {
		t.Run(value, func(t *testing.T) {
			values := validEnvironment(t)
			values["CONNECTOR_SERVER_REPLAY_WINDOW_SECONDS"] = value
			config, err := LoadConfig(environment(values))
			if err != nil {
				t.Fatalf("LoadConfig: %v", err)
			}
			if config.ReplayWindow != want {
				t.Errorf("ReplayWindow = %s, want %s", config.ReplayWindow, want)
			}
		})
	}
}

// TestLoadConfigRejectsBadReplayCapacity checks that a capacity that cannot hold one
// nonce is refused.
func TestLoadConfigRejectsBadReplayCapacity(t *testing.T) {
	cases := []string{"0", "-1", "abc", "1.5"}
	for _, value := range cases {
		t.Run(value, func(t *testing.T) {
			values := validEnvironment(t)
			values["CONNECTOR_SERVER_REPLAY_CAPACITY"] = value
			if _, err := LoadConfig(environment(values)); err == nil {
				t.Fatalf("LoadConfig with replay capacity %q = nil error, want a failure", value)
			}
		})
	}
}

func TestLoadConfigAcceptsReplayCapacity(t *testing.T) {
	values := validEnvironment(t)
	values["CONNECTOR_SERVER_REPLAY_CAPACITY"] = "1024"
	config, err := LoadConfig(environment(values))
	if err != nil {
		t.Fatalf("LoadConfig: %v", err)
	}
	if config.ReplayCapacity != 1024 {
		t.Errorf("ReplayCapacity = %d, want 1024", config.ReplayCapacity)
	}
}

// TestConfigRedactedHidesEverySecret checks that a printed configuration leaks neither
// the tunnel token nor a client secret.
//
// The client credential set is reported by its public key identifiers only, because a
// key identifier is what an operator needs to identify a caller and a secret is what an
// attacker needs to impersonate one.
func TestConfigRedactedHidesEverySecret(t *testing.T) {
	credential, err := security.NewCredentialWithKeyID("operator")
	if err != nil {
		t.Fatalf("NewCredentialWithKeyID() = %v", err)
	}
	values := map[string]string{
		"CONNECTOR_SERVER_TUNNEL_TOKEN":            "tunnel-token-0123456789",
		"CONNECTOR_SERVER_CLIENT_CREDENTIALS_FILE": writeClientCredentialFile(t, credential),
	}
	config, err := LoadConfig(environment(values))
	if err != nil {
		t.Fatalf("LoadConfig: %v", err)
	}
	rendered := config.Redacted()
	for _, secret := range []string{"tunnel-token-0123456789", string(credential.Secret)} {
		if strings.Contains(rendered, secret) {
			t.Errorf("Redacted() contains the secret %q: %s", secret, rendered)
		}
	}
	if !strings.Contains(rendered, "operator") {
		t.Errorf("Redacted() does not report the public key id: %s", rendered)
	}
	if !strings.Contains(rendered, "listen=") {
		t.Errorf("Redacted() does not report the listen address: %s", rendered)
	}
	if config.String() != rendered {
		t.Error("String() and Redacted() disagree")
	}
}
