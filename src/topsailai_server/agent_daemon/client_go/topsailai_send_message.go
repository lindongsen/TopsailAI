package main

import (
	"bytes"
	"encoding/json"
	"flag"
	"fmt"
	"io"
	"net/http"
	"os"
	"strings"
	"time"
)

// Config holds all configuration
type Config struct {
	Host         string
	Port         string
	SessionID    string
	Message      string
	Role         string
	WaitInterval int
	MaxWaitTime  int
	ResultOnly   bool
	APIKey       string
	AuthStyle    string
	APIKeyID     string
	EnvironKey   string
	EnvironValue string
}

func (c *Config) baseURL() string {
	return fmt.Sprintf("http://%s:%s", c.Host, c.Port)
}

// setAuthHeader sets the appropriate authentication header on the request
func (c *Config) setAuthHeader(req *http.Request) {
	if c.APIKey == "" {
		return
	}
	if strings.ToLower(c.AuthStyle) == "bearer" {
		req.Header.Set("Authorization", "Bearer "+c.APIKey)
	} else {
		req.Header.Set("X-API-Key", c.APIKey)
	}
}

// Message represents a message from the API
type Message struct {
	MsgID          string `json:"msg_id"`
	SessionID      string `json:"session_id"`
	ProcessedMsgID string `json:"processed_msg_id"`
	Role           string `json:"role"`
	Message        string `json:"message"`
	TaskID         string `json:"task_id"`
	TaskResult     string `json:"task_result"`
	CreateTime     string `json:"create_time"`
}

// APIResponse is the standard API response
type APIResponse struct {
	Code    int             `json:"code"`
	Data    json.RawMessage `json:"data"`
	Message string          `json:"message"`
}

// ReceiveMessageRequest is the request body for receiving a message
type ReceiveMessageRequest struct {
	Message        string `json:"message"`
	SessionID      string `json:"session_id"`
	Role           string `json:"role"`
	ProcessedMsgID string `json:"processed_msg_id,omitempty"`
}

// SetEnvironRequest is the request body for setting an API key environ
type SetEnvironRequest struct {
	Key   string `json:"key"`
	Value string `json:"value"`
}

// EnvironData represents an API key environ from the API
type EnvironData struct {
	APIKeyID   string `json:"api_key_id"`
	Key        string `json:"key"`
	Value      string `json:"value"`
	CreateTime string `json:"create_time"`
}

// loadConfig loads configuration from environment variables and flags
func loadConfig() *Config {
	cfg := &Config{}

	host := getEnv("TOPSAILAI_AGENT_DAEMON_HOST", "localhost")
	port := getEnv("TOPSAILAI_AGENT_DAEMON_PORT", "7373")
	sessionID := getEnv("TOPSAILAI_SESSION_ID", "")
	message := getEnv("TOPSAILAI_MESSAGE", "")
	role := getEnv("TOPSAILAI_MESSAGE_ROLE", "user")
	waitInterval := intEnv("WAIT_INTERVAL", 2)
	maxWaitTime := intEnv("MAX_WAIT_TIME", 300)
	resultOnly := envBool("RESULT_ONLY")
	apiKey := getEnv("TOPSAILAI_AGENT_DAEMON_API_KEY", "")
	authStyle := getEnv("TOPSAILAI_AGENT_DAEMON_AUTH_STYLE", "x-api-key")

	flag.StringVar(&cfg.Host, "host", host, "Agent daemon host")
	flag.StringVar(&cfg.Port, "port", port, "Agent daemon port")
	flag.StringVar(&cfg.SessionID, "session-id", sessionID, "Session ID")
	flag.StringVar(&cfg.Message, "message", message, "Message content")
	flag.StringVar(&cfg.Role, "role", role, "Message role (user/assistant)")
	flag.IntVar(&cfg.WaitInterval, "wait-interval", waitInterval, "Wait interval in seconds")
	flag.IntVar(&cfg.MaxWaitTime, "max-wait-time", maxWaitTime, "Max wait time in seconds")
	flag.BoolVar(&cfg.ResultOnly, "result-only", resultOnly, "Only output result")
	flag.StringVar(&cfg.APIKey, "api-key", apiKey, "API key for authentication (fallback: TOPSAILAI_AGENT_DAEMON_API_KEY env var)")
	flag.StringVar(&cfg.AuthStyle, "auth-style", authStyle, "Authentication header style: x-api-key or bearer (fallback: TOPSAILAI_AGENT_DAEMON_AUTH_STYLE env var)")
	flag.StringVar(&cfg.APIKeyID, "api-key-id", "", "API key ID for environ operations")
	flag.StringVar(&cfg.EnvironKey, "key", "", "Environment variable key")
	flag.StringVar(&cfg.EnvironValue, "value", "", "Environment variable value")

	flag.Parse()
	return cfg
}

