package server

import (
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

// validEnvironment is the smallest environment that starts a Server.
func validEnvironment() map[string]string {
	return map[string]string{
		"CONNECTOR_SERVER_TUNNEL_TOKEN": "tunnel-token-0123456789",
		"CONNECTOR_SERVER_CLIENT_TOKEN": "client-token-0123456789",
	}
}

func TestLoadConfigAcceptsMinimalEnvironment(t *testing.T) {
	config, err := LoadConfig(environment(validEnvironment()))
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
	if config.ClientToken != security.Secret("client-token-0123456789") {
		t.Error("ClientToken was not carried through")
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
		{name: "client token missing", remove: "CONNECTOR_SERVER_CLIENT_TOKEN"},
	}
	for _, testCase := range cases {
		t.Run(testCase.name, func(t *testing.T) {
			values := validEnvironment()
			delete(values, testCase.remove)
			if _, err := LoadConfig(environment(values)); err == nil {
				t.Fatalf("LoadConfig with %s removed = nil error, want a failure", testCase.remove)
			}
		})
	}
}

func TestLoadConfigRejectsShortSecret(t *testing.T) {
	values := validEnvironment()
	values["CONNECTOR_SERVER_CLIENT_TOKEN"] = "short"
	_, err := LoadConfig(environment(values))
	if err == nil {
		t.Fatal("LoadConfig with a short secret = nil error, want a failure")
	}
	if !strings.Contains(err.Error(), "CONNECTOR_SERVER_CLIENT_TOKEN") {
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
			values := validEnvironment()
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
			values := validEnvironment()
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
			values := validEnvironment()
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
			values := validEnvironment()
			values["CONNECTOR_SERVER_TLS_CERT"] = testCase.cert
			values["CONNECTOR_SERVER_TLS_KEY"] = testCase.key
			if _, err := LoadConfig(environment(values)); err == nil {
				t.Fatal("LoadConfig with a relative TLS path = nil error, want a failure")
			}
		})
	}
}

func TestLoadConfigAcceptsTLSPair(t *testing.T) {
	values := validEnvironment()
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
			values := validEnvironment()
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
			values := validEnvironment()
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

func TestConfigRedactedHidesBothSecrets(t *testing.T) {
	values := validEnvironment()
	config, err := LoadConfig(environment(values))
	if err != nil {
		t.Fatalf("LoadConfig: %v", err)
	}
	rendered := config.Redacted()
	for _, secret := range []string{"tunnel-token-0123456789", "client-token-0123456789"} {
		if strings.Contains(rendered, secret) {
			t.Errorf("Redacted() contains the secret %q: %s", secret, rendered)
		}
	}
	if !strings.Contains(rendered, "listen=") {
		t.Errorf("Redacted() does not report the listen address: %s", rendered)
	}
	if config.String() != rendered {
		t.Error("String() and Redacted() disagree")
	}
}
