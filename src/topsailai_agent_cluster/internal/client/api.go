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
	"topsailai_agent_cluster/internal/security"
)

// endpointTokenHeader carries the token the target Endpoint accepts.
//
// It is a header rather than a query parameter because a URL is recorded by
// Server access logs, reverse proxies and shell history, while a header is not
// recorded by default. The Server forwards this header into the channel frame
// without interpreting it.
const endpointTokenHeader = "X-Endpoint-Token"

// APIClient calls the authenticated Server operator API.
type APIClient struct {
	HTTPClient *http.Client
	BaseURL    string
	Token      string
	// AuthMode selects how the Server credential is presented.
	//
	// An empty value means the default, which is HMAC. The field exists because
	// the Server accepts exactly one mode at a time and refuses a request that
	// arrives in the other one, so the client must present the same mode the
	// Server was configured with. It is a field rather than a constructor
	// argument so an existing caller keeps compiling and keeps the default.
	AuthMode security.AuthMode
	// EndpointTokens maps an Endpoint ID to the token that Endpoint accepts.
	//
	// The mapping lives on the client because the Server must never hold it: a
	// Server that could hand out Endpoint tokens would be able to grant access
	// to every machine, which is exactly the authority this design removes. An
	// absent entry sends no token, and the Endpoint decides whether that is
	// acceptable, so a deployment that configures no policy directory keeps
	// working without any token at all.
	EndpointTokens map[string]string
}

// NewAPIClient constructs an API client for baseURL and Server credential.
func NewAPIClient(baseURL, token string) *APIClient {
	return &APIClient{HTTPClient: http.DefaultClient, BaseURL: strings.TrimRight(baseURL, "/"), Token: token}
}

// applyServerCredential attaches the Server credential in the configured mode.
//
// The two modes are exclusive. A request is signed or it carries a bearer token,
// never both, because a Server configured for one mode refuses the other and a
// request carrying both would leave the operator unable to tell which credential
// was actually accepted.
//
// An empty token attaches nothing. That is deliberate: a Server may be configured
// without a credential, and inventing one would present a credential the operator
// never configured.
func (c *APIClient) applyServerCredential(req *http.Request, body []byte) error {
	if c.Token == "" {
		return nil
	}
	mode := c.AuthMode
	if mode == "" {
		mode = security.DefaultAuthMode
	}
	switch mode {
	case security.ModeBearer:
		req.Header.Set("Authorization", "Bearer "+c.Token)
		return nil
	case security.ModeHMAC:
		token, err := security.ParseToken(c.Token)
		if err != nil {
			// The mode is HMAC but the credential has no key identifier, so no
			// signature can be produced. Reporting it here names the real
			// mistake; sending an unsigned request would be refused by the
			// Server with a generic authentication failure that points at the
			// token value instead of at its format.
			return fmt.Errorf("server credential is not in key_id.secret form required by hmac mode: %w", err)
		}
		// The signed path is taken from the request itself rather than from the
		// caller's path argument, so the client and the Server derive it with the
		// same function. Rebuilding it from the argument would let the two
		// disagree about escaping and produce a signature that fails to verify
		// for a request that is otherwise correct.
		signature, err := security.SignRequest(token, func(timestampMS int64, nonce string) string {
			return security.CanonicalHTTPRequest(req.Method, req.URL.RequestURI(), body, timestampMS, nonce)
		})
		if err != nil {
			return err
		}
		req.Header.Set("Authorization", signature.Header())
		return nil
	default:
		// An unrecognised mode refuses locally instead of guessing. A guess would
		// present a credential in a scheme the operator did not select, and the
		// Server's refusal would then describe the wrong problem.
		return fmt.Errorf("unsupported authentication mode %q", mode)
	}
}

// withEndpointToken attaches the token this Endpoint accepts to the request
// context, so the transport can carry it without every call site handling
// credentials.
//
// An Endpoint with no configured token is left untouched rather than refused
// here. The client cannot know whether the target Endpoint requires a token,
// because an Endpoint with no policy directory accepts every caller. Refusing
// locally would therefore break a deployment where only some machines enforce a
// policy, and it would make the client a second authority that could disagree
// with the Endpoint.
func (c *APIClient) withEndpointToken(ctx context.Context, endpointID string) context.Context {
	token := c.EndpointTokens[endpointID]
	if token == "" {
		return ctx
	}
	return security.WithEndpointToken(ctx, token)
}

