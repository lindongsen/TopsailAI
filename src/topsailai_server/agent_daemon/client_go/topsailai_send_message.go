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
}

func (c *Config) baseURL() string {
	return fmt.Sprintf("http://%s:%s", c.Host, c.Port)
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

	host := getEnv("TOPSAILAI_AGENT_DAEMON_HOST", "localhost")
	port := getEnv("TOPSAILAI_AGENT_DAEMON_PORT", "7373")
	sessionID := getEnv("TOPSAILAI_SESSION_ID", "")
	message := getEnv("TOPSAILAI_MESSAGE", "")
	role := getEnv("TOPSAILAI_MESSAGE_ROLE", "user")
	waitInterval := intEnv("WAIT_INTERVAL", 2)
	maxWaitTime := intEnv("MAX_WAIT_TIME", 300)
	resultOnly := envBool("RESULT_ONLY")

	flag.StringVar(&cfg.Host, "host", host, "Agent daemon host")
	flag.StringVar(&cfg.Port, "port", port, "Agent daemon port")
	flag.StringVar(&cfg.SessionID, "session-id", sessionID, "Session ID")
	flag.StringVar(&cfg.Message, "message", message, "Message content")
	flag.StringVar(&cfg.Role, "role", role, "Message role (user/assistant)")
	flag.IntVar(&cfg.WaitInterval, "wait-interval", waitInterval, "Wait interval in seconds")
	flag.IntVar(&cfg.MaxWaitTime, "max-wait-time", maxWaitTime, "Max wait time in seconds")
	flag.BoolVar(&cfg.ResultOnly, "result-only", resultOnly, "Only output result")

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

	resp, err := http.Post(url, "application/json", bytes.NewBuffer(jsonData))
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

// listMessages retrieves messages after the given message ID
func listMessages(cfg *Config, afterMsgID string) ([]Message, error) {
	url := cfg.baseURL() + "/api/v1/message?session_id=" + cfg.SessionID + "&sort_key=create_time&order_by=asc&limit=100"

	resp, err := http.Get(url)
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

	// Filter messages that come after afterMsgID
	var result []Message
	found := false
	for _, msg := range messages {
		if msg.MsgID == afterMsgID {
			found = true
			continue
		}
		if found {
			result = append(result, msg)
		}
	}

	return result, nil
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

func main() {
	cfg := loadConfig()

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

	// Wait for result
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
