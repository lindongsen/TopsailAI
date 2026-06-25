// Package main provides HTTP API client for the ACS server.
package main

import (
	"bytes"
	"encoding/json"
	"fmt"
	"io"
	"log"
	"net/http"
	"net/url"
	"os"
	"strconv"
	"strings"
	"time"
)

// debugLog writes a debug message when ACS_CLI_DEBUG is set to a truthy value.
func debugLog(format string, args ...interface{}) {
	if os.Getenv("ACS_CLI_DEBUG") == "" {
		return
	}
	log.Printf("[acs-cli-debug] "+format, args...)
}

// AuthMethod represents the authentication method used by the API client.
type AuthMethod string

const (
	// AuthMethodAPIKey authenticates using an API key token.
	AuthMethodAPIKey AuthMethod = "api_key"
	// AuthMethodSession authenticates using a login session key.
	AuthMethodSession AuthMethod = "session"
)

// APIResponse is the standard response envelope from ACS server.
type APIResponse struct {
	Data    json.RawMessage `json:"data"`
	Error   string          `json:"error"`
	TraceID string          `json:"trace_id"`
}

// APIClient wraps HTTP calls to the ACS server.
type APIClient struct {
	baseURL    string
	client     *http.Client
	authMethod AuthMethod
	apiKey     string
	sessionKey string
}

// NewAPIClient creates a new API client.
func NewAPIClient(baseURL string) *APIClient {
	return &APIClient{
		baseURL: baseURL,
		client: &http.Client{
			Timeout: 30 * time.Second,
		},
	}
}

// SetAPIKey switches the client to API key authentication.
func (c *APIClient) SetAPIKey(apiKey string) {
	apiKey = strings.TrimSpace(apiKey)
	c.apiKey = apiKey
	c.sessionKey = ""
	c.authMethod = AuthMethodAPIKey
	debugLog("SetAPIKey: method=%s, hasCredential=%t", c.authMethod, apiKey != "")
}

// SetSessionKey switches the client to session-key authentication.
func (c *APIClient) SetSessionKey(sessionKey string) {
	sessionKey = strings.TrimSpace(sessionKey)
	c.sessionKey = sessionKey
	c.apiKey = ""
	c.authMethod = AuthMethodSession
	debugLog("SetSessionKey: method=%s, hasCredential=%t", c.authMethod, sessionKey != "")
}

// SetAuthMethod explicitly sets the authentication method and credential.
func (c *APIClient) SetAuthMethod(method AuthMethod, credential string) {
	credential = strings.TrimSpace(credential)
	switch method {
	case AuthMethodAPIKey:
		c.SetAPIKey(credential)
	case AuthMethodSession:
		c.SetSessionKey(credential)
	default:
		c.apiKey = ""
		c.sessionKey = ""
		c.authMethod = ""
		debugLog("SetAuthMethod: cleared auth")
	}
}

// AuthMethod returns the current authentication method.
func (c *APIClient) AuthMethod() AuthMethod {
	return c.authMethod
}

// IsAuthenticated returns true when the client has a credential configured.
func (c *APIClient) IsAuthenticated() bool {
	if c.authMethod == AuthMethodAPIKey {
		return c.apiKey != ""
	}
	if c.authMethod == AuthMethodSession {
		return c.sessionKey != ""
	}
	return false
}

// ListQuery holds common list query parameters.
type ListQuery struct {
	Offset     int
	Limit      int
	SortKey    string
	OrderBy    string
	CreateAtMs string
	UpdateAtMs string
}

// ToQueryString converts ListQuery to URL query string.
func (q ListQuery) ToQueryString() string {
	values := url.Values{}
	if q.Offset > 0 {
		values.Set("offset", strconv.Itoa(q.Offset))
	}
	if q.Limit > 0 {
		values.Set("limit", strconv.Itoa(q.Limit))
	}
	if q.SortKey != "" {
		values.Set("sort_key", q.SortKey)
	}
	if q.OrderBy != "" {
		values.Set("order_by", q.OrderBy)
	}
	if q.CreateAtMs != "" {
		values.Set("create_at_ms", q.CreateAtMs)
	}
	if q.UpdateAtMs != "" {
		values.Set("update_at_ms", q.UpdateAtMs)
	}
	return values.Encode()
}