func getEnv(key, defaultVal string) string {
	if val := os.Getenv(key); val != "" {
		return val
	}
	return defaultVal
}

func intEnv(key string, defaultVal int) int {
	if val := os.Getenv(key); val != "" {
		var result int
		fmt.Sscanf(val, "%d", &result)
		return result
	}
	return defaultVal
}

func envBool(key string) bool {
	return strings.ToLower(os.Getenv(key)) == "true" || os.Getenv(key) == "1"
}

// receiveMessage sends a message to the API and returns the new message ID
func receiveMessage(cfg *Config, processedMsgID string) (string, error) {
	url := cfg.baseURL() + "/api/v1/message"

	reqBody := ReceiveMessageRequest{
		Message:        cfg.Message,
		SessionID:      cfg.SessionID,
		Role:           cfg.Role,
		ProcessedMsgID: processedMsgID,
	}

	jsonData, err := json.Marshal(reqBody)
	if err != nil {
		return "", fmt.Errorf("failed to marshal request: %w", err)
	}

	req, err := http.NewRequest("POST", url, bytes.NewBuffer(jsonData))
	if err != nil {
		return "", fmt.Errorf("failed to create request: %w", err)
	}
	req.Header.Set("Content-Type", "application/json")
	cfg.setAuthHeader(req)

	client := &http.Client{}
	resp, err := client.Do(req)
	if err != nil {
		return "", fmt.Errorf("failed to send request: %w", err)
	}
	defer resp.Body.Close()

	body, err := io.ReadAll(resp.Body)
	if err != nil {
		return "", fmt.Errorf("failed to read response: %w", err)
	}

	// Debug: print raw response if non-2xx
	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		return "", fmt.Errorf("HTTP %d: %s", resp.StatusCode, string(body))
	}

	var apiResp APIResponse
	if err := json.Unmarshal(body, &apiResp); err != nil {
		return "", fmt.Errorf("failed to parse response (raw: %s): %w", string(body), err)
	}

	if apiResp.Code != 0 {
		return "", fmt.Errorf("API error: %s", apiResp.Message)
	}

	// Parse data to get msg_id
	var data map[string]interface{}
	if err := json.Unmarshal(apiResp.Data, &data); err != nil {
		return "", fmt.Errorf("failed to parse data (raw: %s): %w", string(apiResp.Data), err)
	}

	msgID, ok := data["msg_id"].(string)
	if !ok {
		return "", fmt.Errorf("msg_id not found in response")
	}

	return msgID, nil
}

