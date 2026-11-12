package config

import "testing"

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
	t.Setenv("AGENT_CLUSTER_ADAPTERS", "{")
	if _, err := Load(nil, "agent-cluster-server"); err != nil {
		t.Fatalf("server parsed Endpoint adapter configuration: %v", err)
	}
	t.Setenv("AGENT_CLUSTER_ADAPTERS", "")
	t.Setenv("AGENT_CLUSTER_ENDPOINT_DIAL_ADDRESSES", "invalid")
	if _, err := Load(nil, "agent-cluster-endpoint"); err != nil {
		t.Fatalf("Endpoint parsed Server dial configuration: %v", err)
	}
}

func TestLoadRejectsMalformedOwnedRoleEnvironment(t *testing.T) {
	t.Setenv("AGENT_CLUSTER_ADAPTERS", "{")
	if _, err := Load(nil, "agent-cluster-endpoint"); err == nil {
		t.Fatal("Endpoint accepted malformed adapter configuration")
	}
	t.Setenv("AGENT_CLUSTER_ADAPTERS", "")
	t.Setenv("AGENT_CLUSTER_ENDPOINT_DIAL_ADDRESSES", "invalid")
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