// doRequest performs an HTTP request and returns the parsed APIResponse.
func (c *APIClient) doRequest(method, path string, body []byte) (*APIResponse, error) {
	reqURL := c.baseURL + path
	var bodyReader io.Reader
	if body != nil {
		bodyReader = bytes.NewReader(body)
	}

	req, err := http.NewRequest(method, reqURL, bodyReader)
	if err != nil {
		return nil, fmt.Errorf("failed to create request: %w", err)
	}
	if body != nil {
		req.Header.Set("Content-Type", "application/json")
	}

	// Apply authentication header based on the active method.
	switch c.authMethod {
	case AuthMethodAPIKey:
		if c.apiKey != "" {
			req.Header.Set("Authorization", "Bearer "+c.apiKey)
			debugLog("doRequest %s %s: Authorization header set (method=%s)", method, path, c.authMethod)
		} else {
			debugLog("doRequest %s %s: API key auth selected but credential empty", method, path)
		}
	case AuthMethodSession:
		if c.sessionKey != "" {
			req.Header.Set("X-Session-Key", c.sessionKey)
			debugLog("doRequest %s %s: X-Session-Key header set (method=%s)", method, path, c.authMethod)
		} else {
			debugLog("doRequest %s %s: session auth selected but credential empty", method, path)
		}
	default:
		debugLog("doRequest %s %s: no auth method selected", method, path)
	}

	resp, err := c.client.Do(req)
	if err != nil {
		return nil, fmt.Errorf("request failed: %w", err)
	}
	defer resp.Body.Close()

	respBody, err := io.ReadAll(resp.Body)
	if err != nil {
		return nil, fmt.Errorf("failed to read response body: %w", err)
	}

	// Handle HTTP 204 No Content or empty response body.
	if resp.StatusCode == http.StatusNoContent || len(respBody) == 0 {
		return &APIResponse{}, nil
	}

	var apiResp APIResponse
	if err := json.Unmarshal(respBody, &apiResp); err != nil {
		// If response is not JSON, wrap raw body.
		return nil, fmt.Errorf("HTTP %d: %s", resp.StatusCode, string(respBody))
	}

	// Detect raw server response without envelope (data/error/trace_id fields).
	// When all envelope fields are zero, wrap the raw body as Data.
	if apiResp.Data == nil && apiResp.Error == "" && apiResp.TraceID == "" {
		apiResp.Data = respBody
	}

	if resp.StatusCode >= 400 {
		if apiResp.Error != "" {
			return nil, fmt.Errorf("HTTP %d: %s (trace_id: %s)", resp.StatusCode, apiResp.Error, apiResp.TraceID)
		}
		return nil, fmt.Errorf("HTTP %d: %s", resp.StatusCode, string(respBody))
	}

	return &apiResp, nil
}

// Get performs a GET request.
func (c *APIClient) Get(path string) (*APIResponse, error) {
	return c.doRequest(http.MethodGet, path, nil)
}

// Post performs a POST request with JSON body.
func (c *APIClient) Post(path string, payload interface{}) (*APIResponse, error) {
	data, err := json.Marshal(payload)
	if err != nil {
		return nil, fmt.Errorf("failed to marshal payload: %w", err)
	}
	return c.doRequest(http.MethodPost, path, data)
}

// Put performs a PUT request with JSON body.
func (c *APIClient) Put(path string, payload interface{}) (*APIResponse, error) {
	data, err := json.Marshal(payload)
	if err != nil {
		return nil, fmt.Errorf("failed to marshal payload: %w", err)
	}
	return c.doRequest(http.MethodPut, path, data)
}

// Delete performs a DELETE request.
func (c *APIClient) Delete(path string) (*APIResponse, error) {
	return c.doRequest(http.MethodDelete, path, nil)
}

// GetData extracts the data field from APIResponse into the provided target.
func (r *APIResponse) GetData(target interface{}) error {
	if r.Data == nil {
		return nil
	}
	return json.Unmarshal(r.Data, target)
}
// --- Convenience methods for ACS API ---

// Login authenticates with login_name and login_password.
func (c *APIClient) Login(loginName, loginPassword string) (*APIResponse, error) {
	payload := map[string]interface{}{
		"login_name":     loginName,
		"login_password": loginPassword,
	}
	return c.Post("/api/v1/accounts/login", payload)
}

// GetMe returns the current authenticated account.
func (c *APIClient) GetMe() (*APIResponse, error) {
	return c.Get("/api/v1/accounts/me")
}

// CreateAccount creates a new account.
func (c *APIClient) CreateAccount(req map[string]interface{}) (*APIResponse, error) {
	return c.Post("/api/v1/accounts", req)
}