// listMessages retrieves messages filtered by processed_msg_id via the API.
// When processedMsgID is provided, the API returns only messages whose
// processed_msg_id matches the given value.
func listMessages(cfg *Config, processedMsgID string) ([]Message, error) {
	url := cfg.baseURL() + "/api/v1/message?session_id=" + cfg.SessionID +
		"&processed_msg_id=" + processedMsgID +
		"&sort_key=create_time&order_by=asc&limit=100"

	req, err := http.NewRequest("GET", url, nil)
	if err != nil {
		return nil, fmt.Errorf("failed to create request: %w", err)
	}
	cfg.setAuthHeader(req)

	client := &http.Client{}
	resp, err := client.Do(req)
	if err != nil {
		return nil, fmt.Errorf("failed to get messages: %w", err)
	}
	defer resp.Body.Close()

	body, err := io.ReadAll(resp.Body)
	if err != nil {
		return nil, fmt.Errorf("failed to read response: %w", err)
	}

	// Debug: print raw response if non-2xx
	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		return nil, fmt.Errorf("HTTP %d: %s", resp.StatusCode, string(body))
	}

	var apiResp APIResponse
	if err := json.Unmarshal(body, &apiResp); err != nil {
		return nil, fmt.Errorf("failed to parse response (raw: %s): %w", string(body), err)
	}

	if apiResp.Code != 0 {
		return nil, fmt.Errorf("API error: %s", apiResp.Message)
	}

	var messages []Message
	if err := json.Unmarshal(apiResp.Data, &messages); err != nil {
		return nil, fmt.Errorf("failed to parse messages: %w", err)
	}

	return messages, nil
}

// setAPIKeyEnviron sets an environment variable for an API key
func setAPIKeyEnviron(cfg *Config) error {
	url := cfg.baseURL() + "/api/v1/apikey/" + cfg.APIKeyID + "/environs"

	reqBody := SetEnvironRequest{
		Key:   cfg.EnvironKey,
		Value: cfg.EnvironValue,
	}

	jsonData, err := json.Marshal(reqBody)
	if err != nil {
		return fmt.Errorf("failed to marshal request: %w", err)
	}

	req, err := http.NewRequest("POST", url, bytes.NewBuffer(jsonData))
	if err != nil {
		return fmt.Errorf("failed to create request: %w", err)
	}
	req.Header.Set("Content-Type", "application/json")
	cfg.setAuthHeader(req)

	client := &http.Client{}
	resp, err := client.Do(req)
	if err != nil {
		return fmt.Errorf("failed to send request: %w", err)
	}
	defer resp.Body.Close()

	body, err := io.ReadAll(resp.Body)
	if err != nil {
		return fmt.Errorf("failed to read response: %w", err)
	}

	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		return fmt.Errorf("HTTP %d: %s", resp.StatusCode, string(body))
	}

	var apiResp APIResponse
	if err := json.Unmarshal(body, &apiResp); err != nil {
		return fmt.Errorf("failed to parse response (raw: %s): %w", string(body), err)
	}

	if apiResp.Code != 0 {
		return fmt.Errorf("API error: %s", apiResp.Message)
	}

	// Parse data to display result
	var data map[string]interface{}
	if err := json.Unmarshal(apiResp.Data, &data); err != nil {
		return fmt.Errorf("failed to parse data: %w", err)
	}

	fmt.Printf("Environ set successfully:\n")
	fmt.Printf("  api_key_id: %v\n", data["api_key_id"])
	fmt.Printf("  key: %v\n", data["key"])
	fmt.Printf("  value: %v\n", data["value"])

	return nil
}

// listAPIKeyEnvirons lists environment variables for an API key
func listAPIKeyEnvirons(cfg *Config) error {
	url := cfg.baseURL() + "/api/v1/apikey/" + cfg.APIKeyID + "/environs"

	req, err := http.NewRequest("GET", url, nil)
	if err != nil {
		return fmt.Errorf("failed to create request: %w", err)
	}
	cfg.setAuthHeader(req)

	client := &http.Client{}
	resp, err := client.Do(req)
	if err != nil {
		return fmt.Errorf("failed to get environs: %w", err)
	}
	defer resp.Body.Close()

	body, err := io.ReadAll(resp.Body)
	if err != nil {
		return fmt.Errorf("failed to read response: %w", err)
	}

	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		return fmt.Errorf("HTTP %d: %s", resp.StatusCode, string(body))
	}

	var apiResp APIResponse
	if err := json.Unmarshal(body, &apiResp); err != nil {
		return fmt.Errorf("failed to parse response (raw: %s): %w", string(body), err)
	}

	if apiResp.Code != 0 {
		return fmt.Errorf("API error: %s", apiResp.Message)
	}

	// Parse data to get environs list
	var data struct {
		Environs []EnvironData `json:"environs"`
		Total    int           `json:"total"`
	}
	if err := json.Unmarshal(apiResp.Data, &data); err != nil {
		return fmt.Errorf("failed to parse data: %w", err)
	}

	if len(data.Environs) == 0 {
		fmt.Println("No environs found.")
		return nil
	}

	fmt.Printf("Environs (%d total):\n", data.Total)
	for _, env := range data.Environs {
		fmt.Printf("  %s: %s\n", env.Key, env.Value)
	}

	return nil
}

