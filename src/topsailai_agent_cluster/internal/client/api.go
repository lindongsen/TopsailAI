package client

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"strings"

	"topsailai_agent_cluster/internal/protocol"
)

// APIClient calls the authenticated Server operator API.
type APIClient struct {
	HTTPClient *http.Client
	BaseURL    string
	Token      string
}

// NewAPIClient constructs an API client for baseURL and bearer token.
func NewAPIClient(baseURL, token string) *APIClient {
	return &APIClient{HTTPClient: http.DefaultClient, BaseURL: strings.TrimRight(baseURL, "/"), Token: token}
}

// ListEndpoints returns the current endpoint projection.
func (c *APIClient) ListEndpoints(ctx context.Context) ([]protocol.Endpoint, error) {
	var result []protocol.Endpoint
	if err := c.get(ctx, "/api/v1/endpoints", &result); err != nil {
		return nil, err
	}
	return result, nil
}

// GetInventory returns the latest inventory report for endpointID.
func (c *APIClient) GetInventory(ctx context.Context, endpointID string) (protocol.InventoryReport, error) {
	var result protocol.InventoryReport
	err := c.get(ctx, "/api/v1/endpoints/"+endpointID+"/session-state", &result)
	return result, err
}

// GetCapabilities returns the standard capabilities visible for endpointID.
func (c *APIClient) GetCapabilities(ctx context.Context, endpointID string) (protocol.CapabilityDescriptor, error) {
	var result protocol.CapabilityDescriptor
	err := c.get(ctx, "/api/v1/endpoints/"+endpointID+"/capabilities", &result)
	return result, err
}

// GetCommand returns durable command evidence by ID.
func (c *APIClient) GetCommand(ctx context.Context, commandID string) (map[string]any, error) {
	var result map[string]any
	err := c.get(ctx, "/api/v1/commands/"+commandID, &result)
	return result, err
}

// ListCommands returns recent commands for an endpoint or resource.
func (c *APIClient) ListCommands(ctx context.Context, endpointID, resourceID string, limit int) ([]map[string]any, error) {
	path := fmt.Sprintf("/api/v1/commands?endpoint_id=%s&resource_id=%s&limit=%d", url.QueryEscape(endpointID), url.QueryEscape(resourceID), limit)
	var result []map[string]any
	if err := c.get(ctx, path, &result); err != nil {
		return nil, err
	}
	return result, nil
}

// OutputSnapshot is the Server response for a bounded runtime output request.
type OutputSnapshot = protocol.OutputSnapshotResponse

// GetOutput retrieves a bounded output snapshot for a resource.
// maxLines bounds the provider line count and zero keeps the provider default.
func (c *APIClient) GetOutput(ctx context.Context, endpointID, resourceID, generation string, maxBytes, maxLines int) (protocol.OutputSnapshotResponse, error) {
	path := fmt.Sprintf("/api/v1/output?endpoint_id=%s&resource_id=%s&provider_generation=%s&max_bytes=%d&max_lines=%d", url.QueryEscape(endpointID), url.QueryEscape(resourceID), url.QueryEscape(generation), maxBytes, maxLines)
	var result protocol.OutputSnapshotResponse
	err := c.get(ctx, path, &result)
	return result, err
}

// FollowChunk is one streamed output record delivered by FollowOutput. It is an
// alias of the protocol record so the terminal surfaces can consume the same
// vocabulary without importing this HTTP client.
type FollowChunk = protocol.OutputFollowRecord

// FollowOutput streams output records for a resource until the stream ends or ctx
// is cancelled.
//
// The Server answers with newline-delimited JSON rather than one envelope, so this
// method decodes records incrementally instead of reusing request(). Cancelling
// ctx closes the response body, which releases the follow at the Server and stops
// the provider child.
func (c *APIClient) FollowOutput(ctx context.Context, endpointID, resourceID, generation string, maxBytes, maxLines int) (<-chan FollowChunk, error) {
	path := fmt.Sprintf("/api/v1/output/follow?endpoint_id=%s&resource_id=%s&provider_generation=%s&max_bytes=%d&max_lines=%d", url.QueryEscape(endpointID), url.QueryEscape(resourceID), url.QueryEscape(generation), maxBytes, maxLines)
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, c.BaseURL+path, nil)
	if err != nil {
		return nil, err
	}
	if c.Token != "" {
		req.Header.Set("Authorization", "Bearer "+c.Token)
	}
	httpClient := c.HTTPClient
	if httpClient == nil {
		httpClient = http.DefaultClient
	}
	resp, err := httpClient.Do(req)
	if err != nil {
		return nil, err
	}
	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		defer resp.Body.Close()
		return nil, decodeFailure("server follow failed", resp)
	}
	records := make(chan FollowChunk, 64)
	go func() {
		defer resp.Body.Close()
		defer close(records)
		decoder := json.NewDecoder(resp.Body)
		for {
			var record struct {
				Type         string   `json:"type"`
				Lines        []string `json:"lines"`
				ObservedAtMS int64    `json:"observed_at_ms"`
				Truncated    bool     `json:"truncated"`
				ErrorCode    string   `json:"error_code"`
			}
			if err := decoder.Decode(&record); err != nil {
				// A stream that stops without an end record is reported as
				// interrupted, never as a clean finish.
				if ctx.Err() == nil {
					select {
					case records <- FollowChunk{End: true, ErrorCode: "stream_interrupted"}:
					case <-ctx.Done():
					}
				}
				return
			}
			chunk := FollowChunk{Lines: record.Lines, ObservedAtMS: record.ObservedAtMS, Truncated: record.Truncated}
			if record.Type == "end" {
				chunk.End = true
				chunk.ErrorCode = record.ErrorCode
			}
			select {
			case records <- chunk:
			case <-ctx.Done():
				return
			}
			if chunk.End {
				return
			}
		}
	}()
	return records, nil
}

