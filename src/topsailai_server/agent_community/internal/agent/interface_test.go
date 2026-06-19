// Package agent provides agent interface parsing tests.
package agent

import (
	"testing"
	"time"
)

// TestParseInterfaceEmpty verifies empty string returns error.
func TestParseInterfaceEmpty(t *testing.T) {
	_, err := ParseInterface("")
	if err == nil {
		t.Error("expected error for empty interface string")
	}
}

// TestParseInterfaceInvalidJSON verifies invalid JSON returns error.
func TestParseInterfaceInvalidJSON(t *testing.T) {
	_, err := ParseInterface("not json")
	if err == nil {
		t.Error("expected error for invalid JSON")
	}
}

// TestParseInterfaceMinimal verifies minimal valid JSON parses correctly.
func TestParseInterfaceMinimal(t *testing.T) {
	jsonStr := `{"adaptor": "test_adaptor"}`
	iface, err := ParseInterface(jsonStr)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if iface.Adaptor != "test_adaptor" {
		t.Errorf("adaptor = %v, want test_adaptor", iface.Adaptor)
	}
	if iface.TimeoutCheckHealth != DefaultTimeoutCheckHealth {
		t.Errorf("timeout_check_health = %v, want %v", iface.TimeoutCheckHealth, DefaultTimeoutCheckHealth)
	}
	if iface.TimeoutCheckStatus != DefaultTimeoutCheckStatus {
		t.Errorf("timeout_check_status = %v, want %v", iface.TimeoutCheckStatus, DefaultTimeoutCheckStatus)
	}
	if iface.TimeoutChat != DefaultTimeoutChat {
		t.Errorf("timeout_chat = %v, want %v", iface.TimeoutChat, DefaultTimeoutChat)
	}
}

// TestParseInterfaceFull verifies full configuration parsing.
func TestParseInterfaceFull(t *testing.T) {
	jsonStr := `{
		"adaptor": "topsailai_agent",
		"environments": {
			"ACS_AGENT_API_BASE": "http://172.18.0.4:7373",
			"ACS_AGENT_API_KEY": "I-Love-Dawson",
			"ACS_AGENT_API_AUTH": "bearer"
		},
		"timeout_check_health": 10,
		"timeout_check_status": 15,
		"timeout_chat": 300,
		"cmd_check_health": "custom_health_cmd",
		"cmd_check_status": "custom_status_cmd",
		"cmd_chat": "custom_chat_cmd"
	}`

	iface, err := ParseInterface(jsonStr)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}

	if iface.Adaptor != "topsailai_agent" {
		t.Errorf("adaptor = %v, want topsailai_agent", iface.Adaptor)
	}

	if iface.Environments["ACS_AGENT_API_BASE"] != "http://172.18.0.4:7373" {
		t.Errorf("api_base = %v", iface.Environments["ACS_AGENT_API_BASE"])
	}

	if iface.TimeoutCheckHealth != 10*time.Second {
		t.Errorf("timeout_check_health = %v, want 10s", iface.TimeoutCheckHealth)
	}
	if iface.TimeoutCheckStatus != 15*time.Second {
		t.Errorf("timeout_check_status = %v, want 15s", iface.TimeoutCheckStatus)
	}
	if iface.TimeoutChat != 300*time.Second {
		t.Errorf("timeout_chat = %v, want 300s", iface.TimeoutChat)
	}

	if iface.CmdCheckHealth != "custom_health_cmd" {
		t.Errorf("cmd_check_health = %v", iface.CmdCheckHealth)
	}
	if iface.CmdCheckStatus != "custom_status_cmd" {
		t.Errorf("cmd_check_status = %v", iface.CmdCheckStatus)
	}
	if iface.CmdChat != "custom_chat_cmd" {
		t.Errorf("cmd_chat = %v", iface.CmdChat)
	}
}

// TestParseInterfaceDurationString verifies duration parsing from string.
func TestParseInterfaceDurationString(t *testing.T) {
	jsonStr := `{
		"timeout_chat": "30s"
	}`

	iface, err := ParseInterface(jsonStr)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if iface.TimeoutChat != 30*time.Second {
		t.Errorf("timeout_chat = %v, want 30s", iface.TimeoutChat)
	}
}