// ListAccounts lists accounts with optional filters.
func (c *APIClient) ListAccounts(q ListQuery, role, status, externalID string) (*APIResponse, error) {
	values := url.Values{}
	qs := q.ToQueryString()
	if qs != "" {
		parsed, err := url.ParseQuery(qs)
		if err == nil {
			for k, v := range parsed {
				values[k] = v
			}
		}
	}
	if role != "" {
		values.Set("role", role)
	}
	if status != "" {
		values.Set("status", status)
	}
	if externalID != "" {
		values.Set("external_id", externalID)
	}
	path := "/api/v1/accounts"
	if len(values) > 0 {
		path += "?" + values.Encode()
	}
	return c.Get(path)
}
// GetAccount returns a single account by ID.
func (c *APIClient) GetAccount(accountID string) (*APIResponse, error) {
	return c.Get(fmt.Sprintf("/api/v1/accounts/%s", accountID))
}

// UpdateAccount updates an account.
func (c *APIClient) UpdateAccount(accountID string, req map[string]interface{}) (*APIResponse, error) {
	return c.Put(fmt.Sprintf("/api/v1/accounts/%s", accountID), req)
}

// DeleteAccount soft-deletes an account.
func (c *APIClient) DeleteAccount(accountID string) (*APIResponse, error) {
	return c.Delete(fmt.Sprintf("/api/v1/accounts/%s", accountID))
}

// ChangePassword changes the login_password for an account.
func (c *APIClient) ChangePassword(accountID, oldPassword, newPassword string) (*APIResponse, error) {
	payload := map[string]interface{}{
		"new_password": newPassword,
	}
	if oldPassword != "" {
		payload["old_password"] = oldPassword
	}
	return c.Post(fmt.Sprintf("/api/v1/accounts/%s/password", accountID), payload)
}

// CreateSession creates a new login session for an account.
func (c *APIClient) CreateSession(accountID string) (*APIResponse, error) {
	return c.Post(fmt.Sprintf("/api/v1/accounts/%s/session", accountID), map[string]interface{}{})
}

// CreateAPIKey creates a new API key for an account.
func (c *APIClient) CreateAPIKey(accountID, name, role string) (*APIResponse, error) {
	payload := map[string]interface{}{
		"api_key_name": name,
	}
	if role != "" {
		payload["role"] = role
	}
	return c.Post(fmt.Sprintf("/api/v1/accounts/%s/api-keys", accountID), payload)
}

// ListAPIKeys lists API keys for an account.
func (c *APIClient) ListAPIKeys(accountID string, q ListQuery, status string) (*APIResponse, error) {
	values := url.Values{}
	qs := q.ToQueryString()
	if qs != "" {
		parsed, err := url.ParseQuery(qs)
		if err == nil {
			for k, v := range parsed {
				values[k] = v
			}
		}
	}
	if status != "" {
		values.Set("status", status)
	}
	path := fmt.Sprintf("/api/v1/accounts/%s/api-keys", accountID)
	if len(values) > 0 {
		path += "?" + values.Encode()
	}
	return c.Get(path)
}

// DeleteAPIKey deletes an API key.
func (c *APIClient) DeleteAPIKey(accountID, apiKeyID string) (*APIResponse, error) {
	return c.Delete(fmt.Sprintf("/api/v1/accounts/%s/api-keys/%s", accountID, apiKeyID))
}

// ListGroups lists all groups.
func (c *APIClient) ListGroups(q ListQuery) (*APIResponse, error) {
	path := "/api/v1/groups"
	qs := q.ToQueryString()
	if qs != "" {
		path += "?" + qs
	}
	return c.Get(path)
}

// CreateGroup creates a new group.
func (c *APIClient) CreateGroup(name, context, key string) (*APIResponse, error) {
	payload := map[string]interface{}{
		"group_name":    name,
		"group_context": context,
	}
	if key != "" {
		payload["group_key"] = key
	}
	return c.Post("/api/v1/groups", payload)
}

// JoinGroup self-joins the authenticated account to a group.
// groupKey is optional and only required for private groups.
// Self-join requests must not include member_id or member_type; the server
// derives them from the authenticated account.
func (c *APIClient) JoinGroup(groupID, memberName, memberDesc, groupKey string) (*APIResponse, error) {
	payload := map[string]interface{}{
		"member_name": memberName,
	}
	if memberDesc != "" {
		payload["member_description"] = memberDesc
	}
	if groupKey != "" {
		payload["group_key"] = groupKey
	}
	return c.Post(fmt.Sprintf("/api/v1/groups/%s/members", groupID), payload)
}

