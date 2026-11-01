package config

import "testing"

func TestParseAdaptersValidatesSchema(t *testing.T) {
	valid := `[ {"adapter_id":"fixture-main","provider_type":"fixture","command":"/bin/echo","args":["ok"],"timeout_ms":5000} ]`
	adapters, err := ParseAdapters(valid)
	if err != nil || len(adapters) != 1 || adapters[0].Command != "/bin/echo" {
		t.Fatalf("valid adapter rejected: %#v %v", adapters, err)
	}
	cases := []string{
		`{`, `[]`, `[{"adapter_id":"a","provider_type":"fixture","command":"relative","timeout_ms":1}]`,
		`[{"adapter_id":"a","provider_type":"fixture","command":"/bin/echo","timeout_ms":1},{"adapter_id":"a","provider_type":"fixture","command":"/bin/echo","timeout_ms":1}]`,
	}
	for _, value := range cases {
		if _, err := ParseAdapters(value); err == nil {
			t.Errorf("accepted invalid adapter configuration: %s", value)
		}
	}
}
