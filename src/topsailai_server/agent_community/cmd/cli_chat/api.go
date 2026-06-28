// Package main provides the HTTP API client for the ACS chat CLI.
package main

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"time"
)

// Client is an HTTP client for the ACS API.
type Client struct {
	baseURL    string
	httpClient *http.Client
	apiKey     string
	sessionKey string
}

// NewClient creates a new API client.
func NewClient(baseURL string) *Client {
	if baseURL == "" {
		baseURL = "http://localhost:7370"
	}
	return &Client{
		baseURL:    baseURL,
		httpClient: &http.Client{Timeout: 30 * time.Second},
	}
}

// SetAPIKey sets the API key for authentication.
func (c *Client) SetAPIKey(apiKey string) {
	c.apiKey = apiKey
	c.sessionKey = ""
}

// SetSessionKey sets the session key for authentication.
func (c *Client) SetSessionKey(sessionKey string) {
	c.sessionKey = sessionKey
	c.apiKey = ""
}

// Me is an alias for GetMe.
func (c *Client) Me(ctx context.Context) (*Account, error) {
	return c.GetMe(ctx)
}

func (c *Client) authHeaders(req *http.Request) {
	if c.sessionKey != "" {
		req.Header.Set("X-Session-Key", c.sessionKey)
	} else if c.apiKey != "" {
		req.Header.Set("Authorization", "Bearer "+c.apiKey)
	}
}

func (c *Client) doURL(ctx context.Context, method, urlStr string, body any, out any) error {
	var bodyReader io.Reader
	if body != nil {
		data, err := json.Marshal(body)
		if err != nil {
			return err
		}
		bodyReader = bytes.NewReader(data)
	}
	req, err := http.NewRequestWithContext(ctx, method, urlStr, bodyReader)
	if err != nil {
		return err
	}
	req.Header.Set("Content-Type", "application/json")
	c.authHeaders(req)
	resp, err := c.httpClient.Do(req)
	if err != nil {
		return err
	}
	defer resp.Body.Close()
	return c.decodeResponse(resp, out)
}

func (c *Client) doJSON(ctx context.Context, method, path string, body any, out any) error {
	u, err := url.JoinPath(c.baseURL, path)
	if err != nil {
		return err
	}
	return c.doURL(ctx, method, u, body, out)
}

func (c *Client) decodeResponse(resp *http.Response, out any) error {
	data, err := io.ReadAll(resp.Body)
	if err != nil {
		return err
	}
	if resp.StatusCode >= 200 && resp.StatusCode < 300 {
		if out == nil {
			return nil
		}
		return json.Unmarshal(data, out)
	}
	var env Response[json.RawMessage]
	if err := json.Unmarshal(data, &env); err == nil && env.Error != "" {
		return fmt.Errorf("%s", env.Error)
	}
	return fmt.Errorf("HTTP %d: %s", resp.StatusCode, string(data))
}

// Login authenticates with login name and password.
func (c *Client) Login(ctx context.Context, loginName, loginPassword string) (*LoginResponse, string, error) {
	body := map[string]string{
		"login_name":     loginName,
		"login_password": loginPassword,
	}
	var resp Response[LoginResponse]
	if err := c.doJSON(ctx, "POST", "/api/v1/accounts/login", body, &resp); err != nil {
		return nil, "", err
	}
	c.SetSessionKey(resp.Data.SessionKey)
	return &resp.Data, resp.Data.SessionKey, nil
}

// GetMe returns the current account.
func (c *Client) GetMe(ctx context.Context) (*Account, error) {
	var resp Response[Account]
	if err := c.doJSON(ctx, "GET", "/api/v1/accounts/me", nil, &resp); err != nil {
		return nil, err
	}
	return &resp.Data, nil
}

// ListGroups lists groups visible to the authenticated account.
func (c *Client) ListGroups(ctx context.Context) ([]Group, error) {
	var resp Response[ListResponse[Group]]
	if err := c.doJSON(ctx, "GET", "/api/v1/groups", nil, &resp); err != nil {
		return nil, err
	}
	return resp.Data.Items, nil
}

// CreateGroup creates a new group.
func (c *Client) CreateGroup(ctx context.Context, name, groupContext, key string) (*Group, error) {
	req := CreateGroupRequest{
		GroupName:    name,
		GroupContext: groupContext,
	}
	if key != "" {
		req.GroupKey = key
	}
	var resp Response[Group]
	if err := c.doJSON(ctx, "POST", "/api/v1/groups", req, &resp); err != nil {
		return nil, err
	}
	return &resp.Data, nil
}

// GetGroup returns a group by ID.
func (c *Client) GetGroup(ctx context.Context, groupID string) (*Group, error) {
	var resp Response[Group]
	if err := c.doJSON(ctx, "GET", "/api/v1/groups/"+groupID, nil, &resp); err != nil {
		return nil, err
	}
	return &resp.Data, nil
}

// ListMembers lists members of a group.
func (c *Client) ListMembers(ctx context.Context, groupID string) ([]Member, error) {
	var resp Response[ListResponse[Member]]
	if err := c.doJSON(ctx, "GET", "/api/v1/groups/"+groupID+"/members", nil, &resp); err != nil {
		return nil, err
	}
	return resp.Data.Items, nil
}

// AddMember adds a member to a group.
func (c *Client) AddMember(ctx context.Context, groupID, memberID, memberName, memberType string, memberInterface any) (*Member, error) {
	req := AddMemberRequest{
		MemberID:        memberID,
		MemberName:      memberName,
		MemberType:      memberType,
		MemberInterface: memberInterface,
	}
	var resp Response[Member]
	if err := c.doJSON(ctx, "POST", "/api/v1/groups/"+groupID+"/members", req, &resp); err != nil {
		return nil, err
	}
	return &resp.Data, nil
}

// LeaveGroup removes the current account from a group.
func (c *Client) LeaveGroup(ctx context.Context, groupID, memberID string) error {
	return c.doJSON(ctx, "DELETE", "/api/v1/groups/"+groupID+"/members/"+memberID, nil, nil)
}

// ListMessages lists messages in a group.
func (c *Client) ListMessages(ctx context.Context, groupID string, limit int) ([]Message, error) {
	u, err := url.Parse(c.baseURL + "/api/v1/groups/" + groupID + "/messages")
	if err != nil {
		return nil, err
	}
	q := u.Query()
	q.Set("limit", fmt.Sprintf("%d", limit))
	u.RawQuery = q.Encode()
	var resp Response[ListResponse[Message]]
	if err := c.doURL(ctx, "GET", u.String(), nil, &resp); err != nil {
		return nil, err
	}
	return resp.Data.Items, nil
}

// SendMessage sends a message to a group.
func (c *Client) SendMessage(ctx context.Context, groupID, text string) (*Message, error) {
	req := SendMessageRequest{MessageText: text}
	var resp Response[Message]
	if err := c.doJSON(ctx, "POST", "/api/v1/groups/"+groupID+"/messages", req, &resp); err != nil {
		return nil, err
	}
	return &resp.Data, nil
}

// TriggerMessage manually triggers agent processing for a message.
func (c *Client) TriggerMessage(ctx context.Context, groupID, messageID string) error {
	return c.doJSON(ctx, "POST", fmt.Sprintf("/api/v1/groups/%s/messages/%s/trigger", groupID, messageID), nil, nil)
}
