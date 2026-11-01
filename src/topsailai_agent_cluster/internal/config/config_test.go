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