// explainRefusal adds the local cause to a refusal that the Endpoint could only
// report as a policy decision.
//
// When the Endpoint refuses because no token was presented, the real cause is
// usually that this CLI has no token for that machine. The Endpoint cannot say
// so, because it cannot distinguish a caller that forgot to configure a token
// from a caller that deliberately presented none. The client can tell the
// difference, so it names the missing configuration instead of leaving the
// operator to guess why a machine they can reach refuses them.
//
// The original error is preserved, because the Endpoint's own code and message
// remain the authoritative statement of what happened.
func (c *APIClient) explainRefusal(err error, endpointID string) error {
	if err == nil {
		return nil
	}
	if _, configured := c.EndpointTokens[endpointID]; configured {
		return err
	}
	if !strings.Contains(err.Error(), "policy_denied") {
		return err
	}
	return fmt.Errorf("%w (no endpoint token is configured for %q in %s)", err, endpointID, endpointTokensEnvName)
}

// endpointTokensEnvName names the CLI configuration key that holds the Endpoint
// token map. It is repeated here rather than imported from the CLI package
// because the client is a library and must not depend on a command.
const endpointTokensEnvName = "AGENT_CLUSTER_CLI_ENDPOINT_TOKENS"

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
	err := c.get(c.withEndpointToken(ctx, endpointID), path, &result)
	return result, c.explainRefusal(err, endpointID)
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
// ctx closes the response body, which releases the follow at the Server; the Server
// then sends output_follow_cancel to the Endpoint, which cancels the stream and
// releases its follow slot. The provider child therefore stops instead of streaming
// into a queue nobody reads.
func (c *APIClient) FollowOutput(ctx context.Context, endpointID, resourceID, generation string, maxBytes, maxLines int) (<-chan FollowChunk, error) {
	path := fmt.Sprintf("/api/v1/output/follow?endpoint_id=%s&resource_id=%s&provider_generation=%s&max_bytes=%d&max_lines=%d", url.QueryEscape(endpointID), url.QueryEscape(resourceID), url.QueryEscape(generation), maxBytes, maxLines)
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, c.BaseURL+path, nil)
	if err != nil {
		return nil, err
	}
	if err := c.applyServerCredential(req, nil); err != nil {
		return nil, err
	}
	if token := security.EndpointToken(c.withEndpointToken(ctx, endpointID)); token != "" {
		req.Header.Set(endpointTokenHeader, token)
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
		return nil, c.explainRefusal(decodeFailure("server follow failed", resp), endpointID)
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
//
// The intent names its own Endpoint, so the token that Endpoint accepts is
// attached here rather than by every caller. A command that reached the Endpoint
// without its token would be refused by a machine that enforces a policy, and the
// refusal would look like a permission problem instead of a missing credential.
func (c *APIClient) AdmitCommand(ctx context.Context, intent protocol.ImmutableIntent) (map[string]any, error) {
	var result map[string]any
	err := c.request(c.withEndpointToken(ctx, intent.EndpointID), http.MethodPost, "/api/v1/commands", intent, &result)
	return result, c.explainRefusal(err, intent.EndpointID)
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
	var bodyBytes []byte
	if body != nil {
		data, err := json.Marshal(body)
		if err != nil {
			return err
		}
		bodyBytes = data
		reader = bytes.NewReader(data)
	}
	req, err := http.NewRequestWithContext(ctx, method, c.BaseURL+path, reader)
	if err != nil {
		return err
	}
	if body != nil {
		req.Header.Set("Content-Type", "application/json")
	}
	if err := c.applyServerCredential(req, bodyBytes); err != nil {
		return err
	}
	if token := security.EndpointToken(ctx); token != "" {
		req.Header.Set(endpointTokenHeader, token)
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