// TestParseInterfaceDefaultCommands verifies default command generation.
func TestParseInterfaceDefaultCommands(t *testing.T) {
	jsonStr := `{"adaptor": "my_adaptor"}`

	iface, err := ParseInterface(jsonStr)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}

	if iface.CmdCheckHealth != "my_adaptor_cmd_check_health" {
		t.Errorf("default health cmd = %v", iface.CmdCheckHealth)
	}
	if iface.CmdCheckStatus != "my_adaptor_cmd_check_status" {
		t.Errorf("default status cmd = %v", iface.CmdCheckStatus)
	}
	if iface.CmdChat != "my_adaptor_cmd_chat" {
		t.Errorf("default chat cmd = %v", iface.CmdChat)
	}
}

// TestApplyManagerDefaults verifies manager defaults are applied correctly.
func TestApplyManagerDefaults(t *testing.T) {
	jsonStr := `{
		"adaptor": "test",
		"environments": {
			"ACS_AGENT_API_BASE": "http://agent.local:8080"
		}
	}`

	iface, err := ParseInterface(jsonStr)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}

	iface.ApplyManagerDefaults("http://manager.local:9090", "manager-key", "bearer")

	// Existing value should not be overwritten
	if iface.Environments["ACS_AGENT_API_BASE"] != "http://agent.local:8080" {
		t.Errorf("existing api_base overwritten = %v", iface.Environments["ACS_AGENT_API_BASE"])
	}

	// Missing values should be filled with defaults
	if iface.Environments["ACS_AGENT_API_KEY"] != "manager-key" {
		t.Errorf("api_key = %v, want manager-key", iface.Environments["ACS_AGENT_API_KEY"])
	}
	if iface.Environments["ACS_AGENT_API_AUTH"] != "bearer" {
		t.Errorf("api_auth = %v, want bearer", iface.Environments["ACS_AGENT_API_AUTH"])
	}
}

// TestApplyManagerDefaultsAllEmpty verifies all defaults applied when empty.
func TestApplyManagerDefaultsAllEmpty(t *testing.T) {
	jsonStr := `{"adaptor": "test"}`

	iface, err := ParseInterface(jsonStr)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}

	iface.ApplyManagerDefaults("http://manager.local:9090", "key123", "ApiKey")

	if iface.Environments["ACS_AGENT_API_BASE"] != "http://manager.local:9090" {
		t.Errorf("api_base = %v", iface.Environments["ACS_AGENT_API_BASE"])
	}
	if iface.Environments["ACS_AGENT_API_KEY"] != "key123" {
		t.Errorf("api_key = %v", iface.Environments["ACS_AGENT_API_KEY"])
	}
	if iface.Environments["ACS_AGENT_API_AUTH"] != "ApiKey" {
		t.Errorf("api_auth = %v", iface.Environments["ACS_AGENT_API_AUTH"])
	}
}

// TestBuildChatEnv verifies environment building for chat.
func TestBuildChatEnv(t *testing.T) {
	jsonStr := `{
		"adaptor": "test",
		"environments": {
			"ACS_AGENT_API_BASE": "http://agent.local:8080",
			"CUSTOM_VAR": "custom_value"
		},
		"timeout_chat": 120
	}`

	iface, err := ParseInterface(jsonStr)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}

	env := iface.BuildChatEnv(
		"agent1", "Bot", "worker-agent", "group1", "TestGroup",
		"user1", "Alice", "msg1", "Hello world",
		"agent",
		"system-prompt", "group-context", `[{"member_id":"user1"}]`, "mention",
		"",
	)

	// Base environments should be copied
	if env["ACS_AGENT_API_BASE"] != "http://agent.local:8080" {
		t.Errorf("api_base = %v", env["ACS_AGENT_API_BASE"])
	}
	if env["CUSTOM_VAR"] != "custom_value" {
		t.Errorf("custom_var = %v", env["CUSTOM_VAR"])
	}

	// Agent-specific variables should be set
	if env["ACS_AGENT_ID"] != "agent1" {
		t.Errorf("agent_id = %v", env["ACS_AGENT_ID"])
	}
	if env["ACS_AGENT_NAME"] != "Bot" {
		t.Errorf("agent_name = %v", env["ACS_AGENT_NAME"])
	}
	if env["ACS_AGENT_TYPE"] != "worker-agent" {
		t.Errorf("agent_type = %v", env["ACS_AGENT_TYPE"])
	}
	if env["ACS_AGENT_MODE"] != "agent" {
		t.Errorf("agent_mode = %v", env["ACS_AGENT_MODE"])
	}
	if env["ACS_AGENT_MESSAGE"] != "Hello world" {
		t.Errorf("agent_message = %v", env["ACS_AGENT_MESSAGE"])
	}
	if env["ACS_AGENT_TIMEOUT"] != "120" {
		t.Errorf("agent_timeout = %v", env["ACS_AGENT_TIMEOUT"])
	}

	// Group context should be set
	if env["ACS_GROUP_ID"] != "group1" {
		t.Errorf("group_id = %v", env["ACS_GROUP_ID"])
	}
	if env["ACS_GROUP_NAME"] != "TestGroup" {
		t.Errorf("group_name = %v", env["ACS_GROUP_NAME"])
	}

	// Sender context should be set
	if env["ACS_SENDER_ID"] != "user1" {
		t.Errorf("sender_id = %v", env["ACS_SENDER_ID"])
	}
	if env["ACS_SENDER_NAME"] != "Alice" {
		t.Errorf("sender_name = %v", env["ACS_SENDER_NAME"])
	}
	if env["ACS_MESSAGE_ID"] != "msg1" {
		t.Errorf("message_id = %v", env["ACS_MESSAGE_ID"])
	}
	if env["ACS_AGENT_PROMPT"] != "system-prompt" {
		t.Errorf("agent_prompt = %v", env["ACS_AGENT_PROMPT"])
	}
	if env["ACS_GROUP_CONTEXT"] != "group-context" {
		t.Errorf("group_context = %v", env["ACS_GROUP_CONTEXT"])
	}
	if env["ACS_MESSAGE_MENTIONS"] != `[{"member_id":"user1"}]` {
		t.Errorf("message_mentions = %v", env["ACS_MESSAGE_MENTIONS"])
	}
	if env["ACS_MESSAGE_TRIGGER_TYPE"] != "mention" {
		t.Errorf("message_trigger_type = %v", env["ACS_MESSAGE_TRIGGER_TYPE"])
	}

	// Login session key should not be set when empty
	if _, ok := env["ACS_LOGIN_SESSION_KEY"]; ok {
		t.Errorf("ACS_LOGIN_SESSION_KEY should not be set when loginSessionKey is empty")
	}
}