// deleteAPIKeyEnviron deletes an environment variable for an API key
func deleteAPIKeyEnviron(cfg *Config) error {
	url := cfg.baseURL() + "/api/v1/apikey/" + cfg.APIKeyID + "/environs/" + cfg.EnvironKey

	req, err := http.NewRequest("DELETE", url, nil)
	if err != nil {
		return fmt.Errorf("failed to create request: %w", err)
	}
	cfg.setAuthHeader(req)

	client := &http.Client{}
	resp, err := client.Do(req)
	if err != nil {
		return fmt.Errorf("failed to delete environ: %w", err)
	}
	defer resp.Body.Close()

	body, err := io.ReadAll(resp.Body)
	if err != nil {
		return fmt.Errorf("failed to read response: %w", err)
	}

	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		return fmt.Errorf("HTTP %d: %s", resp.StatusCode, string(body))
	}

	var apiResp APIResponse
	if err := json.Unmarshal(body, &apiResp); err != nil {
		return fmt.Errorf("failed to parse response (raw: %s): %w", string(body), err)
	}

	if apiResp.Code != 0 {
		return fmt.Errorf("API error: %s", apiResp.Message)
	}

	fmt.Println("Environ deleted successfully.")
	return nil
}

// formatMessage formats a single message for output
func formatMessage(msg Message) string {
	var sb strings.Builder
	sb.WriteString(fmt.Sprintf("[%s] [%s] [%s]\n", msg.CreateTime, msg.MsgID, msg.Role))
	sb.WriteString(msg.Message)
	if msg.TaskID != "" {
		sb.WriteString(fmt.Sprintf("\n>>> task_id: %s", msg.TaskID))
	}
	if msg.TaskResult != "" {
		sb.WriteString(fmt.Sprintf("\n>>> task_result: %s", msg.TaskResult))
	}
	return sb.String()
}

func runSendMessage(cfg *Config) {
	if cfg.SessionID == "" {
		fmt.Fprintln(os.Stderr, "Error: session-id is required")
		os.Exit(1)
	}
	if cfg.Message == "" {
		fmt.Fprintln(os.Stderr, "Error: message is required")
		os.Exit(1)
	}

	// Send the message
	newMsgID, err := receiveMessage(cfg, "")
	if err != nil {
		fmt.Fprintf(os.Stderr, "Error sending message: %v\n", err)
		os.Exit(1)
	}

	// Output new message ID
	fmt.Printf("new_msg_id: %s\n", newMsgID)

	// Wait for result by querying messages whose processed_msg_id equals newMsgID.
	// The API handles the filtering, so we only get result messages for our request.
	waitInterval := time.Duration(cfg.WaitInterval) * time.Second
	maxWaitTime := time.Duration(cfg.MaxWaitTime) * time.Second
	startTime := time.Now()

	for time.Since(startTime) < maxWaitTime {
		time.Sleep(waitInterval)

		messages, err := listMessages(cfg, newMsgID)
		if err != nil {
			fmt.Fprintf(os.Stderr, "Warning: %v\n", err)
			continue
		}

		if len(messages) > 0 {
			if cfg.ResultOnly {
				// Only output the result (task_result or message)
				for _, msg := range messages {
					if msg.TaskResult != "" {
						fmt.Println(msg.TaskResult)
					} else if msg.Message != "" {
						fmt.Println(msg.Message)
					}
				}
			} else {
				// Output full message format
				for _, msg := range messages {
					fmt.Println("---")
					fmt.Print(formatMessage(msg))
					fmt.Println()
				}
			}
			return
		}
	}

	fmt.Fprintln(os.Stderr, "Error: timeout waiting for result")
	os.Exit(1)
}

