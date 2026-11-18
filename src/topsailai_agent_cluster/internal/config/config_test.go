package config

import (
	"testing"
	"time"
)

func TestDefaultsAndLoad(t *testing.T) {
	defaults := Defaults("test")
	if defaults.Role != "test" || defaults.LogOutput != "stderr" || defaults.LogMaxSize != 100 {
		t.Fatalf("unexpected defaults: %+v", defaults)
	}
	loaded, err := Load([]string{"-log-output", "file", "-log-path", "/tmp/agent-cluster-test.log"}, "test")
	if err != nil {
		t.Fatalf("Load returned error: %v", err)
	}
	if loaded.LogOutput != "file" || loaded.LogPath == "" {
		t.Fatalf("unexpected loaded config: %+v", loaded)
	}
}

func TestValidateRejectsInvalidConfiguration(t *testing.T) {
	cases := []Config{
		{LogOutput: "syslog"},
		{LogOutput: "file"},
		{LogOutput: "stderr", LogMaxSize: 0},
		{LogOutput: "stderr", LogMaxSize: 1, LogBackups: -1},
	}
	for _, cfg := range cases {
		if err := cfg.Validate(); err == nil {
			t.Errorf("Validate accepted invalid config: %+v", cfg)
		}
	}
}

func TestRoleDefaultsUseOwnedDatabase(t *testing.T) {
	if got := Defaults("agent-cluster-server").DatabasePath; got != ".tmp/server.sqlite" {
		t.Fatalf("server database path = %q", got)
	}
	if got := Defaults("agent-cluster-endpoint").DatabasePath; got != ".tmp/endpoint.sqlite" {
		t.Fatalf("endpoint database path = %q", got)
	}
}

func TestLoadIgnoresMalformedForeignRoleEnvironment(t *testing.T) {
	t.Setenv("AGENT_CLUSTER_ENDPOINT_ADAPTERS", "{")
	if _, err := Load(nil, "agent-cluster-server"); err != nil {
		t.Fatalf("server parsed Endpoint adapter configuration: %v", err)
	}
	t.Setenv("AGENT_CLUSTER_ENDPOINT_ADAPTERS", "")
	t.Setenv("AGENT_CLUSTER_SERVER_ENDPOINT_DIAL_ADDRESSES", "invalid")
	if _, err := Load(nil, "agent-cluster-endpoint"); err != nil {
		t.Fatalf("Endpoint parsed Server dial configuration: %v", err)
	}
}

func TestLoadRejectsMalformedOwnedRoleEnvironment(t *testing.T) {
	t.Setenv("AGENT_CLUSTER_ENDPOINT_ADAPTERS", "{")
	if _, err := Load(nil, "agent-cluster-endpoint"); err == nil {
		t.Fatal("Endpoint accepted malformed adapter configuration")
	}
	t.Setenv("AGENT_CLUSTER_ENDPOINT_ADAPTERS", "")
	t.Setenv("AGENT_CLUSTER_SERVER_ENDPOINT_DIAL_ADDRESSES", "invalid")
	if _, err := Load(nil, "agent-cluster-server"); err == nil {
		t.Fatal("Server accepted malformed dial configuration")
	}
}

func TestServerEnvironmentNamesConfigure(t *testing.T) {
	t.Setenv("AGENT_CLUSTER_SERVER_API_LISTEN_ADDR", "new-api")
	t.Setenv("AGENT_CLUSTER_SERVER_CHANNEL_LISTEN_ADDR", "new-channel")
	t.Setenv("AGENT_CLUSTER_SERVER_AUTH_TOKEN", "new-token")
	t.Setenv("AGENT_CLUSTER_SERVER_ENDPOINT_DIAL_ADDRESSES", "new=wss://new")
	t.Setenv("AGENT_CLUSTER_SERVER_TLS_SHARED_CERTIFICATE", "true")
	t.Setenv("AGENT_CLUSTER_TLS_SERVER_NAME", "new-name")
	cfg, err := Load(nil, "agent-cluster-server")
	if err != nil {
		t.Fatalf("load Server configuration: %v", err)
	}
	if cfg.APIListenAddress != "new-api" || cfg.ChannelListenAddress != "new-channel" || cfg.AuthToken != "new-token" {
		t.Fatalf("Server names did not configure the API: %+v", cfg)
	}
	if cfg.EndpointDialAddresses["new"] != "wss://new" || !cfg.TLSSharedCertificate || cfg.ServerName != "new-name" {
		t.Fatalf("Server names did not configure the channel: %+v", cfg)
	}
}