// TestBuildChatEnvWithLoginSessionKey verifies the login session key is forwarded.
func TestBuildChatEnvWithLoginSessionKey(t *testing.T) {
	jsonStr := `{
		"adaptor": "test",
		"environments": {
			"ACS_AGENT_API_BASE": "http://agent.local:8080"
		}
	}`

	iface, err := ParseInterface(jsonStr)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}

	env := iface.BuildChatEnv(
		"manager1", "Manager", "manager-agent", "group1", "TestGroup",
		"user1", "Alice", "msg1", "Hello manager",
		"agent",
		"", "", "", "auto",
		"acc-abc123-550e8400e29b41d4a716446655440000",
	)

	if env["ACS_LOGIN_SESSION_KEY"] != "acc-abc123-550e8400e29b41d4a716446655440000" {
		t.Errorf("ACS_LOGIN_SESSION_KEY = %v", env["ACS_LOGIN_SESSION_KEY"])
	}
}

// TestToEnvSlice verifies environment map to slice conversion.
func TestToEnvSlice(t *testing.T) {
	env := map[string]string{
		"KEY1": "value1",
		"KEY2": "value2",
	}

	slice := ToEnvSlice(env)
	if len(slice) != 2 {
		t.Fatalf("expected 2 env vars, got %d", len(slice))
	}

	// Check that both key-value pairs are present
	found := make(map[string]bool)
	for _, s := range slice {
		found[s] = true
	}
	if !found["KEY1=value1"] {
		t.Error("missing KEY1=value1")
	}
	if !found["KEY2=value2"] {
		t.Error("missing KEY2=value2")
	}
}

// TestMergeEnv verifies environment merging.
func TestMergeEnv(t *testing.T) {
	env1 := map[string]string{"KEY1": "value1", "KEY2": "value2"}
	env2 := map[string]string{"KEY2": "overridden", "KEY3": "value3"}

	merged := MergeEnv(env1, env2)

	if merged["KEY1"] != "value1" {
		t.Errorf("KEY1 = %v", merged["KEY1"])
	}
	if merged["KEY2"] != "overridden" {
		t.Errorf("KEY2 = %v, want overridden", merged["KEY2"])
	}
	if merged["KEY3"] != "value3" {
		t.Errorf("KEY3 = %v", merged["KEY3"])
	}
}

// TestGetEnvOrDefault verifies environment variable fallback.
func TestGetEnvOrDefault(t *testing.T) {
	// Test with a variable that likely doesn't exist
	result := GetEnvOrDefault("ACS_TEST_NONEXISTENT_VAR_12345", "default")
	if result != "default" {
		t.Errorf("result = %v, want default", result)
	}
}
