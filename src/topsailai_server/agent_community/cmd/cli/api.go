// Package main provides HTTP API client for the ACS server.
package main

import (
	"bytes"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"strconv"
	"time"
)

// APIResponse is the standard response envelope from ACS server.
type APIResponse struct {
	Data    json.RawMessage `json:"data"`
	Error   string          `json:"error"`
	TraceID string          `json:"trace_id"`
}

// APIClient wraps HTTP calls to the ACS server.
type APIClient struct {
	baseURL string
	client  *http.Client
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
func (c *APIClient) SendMessage(groupID, text, senderID, senderType string, attachments []map[string]interface{}) (*APIResponse, error) {
	payload := map[string]interface{}{
		"message_text": text,
		"sender_id":    senderID,
		"sender_type":  senderType,
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