// TestServerDeprecatedEnvironmentNamesAreIgnored pins the removal of the
// compatibility fallback. A deprecated name must not configure anything, so an
// operator who still exports one gets the documented default instead of a
// silently different behaviour.
func TestServerDeprecatedEnvironmentNamesAreIgnored(t *testing.T) {
	t.Setenv("AGENT_CLUSTER_API_LISTEN_ADDR", "old-api")
	t.Setenv("AGENT_CLUSTER_CHANNEL_LISTEN_ADDR", "old-channel")
	t.Setenv("AGENT_CLUSTER_AUTH_TOKEN", "old-token")
	t.Setenv("AGENT_CLUSTER_ENDPOINT_DIAL_ADDRESSES", "old=wss://old")
	t.Setenv("AGENT_CLUSTER_TLS_SHARED_CERTIFICATE", "true")
	t.Setenv("AGENT_CLUSTER_SERVER_NAME", "old-name")
	cfg, err := Load(nil, "agent-cluster-server")
	if err != nil {
		t.Fatalf("load Server configuration: %v", err)
	}
	defaults := Defaults("agent-cluster-server")
	if cfg.APIListenAddress != defaults.APIListenAddress || cfg.ChannelListenAddress != defaults.ChannelListenAddress || cfg.AuthToken != defaults.AuthToken {
		t.Fatalf("deprecated Server names configured the API: %+v", cfg)
	}
	if len(cfg.EndpointDialAddresses) != 0 || cfg.TLSSharedCertificate || cfg.ServerName != defaults.ServerName {
		t.Fatalf("deprecated Server names configured the channel: %+v", cfg)
	}
}

func TestEndpointEnvironmentNamesConfigure(t *testing.T) {
	newAdapters := `[ {"adapter_id":"new","provider_type":"fixture","command":"/bin/echo","timeout_ms":1} ]`
	t.Setenv("AGENT_CLUSTER_ENDPOINT_CHANNEL_ADDRESS", "wss://new")
	t.Setenv("AGENT_CLUSTER_ENDPOINT_INSTANCE_ID", "new-instance")
	t.Setenv("AGENT_CLUSTER_ENDPOINT_ADAPTERS", newAdapters)
	t.Setenv("AGENT_CLUSTER_ENDPOINT_COMMAND_ALLOWLIST_FILE", "/new/allowlist")
	cfg, err := Load(nil, "agent-cluster-endpoint")
	if err != nil {
		t.Fatalf("load Endpoint configuration: %v", err)
	}
	if cfg.ChannelAddress != "wss://new" || cfg.InstanceID != "new-instance" || len(cfg.Adapters) != 1 || cfg.Adapters[0].AdapterID != "new" {
		t.Fatalf("Endpoint names did not configure the channel: %+v", cfg)
	}
	if cfg.CommandAllowlistFile != "/new/allowlist" {
		t.Fatalf("Endpoint names did not configure the files: %+v", cfg)
	}
}

// TestEndpointDeprecatedEnvironmentNamesAreIgnored pins the removal of the
// compatibility fallback for the Endpoint role.
func TestEndpointDeprecatedEnvironmentNamesAreIgnored(t *testing.T) {
	t.Setenv("AGENT_CLUSTER_CHANNEL_ADDRESS", "wss://old")
	t.Setenv("AGENT_CLUSTER_INSTANCE_ID", "old-instance")
	t.Setenv("AGENT_CLUSTER_ADAPTERS", `[ {"adapter_id":"old","provider_type":"fixture","command":"/bin/echo","timeout_ms":1} ]`)
	t.Setenv("AGENT_CLUSTER_COMMAND_ALLOWLIST_FILE", "/old/allowlist")
	cfg, err := Load(nil, "agent-cluster-endpoint")
	if err != nil {
		t.Fatalf("load Endpoint configuration: %v", err)
	}
	defaults := Defaults("agent-cluster-endpoint")
	if cfg.ChannelAddress != defaults.ChannelAddress || cfg.InstanceID != defaults.InstanceID || len(cfg.Adapters) != 0 {
		t.Fatalf("deprecated Endpoint names configured the channel: %+v", cfg)
	}
	if cfg.CommandAllowlistFile != defaults.CommandAllowlistFile {
		t.Fatalf("deprecated Endpoint names configured the files: %+v", cfg)
	}
}

func TestServerEndpointExpiryConfiguration(t *testing.T) {
	if got := Defaults("agent-cluster-server").EndpointExpiry; got != 24*time.Hour {
		t.Fatalf("default Endpoint expiry = %s", got)
	}
	t.Setenv("AGENT_CLUSTER_SERVER_ENDPOINT_EXPIRY", "7m30s")
	cfg, err := Load([]string{"--endpoint-expiry", "9m"}, "agent-cluster-server")
	if err != nil {
		t.Fatal(err)
	}
	if cfg.EndpointExpiry != 9*time.Minute {
		t.Fatalf("flag did not override environment: %s", cfg.EndpointExpiry)
	}
}

