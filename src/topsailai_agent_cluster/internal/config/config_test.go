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

func TestEnvironmentValuePrefersPrimaryName(t *testing.T) {
	t.Setenv("AGENT_CLUSTER_NEW_NAME", "primary")
	t.Setenv("AGENT_CLUSTER_OLD_NAME", "deprecated")
	if got := EnvironmentValue("AGENT_CLUSTER_NEW_NAME", "AGENT_CLUSTER_OLD_NAME"); got != "primary" {
		t.Fatalf("environment value = %q", got)
	}
}

func TestServerEnvironmentNamesAndPrecedence(t *testing.T) {
	t.Setenv("AGENT_CLUSTER_API_LISTEN_ADDR", "old-api")
	t.Setenv("AGENT_CLUSTER_SERVER_API_LISTEN_ADDR", "new-api")
	t.Setenv("AGENT_CLUSTER_CHANNEL_LISTEN_ADDR", "old-channel")
	t.Setenv("AGENT_CLUSTER_SERVER_CHANNEL_LISTEN_ADDR", "new-channel")
	t.Setenv("AGENT_CLUSTER_AUTH_TOKEN", "old-token")
	t.Setenv("AGENT_CLUSTER_SERVER_AUTH_TOKEN", "new-token")
	t.Setenv("AGENT_CLUSTER_ENDPOINT_DIAL_ADDRESSES", "old=wss://old")
	t.Setenv("AGENT_CLUSTER_SERVER_ENDPOINT_DIAL_ADDRESSES", "new=wss://new")
	t.Setenv("AGENT_CLUSTER_TLS_SHARED_CERTIFICATE", "false")
	t.Setenv("AGENT_CLUSTER_SERVER_TLS_SHARED_CERTIFICATE", "true")
	t.Setenv("AGENT_CLUSTER_SERVER_NAME", "old-name")
	t.Setenv("AGENT_CLUSTER_TLS_SERVER_NAME", "new-name")
	cfg, err := Load(nil, "agent-cluster-server")
	if err != nil {
		t.Fatalf("load Server configuration: %v", err)
	}
	if cfg.APIListenAddress != "new-api" || cfg.ChannelListenAddress != "new-channel" || cfg.AuthToken != "new-token" {
		t.Fatalf("Server primary names did not win: %+v", cfg)
	}
	if cfg.EndpointDialAddresses["new"] != "wss://new" || !cfg.TLSSharedCertificate || cfg.ServerName != "new-name" {
		t.Fatalf("Server primary names did not configure channel: %+v", cfg)
	}
}

func TestServerDeprecatedEnvironmentNamesRemainFallbacks(t *testing.T) {
	t.Setenv("AGENT_CLUSTER_API_LISTEN_ADDR", "old-api")
	t.Setenv("AGENT_CLUSTER_CHANNEL_LISTEN_ADDR", "old-channel")
	t.Setenv("AGENT_CLUSTER_AUTH_TOKEN", "old-token")
	t.Setenv("AGENT_CLUSTER_ENDPOINT_DIAL_ADDRESSES", "old=wss://old")
	t.Setenv("AGENT_CLUSTER_TLS_SHARED_CERTIFICATE", "true")
	t.Setenv("AGENT_CLUSTER_SERVER_NAME", "old-name")
	cfg, err := Load(nil, "agent-cluster-server")
	if err != nil {
		t.Fatalf("load deprecated Server configuration: %v", err)
	}
	if cfg.APIListenAddress != "old-api" || cfg.ChannelListenAddress != "old-channel" || cfg.AuthToken != "old-token" {
		t.Fatalf("deprecated Server names were not loaded: %+v", cfg)
	}
	if cfg.EndpointDialAddresses["old"] != "wss://old" || !cfg.TLSSharedCertificate || cfg.ServerName != "old-name" {
		t.Fatalf("deprecated Server channel names were not loaded: %+v", cfg)
	}
}

func TestEndpointEnvironmentNamesAndPrecedence(t *testing.T) {
	oldAdapters := `[ {"adapter_id":"old","provider_type":"fixture","command":"/bin/echo","timeout_ms":1} ]`
	newAdapters := `[ {"adapter_id":"new","provider_type":"fixture","command":"/bin/echo","timeout_ms":1} ]`
	t.Setenv("AGENT_CLUSTER_CHANNEL_ADDRESS", "wss://old")
	t.Setenv("AGENT_CLUSTER_ENDPOINT_CHANNEL_ADDRESS", "wss://new")
	t.Setenv("AGENT_CLUSTER_INSTANCE_ID", "old-instance")
	t.Setenv("AGENT_CLUSTER_ENDPOINT_INSTANCE_ID", "new-instance")
	t.Setenv("AGENT_CLUSTER_ADAPTERS", oldAdapters)
	t.Setenv("AGENT_CLUSTER_ENDPOINT_ADAPTERS", newAdapters)
	t.Setenv("AGENT_CLUSTER_COMMAND_ALLOWLIST_FILE", "/old/allowlist")
	t.Setenv("AGENT_CLUSTER_ENDPOINT_COMMAND_ALLOWLIST_FILE", "/new/allowlist")
	t.Setenv("AGENT_CLUSTER_CONTROL_ACTION_FILE", "/old/catalog")
	t.Setenv("AGENT_CLUSTER_ENDPOINT_CONTROL_ACTION_FILE", "/new/catalog")
	cfg, err := Load(nil, "agent-cluster-endpoint")
	if err != nil {
		t.Fatalf("load Endpoint configuration: %v", err)
	}
	if cfg.ChannelAddress != "wss://new" || cfg.InstanceID != "new-instance" || len(cfg.Adapters) != 1 || cfg.Adapters[0].AdapterID != "new" {
		t.Fatalf("Endpoint primary names did not win: %+v", cfg)
	}
	if cfg.CommandAllowlistFile != "/new/allowlist" || cfg.ControlActionFile != "/new/catalog" {
		t.Fatalf("Endpoint file names did not win: %+v", cfg)
	}
}

func TestEndpointDeprecatedEnvironmentNamesRemainFallbacks(t *testing.T) {
	t.Setenv("AGENT_CLUSTER_CHANNEL_ADDRESS", "wss://old")
	t.Setenv("AGENT_CLUSTER_INSTANCE_ID", "old-instance")
	t.Setenv("AGENT_CLUSTER_ADAPTERS", `[ {"adapter_id":"old","provider_type":"fixture","command":"/bin/echo","timeout_ms":1} ]`)
	t.Setenv("AGENT_CLUSTER_COMMAND_ALLOWLIST_FILE", "/old/allowlist")
	t.Setenv("AGENT_CLUSTER_CONTROL_ACTION_FILE", "/old/catalog")
	cfg, err := Load(nil, "agent-cluster-endpoint")
	if err != nil {
		t.Fatalf("load deprecated Endpoint configuration: %v", err)
	}
	if cfg.ChannelAddress != "wss://old" || cfg.InstanceID != "old-instance" || len(cfg.Adapters) != 1 || cfg.Adapters[0].AdapterID != "old" {
		t.Fatalf("deprecated Endpoint names were not loaded: %+v", cfg)
	}
	if cfg.CommandAllowlistFile != "/old/allowlist" || cfg.ControlActionFile != "/old/catalog" {
		t.Fatalf("deprecated Endpoint file names were not loaded: %+v", cfg)
	}
}

func TestServerEndpointExpiryConfiguration(t *testing.T) {
	if got := Defaults("agent-cluster-server").EndpointExpiry; got != 5*time.Minute {
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