// GetGroup gets a single group.
func (c *APIClient) GetGroup(groupID string) (*APIResponse, error) {
	return c.Get(fmt.Sprintf("/api/v1/groups/%s", groupID))
}

// UpdateGroup updates a group.
func (c *APIClient) UpdateGroup(groupID, name, context, key string) (*APIResponse, error) {
	payload := map[string]interface{}{}
	if name != "" {
		payload["group_name"] = name
	}
	if context != "" {
		payload["group_context"] = context
	}
	if key != "" {
		payload["group_key"] = key
	}
	return c.Put(fmt.Sprintf("/api/v1/groups/%s", groupID), payload)
}

// DeleteGroup deletes a group.
func (c *APIClient) DeleteGroup(groupID string) (*APIResponse, error) {
	return c.Delete(fmt.Sprintf("/api/v1/groups/%s", groupID))
}

// ListMembers lists all members of a group.
func (c *APIClient) ListMembers(groupID string, q ListQuery) (*APIResponse, error) {
	path := fmt.Sprintf("/api/v1/groups/%s/members", groupID)
	qs := q.ToQueryString()
	if qs != "" {
		path += "?" + qs
	}
	return c.Get(path)
}

// AddMember adds a member to a group.
func (c *APIClient) AddMember(groupID, memberID, memberName, memberDesc, memberType string, memberInterface map[string]interface{}) (*APIResponse, error) {
	payload := map[string]interface{}{
		"member_id":   memberID,
		"member_name": memberName,
		"member_type": memberType,
	}
	if memberDesc != "" {
		payload["member_description"] = memberDesc
	}
	if memberInterface != nil {
		payload["member_interface"] = memberInterface
	}
	return c.Post(fmt.Sprintf("/api/v1/groups/%s/members", groupID), payload)
}

// GetMember gets a single member.
func (c *APIClient) GetMember(groupID, memberID string) (*APIResponse, error) {
	return c.Get(fmt.Sprintf("/api/v1/groups/%s/members/%s", groupID, memberID))
}

// UpdateMember updates a member.
func (c *APIClient) UpdateMember(groupID, memberID, memberName, memberDesc, memberStatus string, memberInterface map[string]interface{}) (*APIResponse, error) {
	payload := map[string]interface{}{}
	if memberName != "" {
		payload["member_name"] = memberName
	}
	if memberDesc != "" {
		payload["member_description"] = memberDesc
	}
	if memberStatus != "" {
		payload["member_status"] = memberStatus
	}
	if memberInterface != nil {
		payload["member_interface"] = memberInterface
	}
	return c.Put(fmt.Sprintf("/api/v1/groups/%s/members/%s", groupID, memberID), payload)
}

// RemoveMember removes a member from a group.
func (c *APIClient) RemoveMember(groupID, memberID string) (*APIResponse, error) {
	return c.Delete(fmt.Sprintf("/api/v1/groups/%s/members/%s", groupID, memberID))
}

// ListMessages lists messages in a group.
func (c *APIClient) ListMessages(groupID string, q ListQuery) (*APIResponse, error) {
	path := fmt.Sprintf("/api/v1/groups/%s/messages", groupID)
	qs := q.ToQueryString()
	if qs != "" {
		path += "?" + qs
	}
	return c.Get(path)
}

// SendMessage sends a message to a group.
// SendMessage sends a message to a group. The server derives sender_id and
// sender_type from the authenticated account/session, so the client must not
// send them.
func (c *APIClient) SendMessage(groupID, text string, attachments []map[string]interface{}) (*APIResponse, error) {
	payload := map[string]interface{}{
		"message_text": text,
	}
	if attachments != nil {
		payload["message_attachments"] = attachments
	}
	return c.Post(fmt.Sprintf("/api/v1/groups/%s/messages", groupID), payload)
}

// UpdateMessage updates a message.
func (c *APIClient) UpdateMessage(groupID, messageID, text string) (*APIResponse, error) {
	payload := map[string]interface{}{
		"message_text": text,
	}
	return c.Put(fmt.Sprintf("/api/v1/groups/%s/messages/%s", groupID, messageID), payload)
}

// DeleteMessage soft-deletes a message.
func (c *APIClient) DeleteMessage(groupID, messageID string) (*APIResponse, error) {
	return c.Delete(fmt.Sprintf("/api/v1/groups/%s/messages/%s", groupID, messageID))
}