func TestServerEndpointExpiryRejectsInvalidValues(t *testing.T) {
	for _, value := range []string{"invalid", "0s", "-1m"} {
		t.Run(value, func(t *testing.T) {
			t.Setenv("AGENT_CLUSTER_SERVER_ENDPOINT_EXPIRY", value)
			if _, err := Load(nil, "agent-cluster-server"); err == nil {
				t.Fatalf("accepted Endpoint expiry %q", value)
			}
		})
	}
}

func TestEndpointIgnoresServerEndpointExpiry(t *testing.T) {
	t.Setenv("AGENT_CLUSTER_SERVER_ENDPOINT_EXPIRY", "invalid")
	if _, err := Load(nil, "agent-cluster-endpoint"); err != nil {
		t.Fatalf("Endpoint parsed Server expiry: %v", err)
	}
}

func TestServerEndpointDegradedRetentionConfiguration(t *testing.T) {
	if got := Defaults("agent-cluster-server").EndpointDegradedRetention; got != 720*time.Hour {
		t.Fatalf("default degraded retention = %s, want 720h", got)
	}
	t.Setenv("AGENT_CLUSTER_SERVER_ENDPOINT_DEGRADED_RETENTION", "7m30s")
	cfg, err := Load([]string{"--endpoint-degraded-retention", "9m"}, "agent-cluster-server")
	if err != nil {
		t.Fatal(err)
	}
	if cfg.EndpointDegradedRetention != 9*time.Minute {
		t.Fatalf("flag did not override environment: %s", cfg.EndpointDegradedRetention)
	}
}

func TestServerEndpointDegradedRetentionRejectsInvalidValues(t *testing.T) {
	for _, value := range []string{"invalid", "0s", "-1m"} {
		t.Run(value, func(t *testing.T) {
			t.Setenv("AGENT_CLUSTER_SERVER_ENDPOINT_DEGRADED_RETENTION", value)
			if _, err := Load(nil, "agent-cluster-server"); err == nil {
				t.Fatalf("accepted degraded retention %q", value)
			}
		})
	}
}

func TestEndpointIgnoresServerEndpointDegradedRetention(t *testing.T) {
	t.Setenv("AGENT_CLUSTER_SERVER_ENDPOINT_DEGRADED_RETENTION", "invalid")
	if _, err := Load(nil, "agent-cluster-endpoint"); err != nil {
		t.Fatalf("Endpoint parsed Server degraded retention: %v", err)
	}
}

func TestEndpointHeartbeatLivenessConfiguration(t *testing.T) {
	defaults := Defaults("agent-cluster-endpoint")
	if defaults.HeartbeatAckTimeout != 3*time.Second {
		t.Fatalf("default heartbeat acknowledgement timeout = %s, want 3s", defaults.HeartbeatAckTimeout)
	}
	if defaults.UnhealthyWindow != 30*time.Second {
		t.Fatalf("default unhealthy window = %s, want 30s", defaults.UnhealthyWindow)
	}
	t.Setenv("AGENT_CLUSTER_ENDPOINT_HEARTBEAT_ACK_TIMEOUT", "7s")
	t.Setenv("AGENT_CLUSTER_ENDPOINT_UNHEALTHY_WINDOW", "45s")
	cfg, err := Load([]string{"--heartbeat-ack-timeout", "2s", "--unhealthy-window", "90s"}, "agent-cluster-endpoint")
	if err != nil {
		t.Fatal(err)
	}
	if cfg.HeartbeatAckTimeout != 2*time.Second {
		t.Fatalf("flag did not override the acknowledgement timeout: %s", cfg.HeartbeatAckTimeout)
	}
	if cfg.UnhealthyWindow != 90*time.Second {
		t.Fatalf("flag did not override the unhealthy window: %s", cfg.UnhealthyWindow)
	}
}

