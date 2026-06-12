// Package agent provides agent command execution and interface parsing.
package agent

import (
	"encoding/json"
	"fmt"
	"os"
	"strconv"
	"time"
)

// Interface represents the parsed agent member_interface configuration.
type Interface struct {
	Adaptor          string            `json:"adaptor"`
	Environments     map[string]string `json:"environments"`
	TimeoutCheckHealth time.Duration   `json:"timeout_check_health"`
	TimeoutCheckStatus time.Duration   `json:"timeout_check_status"`
	TimeoutChat        time.Duration   `json:"timeout_chat"`
	CmdCheckHealth   string            `json:"cmd_check_health"`
	CmdCheckStatus   string            `json:"cmd_check_status"`
	CmdChat          string            `json:"cmd_chat"`
}

// Default timeouts.
const (
	DefaultTimeoutCheckHealth = 5 * time.Second
	DefaultTimeoutCheckStatus = 5 * time.Second
	DefaultTimeoutChat        = 600 * time.Second
)

// ParseInterface parses a member_interface JSON string into an Interface struct.
func ParseInterface(jsonStr string) (*Interface, error) {
	if jsonStr == "" {
		return nil, fmt.Errorf("empty member_interface")
	}

	var raw map[string]interface{}
	if err := json.Unmarshal([]byte(jsonStr), &raw); err != nil {
		return nil, fmt.Errorf("failed to unmarshal member_interface: %w", err)
	}

	iface := &Interface{
		Environments:       make(map[string]string),
		TimeoutCheckHealth: DefaultTimeoutCheckHealth,
		TimeoutCheckStatus: DefaultTimeoutCheckStatus,
		TimeoutChat:        DefaultTimeoutChat,
	}

	// Parse adaptor
	if v, ok := raw["adaptor"].(string); ok {
		iface.Adaptor = v
	}

	// Parse environments
	if envs, ok := raw["environments"].(map[string]interface{}); ok {
		for k, v := range envs {
			if s, ok := v.(string); ok {
				iface.Environments[k] = s
			}
		}
	}

	// Parse timeouts
	iface.TimeoutCheckHealth = parseDuration(raw, "timeout_check_health", DefaultTimeoutCheckHealth)
	iface.TimeoutCheckStatus = parseDuration(raw, "timeout_check_status", DefaultTimeoutCheckStatus)
	iface.TimeoutChat = parseDuration(raw, "timeout_chat", DefaultTimeoutChat)

	// Parse command overrides
	iface.CmdCheckHealth = parseCmd(raw, "cmd_check_health", iface.Adaptor+"_cmd_check_health")
	iface.CmdCheckStatus = parseCmd(raw, "cmd_check_status", iface.Adaptor+"_cmd_check_status")
	iface.CmdChat = parseCmd(raw, "cmd_chat", iface.Adaptor+"_cmd_chat")

	return iface, nil
}

// ApplyManagerDefaults applies default manager-agent settings from environment variables
// when the agent's own configuration is missing.
func (iface *Interface) ApplyManagerDefaults(managerAPIBase, managerAPIKey, managerAPIAuth string) {
	if iface.Environments == nil {
		iface.Environments = make(map[string]string)
	}

	if _, exists := iface.Environments["ACS_AGENT_API_BASE"]; !exists || iface.Environments["ACS_AGENT_API_BASE"] == "" {
		iface.Environments["ACS_AGENT_API_BASE"] = managerAPIBase
	}
	if _, exists := iface.Environments["ACS_AGENT_API_KEY"]; !exists || iface.Environments["ACS_AGENT_API_KEY"] == "" {
		iface.Environments["ACS_AGENT_API_KEY"] = managerAPIKey
	}
	if _, exists := iface.Environments["ACS_AGENT_API_AUTH"]; !exists || iface.Environments["ACS_AGENT_API_AUTH"] == "" {
		iface.Environments["ACS_AGENT_API_AUTH"] = managerAPIAuth
	}
}

// BuildChatEnv builds the environment variables for cmd_chat execution.
func (iface *Interface) BuildChatEnv(
	agentID, agentName, memberType, groupID, groupName,
	senderID, senderName, messageID, messageText string,
	mode string,
	agentPrompt, groupContext, mentionsJSON, triggerType string,
) map[string]string {
	env := make(map[string]string)

	// Copy base environments from interface
	for k, v := range iface.Environments {
		env[k] = v
	}

	// Set agent-specific variables
	env["ACS_AGENT_ID"] = agentID
	env["ACS_AGENT_NAME"] = agentName
	env["ACS_AGENT_TYPE"] = memberType
	env["ACS_AGENT_MODE"] = mode
	env["ACS_AGENT_MESSAGE"] = messageText
	env["ACS_AGENT_TIMEOUT"] = strconv.FormatInt(int64(iface.TimeoutChat.Seconds()), 10)

	// Set agent prompt from service environment variable
	if agentPrompt != "" {
		env["ACS_AGENT_PROMPT"] = agentPrompt
	}

	// Set group context only when last_read_message_id is empty
	if groupContext != "" {
		env["ACS_GROUP_CONTEXT"] = groupContext
	}

	// Set group context
	env["ACS_GROUP_ID"] = groupID
	env["ACS_GROUP_NAME"] = groupName

	// Set sender context
	env["ACS_SENDER_ID"] = senderID
	env["ACS_SENDER_NAME"] = senderName
	env["ACS_MESSAGE_ID"] = messageID

	// Set message mentions and trigger type
	if mentionsJSON != "" {
		env["ACS_MESSAGE_MENTIONS"] = mentionsJSON
	}
	if triggerType != "" {
		env["ACS_MESSAGE_TRIGGER_TYPE"] = triggerType
	}

	return env
}

// parseDuration parses a duration field from raw JSON map.
func parseDuration(raw map[string]interface{}, key string, defaultVal time.Duration) time.Duration {
	v, ok := raw[key]
	if !ok {
		return defaultVal
	}

	switch val := v.(type) {
	case float64:
		return time.Duration(val) * time.Second
	case string:
		d, err := time.ParseDuration(val)
		if err != nil {
			// Try parsing as seconds
			if sec, err := strconv.ParseInt(val, 10, 64); err == nil {
				return time.Duration(sec) * time.Second
			}
			return defaultVal
		}
		return d
	default:
		return defaultVal
	}
}

// parseCmd parses a command field from raw JSON map.
func parseCmd(raw map[string]interface{}, key, defaultVal string) string {
	v, ok := raw[key].(string)
	if !ok || v == "" {
		return defaultVal
	}
	return v
}

// ToEnvSlice converts the environment map to a slice of "KEY=VALUE" strings.
func ToEnvSlice(env map[string]string) []string {
	result := make([]string, 0, len(env))
	for k, v := range env {
		result = append(result, fmt.Sprintf("%s=%s", k, v))
	}
	return result
}

// MergeEnv merges multiple environment maps, with later maps overriding earlier ones.
func MergeEnv(envs ...map[string]string) map[string]string {
	result := make(map[string]string)
	for _, env := range envs {
		for k, v := range env {
			result[k] = v
		}
	}
	return result
}

// GetEnvOrDefault returns the value of an environment variable or a default.
func GetEnvOrDefault(key, defaultVal string) string {
	if v := os.Getenv(key); v != "" {
		return v
	}
	return defaultVal
}
