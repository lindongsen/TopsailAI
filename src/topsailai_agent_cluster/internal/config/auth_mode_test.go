package config

import (
	"strings"
	"testing"
	"time"

	"topsailai_agent_cluster/internal/security"
)

// TestDefaultsSelectHMAC proves the default mode is HMAC rather than bearer.
// The default is the whole point of the change: a deployment that configures
// nothing must still avoid transmitting the secret.
func TestDefaultsSelectHMAC(t *testing.T) {
	for _, role := range []string{"agent-cluster-server", "agent-cluster-endpoint", "test"} {
		cfg := Defaults(role)
		if cfg.AuthMode != string(security.ModeHMAC) {
			t.Fatalf("role %q default auth mode = %q, want %q", role, cfg.AuthMode, security.ModeHMAC)
		}
		if cfg.SignatureWindow != security.DefaultSignatureWindow {
			t.Fatalf("role %q default signature window = %s, want %s", role, cfg.SignatureWindow, security.DefaultSignatureWindow)
		}
	}
}

// TestServerAuthModeEnvironment proves the Server reads its own mode and window
// from the Server-prefixed names.
func TestServerAuthModeEnvironment(t *testing.T) {
	t.Setenv("AGENT_CLUSTER_SERVER_AUTH_MODE", "bearer")
	t.Setenv("AGENT_CLUSTER_SERVER_SIGNATURE_WINDOW", "90s")
	cfg, err := Load(nil, "agent-cluster-server")
	if err != nil {
		t.Fatalf("Load returned error: %v", err)
	}
	if cfg.AuthMode != string(security.ModeBearer) {
		t.Fatalf("auth mode = %q, want %q", cfg.AuthMode, security.ModeBearer)
	}
	if cfg.SignatureWindow != 90*time.Second {
		t.Fatalf("signature window = %s, want 90s", cfg.SignatureWindow)
	}
}

// TestEndpointAuthModeEnvironment proves the Endpoint reads its own mode and
// window from the Endpoint-prefixed names, because it is the component that
// verifies the endpoint-token.
func TestEndpointAuthModeEnvironment(t *testing.T) {
	t.Setenv("AGENT_CLUSTER_ENDPOINT_AUTH_MODE", "bearer")
	t.Setenv("AGENT_CLUSTER_ENDPOINT_SIGNATURE_WINDOW", "45s")
	cfg, err := Load(nil, "agent-cluster-endpoint")
	if err != nil {
		t.Fatalf("Load returned error: %v", err)
	}
	if cfg.AuthMode != string(security.ModeBearer) {
		t.Fatalf("auth mode = %q, want %q", cfg.AuthMode, security.ModeBearer)
	}
	if cfg.SignatureWindow != 45*time.Second {
		t.Fatalf("signature window = %s, want 45s", cfg.SignatureWindow)
	}
}

// TestAuthModeFlagOverridesEnvironment proves the flag wins, because a flag is
// the more specific instruction and the environment is only a default.
func TestAuthModeFlagOverridesEnvironment(t *testing.T) {
	t.Setenv("AGENT_CLUSTER_SERVER_AUTH_MODE", "bearer")
	cfg, err := Load([]string{"-auth-mode", "hmac"}, "agent-cluster-server")
	if err != nil {
		t.Fatalf("Load returned error: %v", err)
	}
	if cfg.AuthMode != string(security.ModeHMAC) {
		t.Fatalf("auth mode = %q, want %q", cfg.AuthMode, security.ModeHMAC)
	}
}

// TestLoadRejectsMalformedAuthMode proves a typo fails at startup instead of
// silently selecting a mode. A verifier that runs a different mode than the
// operator configured refuses every request, and that refusal looks like a wrong
// credential rather than a configuration mistake.
func TestLoadRejectsMalformedAuthMode(t *testing.T) {
	cases := []struct {
		name  string
		env   string
		value string
	}{
		{name: "server unknown mode", env: "AGENT_CLUSTER_SERVER_AUTH_MODE", value: "hmac-sha1"},
		{name: "endpoint unknown mode", env: "AGENT_CLUSTER_ENDPOINT_AUTH_MODE", value: "basic"},
	}
	for _, testCase := range cases {
		t.Run(testCase.name, func(t *testing.T) {
			t.Setenv(testCase.env, testCase.value)
			role := "agent-cluster-server"
			if strings.HasPrefix(testCase.env, "AGENT_CLUSTER_ENDPOINT_") {
				role = "agent-cluster-endpoint"
			}
			if _, err := Load(nil, role); err == nil {
				t.Fatalf("Load accepted %s=%q", testCase.env, testCase.value)
			}
		})
	}
}