func TestEndpointHeartbeatLivenessRejectsNonPositiveValues(t *testing.T) {
	// A non-positive bound would disable the Endpoint's only liveness judgement,
	// and a disabled judgement looks exactly like a healthy Server. Each case is
	// rejected at load time so the failure is visible at startup.
	cases := []struct {
		name     string
		variable string
		value    string
	}{
		{"ack timeout zero", "AGENT_CLUSTER_ENDPOINT_HEARTBEAT_ACK_TIMEOUT", "0s"},
		{"ack timeout negative", "AGENT_CLUSTER_ENDPOINT_HEARTBEAT_ACK_TIMEOUT", "-1s"},
		{"ack timeout malformed", "AGENT_CLUSTER_ENDPOINT_HEARTBEAT_ACK_TIMEOUT", "invalid"},
		{"unhealthy window zero", "AGENT_CLUSTER_ENDPOINT_UNHEALTHY_WINDOW", "0s"},
		{"unhealthy window negative", "AGENT_CLUSTER_ENDPOINT_UNHEALTHY_WINDOW", "-1s"},
		{"unhealthy window malformed", "AGENT_CLUSTER_ENDPOINT_UNHEALTHY_WINDOW", "invalid"},
	}
	for _, testCase := range cases {
		t.Run(testCase.name, func(t *testing.T) {
			t.Setenv(testCase.variable, testCase.value)
			if _, err := Load(nil, "agent-cluster-endpoint"); err == nil {
				t.Fatalf("accepted %s=%q", testCase.variable, testCase.value)
			}
		})
	}
}

func TestValidateRejectsNonPositiveHeartbeatBounds(t *testing.T) {
	// Validate is the last gate before service initialization, so it must reject
	// the same values Load rejects. A caller that builds a Config directly would
	// otherwise start an Endpoint with the liveness rule silently disabled.
	base := Defaults("agent-cluster-endpoint")
	zeroAck := base
	zeroAck.HeartbeatAckTimeout = 0
	if err := zeroAck.Validate(); err == nil {
		t.Fatal("Validate accepted a zero acknowledgement timeout")
	}
	zeroWindow := base
	zeroWindow.UnhealthyWindow = 0
	if err := zeroWindow.Validate(); err == nil {
		t.Fatal("Validate accepted a zero unhealthy window")
	}
}

func TestEndpointDetailBoundConfiguration(t *testing.T) {
	// Zero is the documented way to ask for the protocol default, so the default
	// configuration must carry zero rather than a copied constant. Copying the
	// constant here would make the default a second source of truth that could
	// drift from the protocol value the adapter actually resolves.
	defaults := Defaults("agent-cluster-endpoint")
	if defaults.DetailMaxBytes != 0 {
		t.Fatalf("default detail bound = %d, want 0 so the protocol default applies", defaults.DetailMaxBytes)
	}
	t.Setenv("AGENT_CLUSTER_ENDPOINT_DETAIL_MAX_BYTES", "2097152")
	cfg, err := Load(nil, "agent-cluster-endpoint")
	if err != nil {
		t.Fatal(err)
	}
	if cfg.DetailMaxBytes != 2097152 {
		t.Fatalf("environment did not configure the detail bound: %d", cfg.DetailMaxBytes)
	}
	// A flag must win over the environment, because the flag is the more specific
	// declaration and the precedence rule is shared with every other setting.
	cfg, err = Load([]string{"--detail-max-bytes", "1048576"}, "agent-cluster-endpoint")
	if err != nil {
		t.Fatal(err)
	}
	if cfg.DetailMaxBytes != 1048576 {
		t.Fatalf("flag did not override the detail bound: %d", cfg.DetailMaxBytes)
	}
}

func TestEndpointDetailBoundRejectsInvalidValues(t *testing.T) {
	// A negative bound is a configuration mistake rather than a request for the
	// default, and a bound above the ceiling could never be carried by the
	// transport. Both are rejected at load time so the operator sees the mistake
	// at startup instead of as a provider fault on the first read.
	cases := []struct {
		name  string
		value string
	}{
		{"negative", "-1"},
		{"above ceiling", "2097153"},
		{"malformed", "invalid"},
	}
	for _, testCase := range cases {
		t.Run(testCase.name, func(t *testing.T) {
			t.Setenv("AGENT_CLUSTER_ENDPOINT_DETAIL_MAX_BYTES", testCase.value)
			if _, err := Load(nil, "agent-cluster-endpoint"); err == nil {
				t.Fatalf("accepted AGENT_CLUSTER_ENDPOINT_DETAIL_MAX_BYTES=%q", testCase.value)
			}
		})
	}
}

func TestValidateRejectsInvalidDetailBound(t *testing.T) {
	// Validate is the last gate before service initialization, so a caller that
	// builds a Config directly must be refused for the same values Load refuses.
	base := Defaults("agent-cluster-endpoint")
	negative := base
	negative.DetailMaxBytes = -1
	if err := negative.Validate(); err == nil {
		t.Fatal("Validate accepted a negative detail bound")
	}
	aboveCeiling := base
	aboveCeiling.DetailMaxBytes = 2097153
	if err := aboveCeiling.Validate(); err == nil {
		t.Fatal("Validate accepted a detail bound above the contract ceiling")
	}
	atCeiling := base
	atCeiling.DetailMaxBytes = 2097152
	if err := atCeiling.Validate(); err != nil {
		t.Fatalf("Validate rejected the ceiling itself: %v", err)
	}
}