// AdmitCommand submits one immutable command intent.
func (c *APIClient) AdmitCommand(ctx context.Context, intent protocol.ImmutableIntent) (map[string]any, error) {
	var result map[string]any
	err := c.request(ctx, http.MethodPost, "/api/v1/commands", intent, &result)
	return result, err
}

// CancelCommand requests cancellation before dispatch.
func (c *APIClient) CancelCommand(ctx context.Context, commandID string) (map[string]any, error) {
	var result map[string]any
	err := c.request(ctx, http.MethodPost, "/api/v1/commands/"+commandID+"/cancel", nil, &result)
	return result, err
}

func (c *APIClient) get(ctx context.Context, path string, target any) error {
	return c.request(ctx, http.MethodGet, path, nil, target)
}

func (c *APIClient) request(ctx context.Context, method, path string, body any, target any) error {
	var reader io.Reader
	if body != nil {
		data, err := json.Marshal(body)
		if err != nil {
			return err
		}
		reader = bytes.NewReader(data)
	}
	req, err := http.NewRequestWithContext(ctx, method, c.BaseURL+path, reader)
	if err != nil {
		return err
	}
	if body != nil {
		req.Header.Set("Content-Type", "application/json")
	}
	if c.Token != "" {
		req.Header.Set("Authorization", "Bearer "+c.Token)
	}
	httpClient := c.HTTPClient
	if httpClient == nil {
		httpClient = http.DefaultClient
	}
	resp, err := httpClient.Do(req)
	if err != nil {
		return err
	}
	defer resp.Body.Close()
	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		return decodeFailure("server request failed", resp)
	}
	var envelope struct {
		Code    any             `json:"code"`
		Message string          `json:"message"`
		Data    json.RawMessage `json:"data"`
	}
	if err := json.NewDecoder(resp.Body).Decode(&envelope); err != nil {
		return fmt.Errorf("server response (%d) is not a valid envelope: %w", resp.StatusCode, err)
	}
	if target == nil || len(envelope.Data) == 0 || string(envelope.Data) == "null" {
		return nil
	}
	return json.Unmarshal(envelope.Data, target)
}

// failureExcerptBytes bounds how much of a non-JSON failure body is quoted back to
// the operator, so a large HTML error page cannot flood the terminal.
const failureExcerptBytes = 4096

// decodeFailure builds the operator-facing error for a non-2xx response.
//
// The status code is reported first because it is the only evidence that
// distinguishes "this route does not exist" from "the response is corrupt". A
// Server that predates a route answers with plain text, so the envelope decode is
// best-effort: when it fails the bounded body excerpt is quoted instead of the
// decoder's own error, which would otherwise surface a Go type name and hide the
// status code entirely.
func decodeFailure(prefix string, resp *http.Response) error {
	body, _ := io.ReadAll(io.LimitReader(resp.Body, failureExcerptBytes))
	var envelope struct {
		Code    any    `json:"code"`
		Message string `json:"message"`
	}
	if err := json.Unmarshal(body, &envelope); err == nil && envelope.Message != "" {
		if code := failureCode(envelope.Code); code != "" {
			return fmt.Errorf("%s (%d): %s: %s", prefix, resp.StatusCode, code, envelope.Message)
		}
		return fmt.Errorf("%s (%d): %s", prefix, resp.StatusCode, envelope.Message)
	}
	excerpt := strings.TrimSpace(string(body))
	if excerpt == "" {
		return fmt.Errorf("%s (%d): empty response body", prefix, resp.StatusCode)
	}
	return fmt.Errorf("%s (%d): %s", prefix, resp.StatusCode, excerpt)
}

// failureCode renders the envelope code for an error response. A success response
// carries the integer 0, so the field is decoded as any and only a non-empty
// rendering is reported. The code is surfaced because callers must be able to
// match a stable machine code instead of the human-readable message text.
func failureCode(code any) string {
	switch value := code.(type) {
	case nil:
		return ""
	case string:
		return value
	default:
		return fmt.Sprint(value)
	}
}