// TestLoadRejectsMalformedSignatureWindow proves a non-positive or oversized
// window fails at startup. A non-positive window rejects every signed request,
// and an oversized one makes a captured signature replayable for that period.
func TestLoadRejectsMalformedSignatureWindow(t *testing.T) {
	cases := []struct {
		name  string
		env   string
		value string
	}{
		{name: "server zero", env: "AGENT_CLUSTER_SERVER_SIGNATURE_WINDOW", value: "0s"},
		{name: "server negative", env: "AGENT_CLUSTER_SERVER_SIGNATURE_WINDOW", value: "-30s"},
		{name: "server oversized", env: "AGENT_CLUSTER_SERVER_SIGNATURE_WINDOW", value: "1h"},
		{name: "server unparsable", env: "AGENT_CLUSTER_SERVER_SIGNATURE_WINDOW", value: "sixty"},
		{name: "endpoint zero", env: "AGENT_CLUSTER_ENDPOINT_SIGNATURE_WINDOW", value: "0s"},
		{name: "endpoint oversized", env: "AGENT_CLUSTER_ENDPOINT_SIGNATURE_WINDOW", value: "24h"},
	}
	for _, testCase := range cases {
		t.Run(testCase.name, func(t *testing.T) {
			t.Setenv(testCase.env, testCase.value)
			role := "agent-cluster-server"
			if strings.HasPrefix(testCase.env, "AGENT_CLUSTER_ENDPOINT_") {
				role = "agent-cluster-endpoint"
			}
			if _, err := Load(nil, role); err == nil {
				t.Fatalf("Load accepted %s=%q", testCase.env, testCase.value)
			}
		})
	}
}

// TestValidateRejectsInvalidAuthSettings proves Validate catches a bad mode and
// window even when they were set programmatically rather than through Load.
func TestValidateRejectsInvalidAuthSettings(t *testing.T) {
	base := Defaults("agent-cluster-server")
	cases := []struct {
		name   string
		mutate func(*Config)
	}{
		{name: "unknown mode", mutate: func(c *Config) { c.AuthMode = "digest" }},
		{name: "zero window", mutate: func(c *Config) { c.SignatureWindow = 0 }},
		{name: "negative window", mutate: func(c *Config) { c.SignatureWindow = -time.Second }},
		{name: "oversized window", mutate: func(c *Config) { c.SignatureWindow = security.MaxSignatureWindow + time.Second }},
	}
	for _, testCase := range cases {
		t.Run(testCase.name, func(t *testing.T) {
			cfg := base
			testCase.mutate(&cfg)
			if err := cfg.Validate(); err == nil {
				t.Fatalf("Validate accepted invalid auth settings: mode=%q window=%s", cfg.AuthMode, cfg.SignatureWindow)
			}
		})
	}
}

// TestValidateAcceptsBoundaryWindow proves the documented maximum is inclusive,
// so an operator who configures exactly the limit is not refused.
func TestValidateAcceptsBoundaryWindow(t *testing.T) {
	cfg := Defaults("agent-cluster-server")
	cfg.SignatureWindow = security.MaxSignatureWindow
	if err := cfg.Validate(); err != nil {
		t.Fatalf("Validate rejected the documented maximum window: %v", err)
	}
}

// TestEndpointIgnoresServerAuthEnvironment proves the role split holds: an
// Endpoint must not be configured by a Server-prefixed name, because the two
// components verify different credentials.
func TestEndpointIgnoresServerAuthEnvironment(t *testing.T) {
	t.Setenv("AGENT_CLUSTER_SERVER_AUTH_MODE", "bearer")
	t.Setenv("AGENT_CLUSTER_SERVER_SIGNATURE_WINDOW", "90s")
	cfg, err := Load(nil, "agent-cluster-endpoint")
	if err != nil {
		t.Fatalf("Load returned error: %v", err)
	}
	if cfg.AuthMode != string(security.ModeHMAC) {
		t.Fatalf("endpoint auth mode = %q, want the default %q", cfg.AuthMode, security.ModeHMAC)
	}
	if cfg.SignatureWindow != security.DefaultSignatureWindow {
		t.Fatalf("endpoint signature window = %s, want the default %s", cfg.SignatureWindow, security.DefaultSignatureWindow)
	}
}
