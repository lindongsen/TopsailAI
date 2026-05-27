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
	APIBase      string
	SessionID    string
	Message      string
	Role         string
	WaitInterval int
	MaxWaitTime  int
	ResultOnly   bool
	APIKey       string
	AuthStyle    string
}

// rawBaseURL returns the base URL without the /api/v1 suffix.
func (c *Config) rawBaseURL() string {
	base := c.APIBase
	if base == "" {
		base = "http://localhost:7373"
	}
	base = strings.TrimSuffix(base, "/")
	base = strings.TrimSuffix(base, "/api/v1")
	return base
}

func (c *Config) baseURL() string {
	base := c.rawBaseURL()
	if !strings.HasSuffix(base, "/api/v1") {
		base = base + "/api/v1"
	}
	return base
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

// loadConfig loads configuration from environment variables and flags
func loadConfig() *Config {
	cfg := &Config{}

	apiBase := getEnv("TOPSAILAI_AGENT_DAEMON_API_BASE", "")
	sessionID := getEnv("TOPSAILAI_SESSION_ID", "")
	message := getEnv("TOPSAILAI_MESSAGE", "")
	role := getEnv("TOPSAILAI_MESSAGE_ROLE", "user")
	waitInterval := intEnv("WAIT_INTERVAL", 2)
	maxWaitTime := intEnv("MAX_WAIT_TIME", 600)
	resultOnly := false
	debugVal := os.Getenv("DEBUG")
	if debugVal != "" {
		if debugVal == "0" {
			resultOnly = true
		} else if debugVal == "1" {
			resultOnly = false
		}
	} else {
		resultOnly = envBool("RESULT_ONLY")
	}
	apiKey := getEnv("TOPSAILAI_AGENT_DAEMON_API_KEY", "")
	authStyle := getEnv("TOPSAILAI_AGENT_DAEMON_AUTH_STYLE", "x-api-key")

	flag.StringVar(&cfg.APIBase, "api-base", apiBase, "Agent daemon API base URL (e.g., http://host:port or http://host:port/api/v1)")
	flag.StringVar(&cfg.SessionID, "session-id", sessionID, "Session ID")
	flag.StringVar(&cfg.Message, "message", message, "Message content")
	flag.StringVar(&cfg.Role, "role", role, "Message role (user/assistant)")
	flag.IntVar(&cfg.WaitInterval, "wait-interval", waitInterval, "Wait interval in seconds")
	flag.IntVar(&cfg.MaxWaitTime, "max-wait-time", maxWaitTime, "Max wait time in seconds")
	flag.BoolVar(&cfg.ResultOnly, "result-only", resultOnly, "Only output result")
	flag.StringVar(&cfg.APIKey, "api-key", apiKey, "API key for authentication")
	flag.StringVar(&cfg.AuthStyle, "auth-style", authStyle, "Authentication header style: x-api-key or bearer")

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
	url := cfg.baseURL() + "/message"

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
func listMessages(cfg *Config, processedMsgID string) ([]Message, error) {
	url := cfg.baseURL() + "/message?session_id=" + cfg.SessionID +
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

// handleHealthCommand checks the health endpoint and prints the raw response.
func handleHealthCommand(cfg *Config) error {
	url := cfg.rawBaseURL() + "/health"

	req, err := http.NewRequest("GET", url, nil)
	if err != nil {
		return fmt.Errorf("failed to create request: %w", err)
	}
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

	fmt.Println(string(body))

	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		return fmt.Errorf("HTTP %d", resp.StatusCode)
	}

	var apiResp APIResponse
	if err := json.Unmarshal(body, &apiResp); err != nil {
		return fmt.Errorf("failed to parse response: %w", err)
	}

	if apiResp.Code != 0 {
		return fmt.Errorf("API error: %s", apiResp.Message)
	}

	return nil
}

// handleStatusCommand gets session status and prints data.status.
func handleStatusCommand(cfg *Config) error {
	if cfg.SessionID == "" {
		return fmt.Errorf("session-id is required for /status command")
	}

	url := cfg.baseURL() + "/session/" + cfg.SessionID

	req, err := http.NewRequest("GET", url, nil)
	if err != nil {
		return fmt.Errorf("failed to create request: %w", err)
	}
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

	var data map[string]interface{}
	if err := json.Unmarshal(apiResp.Data, &data); err != nil {
		return fmt.Errorf("failed to parse data: %w", err)
	}

	status, ok := data["status"].(string)
	if !ok {
		return fmt.Errorf("status not found in response")
	}

	fmt.Println(status)
	return nil
}

func printUsage() {
	fmt.Println("Usage: topsailai_send_message [options]")
	fmt.Println()
	fmt.Println("Options:")
	fmt.Println("  -api-base string    Agent daemon API base URL (default: http://localhost:7373, auto-append /api/v1)")
	fmt.Println("  -session-id string  Session ID (required for send-message and /status)")
	fmt.Println("  -message string     Message content or command (required)")
	fmt.Println("  -role string        Message role (user/assistant) (default \"user\")")
	fmt.Println("  -wait-interval int  Wait interval in seconds (default 2)")
	fmt.Println("  -max-wait-time int  Max wait time in seconds (default 600)")
	fmt.Println("  -result-only        Only output result")
	fmt.Println("  -api-key string     API key for authentication")
	fmt.Println("  -auth-style string  Authentication header style: x-api-key or bearer (default \"x-api-key\")")
	fmt.Println()
	fmt.Println("Commands (when -message starts with '/'):")
	fmt.Println("  /health             Check daemon health (endpoint: /health)")
	fmt.Println("  /status             Get session status (endpoint: /api/v1/session/{session_id})")
}

func main() {
	cfg := loadConfig()

	if cfg.Message == "" {
		fmt.Fprintln(os.Stderr, "Error: message is required")
		os.Exit(1)
	}

	// Dispatch commands when message starts with '/'
	if strings.HasPrefix(cfg.Message, "/") {
		switch cfg.Message {
		case "/health":
			if err := handleHealthCommand(cfg); err != nil {
				fmt.Fprintf(os.Stderr, "Error: %v\n", err)
				os.Exit(1)
			}
			return
		case "/status":
			if err := handleStatusCommand(cfg); err != nil {
				fmt.Fprintf(os.Stderr, "Error: %v\n", err)
				os.Exit(1)
			}
			return
		default:
			fmt.Fprintf(os.Stderr, "Error: unknown command %s\n", cfg.Message)
			os.Exit(1)
		}
	}

	if cfg.SessionID == "" {
		fmt.Fprintln(os.Stderr, "Error: session-id is required")
		os.Exit(1)
	}

	newMsgID, err := receiveMessage(cfg, "")
	if err != nil {
		fmt.Fprintf(os.Stderr, "Error sending message: %v\n", err)
		os.Exit(1)
	}
	if !cfg.ResultOnly {
		fmt.Printf("new_msg_id: %s\n", newMsgID)
	}
	// If role is assistant, do not wait for result
	if strings.ToLower(cfg.Role) == "assistant" {
		return
	}
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
				for _, msg := range messages {
					if msg.TaskResult != "" {
						fmt.Println(msg.TaskResult)
					} else if msg.Message != "" {
						fmt.Println(msg.Message)
					}
				}
			} else {
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
