package config

import "testing"

// TestParseDialAddresses verifies the Server dial map is parsed strictly, so a
// malformed entry fails at startup instead of silently dialing nothing.
func TestParseDialAddresses(t *testing.T) {
	parsed, err := ParseDialAddresses("endpoint-1=wss://10.0.0.1:8443/channel, endpoint-2=wss://10.0.0.2:8443/channel")
	if err != nil {
		t.Fatalf("parse dial addresses: %v", err)
	}
	if len(parsed) != 2 {
		t.Fatalf("parsed %d entries, want 2", len(parsed))
	}
	if parsed["endpoint-1"] != "wss://10.0.0.1:8443/channel" {
		t.Fatalf("endpoint-1 address = %q", parsed["endpoint-1"])
	}
	if parsed["endpoint-2"] != "wss://10.0.0.2:8443/channel" {
		t.Fatalf("endpoint-2 address = %q", parsed["endpoint-2"])
	}
}

// TestParseDialAddressesRejectsInvalidInput verifies malformed and duplicated
// entries are rejected rather than partially applied.
func TestParseDialAddressesRejectsInvalidInput(t *testing.T) {
	cases := []string{
		"endpoint-1",
		"=wss://10.0.0.1:8443/channel",
		"endpoint-1=",
		"endpoint-1=wss://a/channel,endpoint-1=wss://b/channel",
	}
	for _, value := range cases {
		if _, err := ParseDialAddresses(value); err == nil {
			t.Fatalf("ParseDialAddresses(%q) accepted invalid input", value)
		}
	}
}

// TestValidateChannelDirection verifies only the implemented directions are
// accepted, so a deployment cannot select a direction that does nothing.
func TestValidateChannelDirection(t *testing.T) {
	for _, direction := range []string{DirectionEndpointInitiated, DirectionServerInitiated} {
		cfg := Defaults("test")
		cfg.ChannelDirection = direction
		if err := cfg.Validate(); err != nil {
			t.Fatalf("direction %q rejected: %v", direction, err)
		}
	}
	cfg := Defaults("test")
	cfg.ChannelDirection = "auto"
	if err := cfg.Validate(); err == nil {
		t.Fatal("unimplemented direction \"auto\" was accepted")
	}
	cfg = Defaults("test")
	cfg.ChannelDirection = "sideways"
	if err := cfg.Validate(); err == nil {
		t.Fatal("unknown direction was accepted")
	}
}
