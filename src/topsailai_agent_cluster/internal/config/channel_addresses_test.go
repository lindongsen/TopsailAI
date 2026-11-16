package config

import "testing"

// TestChannelAddressesFromFlagAndEnvironment proves both spellings reach the
// configuration. A registered flag that is never parsed would look correct in
// the source and silently do nothing at runtime.
func TestChannelAddressesFromFlagAndEnvironment(t *testing.T) {
	t.Setenv("AGENT_CLUSTER_ENDPOINT_CHANNEL_ADDRESSES", "wss://a:1,wss://b:2")
	cfg, err := Load([]string{"--endpoint-id", "e1"}, "endpoint")
	if err != nil {
		t.Fatalf("load: %v", err)
	}
	if len(cfg.ChannelAddresses) != 2 || cfg.ChannelAddresses[0] != "wss://a:1" || cfg.ChannelAddresses[1] != "wss://b:2" {
		t.Fatalf("environment list = %v, want [wss://a:1 wss://b:2]", cfg.ChannelAddresses)
	}

	cfg, err = Load([]string{"--endpoint-id", "e1", "--channel-addresses", "wss://c:3,wss://d:4"}, "endpoint")
	if err != nil {
		t.Fatalf("load with flag: %v", err)
	}
	if len(cfg.ChannelAddresses) != 2 || cfg.ChannelAddresses[0] != "wss://c:3" || cfg.ChannelAddresses[1] != "wss://d:4" {
		t.Fatalf("flag list = %v, want [wss://c:3 wss://d:4]", cfg.ChannelAddresses)
	}
}
