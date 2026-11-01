package config

import "testing"

func TestValidateAndParseAdaptersMoreFailures(t *testing.T) {
	for _, value := range []string{`[{"adapter_id":"","provider_type":"x","command":"/bin/echo","timeout_ms":1}]`, `[{"adapter_id":"a","provider_type":"","command":"/bin/echo","timeout_ms":1}]`, `[{"adapter_id":"a","provider_type":"x","command":"/bin/echo","timeout_ms":0}]`} {
		if _, err := ParseAdapters(value); err == nil {
			t.Errorf("accepted %s", value)
		}
	}
	if err := (Config{LogOutput: "file", LogPath: "", LogMaxSize: 1, LogBackups: 1, LogMaxAge: 1}).Validate(); err == nil {
		t.Fatal("file output without path accepted")
	}
}