func runSetEnviron(cfg *Config) {
	if cfg.APIKeyID == "" {
		fmt.Fprintln(os.Stderr, "Error: api-key-id is required")
		os.Exit(1)
	}
	if cfg.EnvironKey == "" {
		fmt.Fprintln(os.Stderr, "Error: key is required")
		os.Exit(1)
	}
	if cfg.EnvironValue == "" {
		fmt.Fprintln(os.Stderr, "Error: value is required")
		os.Exit(1)
	}

	if err := setAPIKeyEnviron(cfg); err != nil {
		fmt.Fprintf(os.Stderr, "Error setting environ: %v\n", err)
		os.Exit(1)
	}
}

func runListEnvirons(cfg *Config) {
	if cfg.APIKeyID == "" {
		fmt.Fprintln(os.Stderr, "Error: api-key-id is required")
		os.Exit(1)
	}

	if err := listAPIKeyEnvirons(cfg); err != nil {
		fmt.Fprintf(os.Stderr, "Error listing environs: %v\n", err)
		os.Exit(1)
	}
}

func runDeleteEnviron(cfg *Config) {
	if cfg.APIKeyID == "" {
		fmt.Fprintln(os.Stderr, "Error: api-key-id is required")
		os.Exit(1)
	}
	if cfg.EnvironKey == "" {
		fmt.Fprintln(os.Stderr, "Error: key is required")
		os.Exit(1)
	}

	if err := deleteAPIKeyEnviron(cfg); err != nil {
		fmt.Fprintf(os.Stderr, "Error deleting environ: %v\n", err)
		os.Exit(1)
	}
}

func printUsage() {
	fmt.Println("Usage: topsailai_send_message <command> [options]")
	fmt.Println()
	fmt.Println("Commands:")
	fmt.Println("  send-message    Send a message to a session (default)")
	fmt.Println("  set-environ     Set an environment variable for an API key")
	fmt.Println("  list-environs   List environment variables for an API key")
	fmt.Println("  delete-environ  Delete an environment variable for an API key")
	fmt.Println()
	fmt.Println("Global Options:")
	fmt.Println("  -host string       Agent daemon host (default \"localhost\")")
	fmt.Println("  -port string       Agent daemon port (default \"7373\")")
	fmt.Println("  -api-key string    API key for authentication")
	fmt.Println("  -auth-style string Authentication header style: x-api-key or bearer (default \"x-api-key\")")
	fmt.Println()
	fmt.Println("Use 'topsailai_send_message <command> -h' for command-specific help.")
}

func main() {
	// Check if a subcommand is provided
	if len(os.Args) < 2 {
		printUsage()
		os.Exit(1)
	}

	// The first argument after the program name is the subcommand
	cmd := os.Args[1]

	// If the first argument looks like a flag (starts with -), treat as default send-message
	if strings.HasPrefix(cmd, "-") {
		// Reset args to include all arguments for default command
		cmd = "send-message"
	} else {
		// Remove the subcommand from args so flag.Parse works correctly
		os.Args = append([]string{os.Args[0]}, os.Args[2:]...)
	}

	cfg := loadConfig()

	switch cmd {
	case "send-message":
		runSendMessage(cfg)
	case "set-environ":
		runSetEnviron(cfg)
	case "list-environs":
		runListEnvirons(cfg)
	case "delete-environ":
		runDeleteEnviron(cfg)
	case "help", "-h", "--help":
		printUsage()
	default:
		fmt.Fprintf(os.Stderr, "Unknown command: %s\n", cmd)
		printUsage()
		os.Exit(1)
	}
}
