package server

import (
	"context"
	"errors"
	"net/http"
	"net/http/httptest"
	"path/filepath"
	"strings"
	"testing"

	"topsailai_agent_cluster/internal/client"
	"topsailai_agent_cluster/internal/protocol"
	"topsailai_agent_cluster/internal/security"
	serverstorage "topsailai_agent_cluster/internal/storage/server"
)

// messagesRequester supplies a test conversation through the real HTTP/client
// boundary.
type messagesRequester struct{}

// RequestOutput preserves the existing constructor's output interface.
func (messagesRequester) RequestOutput(context.Context, string, protocol.OutputSnapshotRequest) (protocol.OutputSnapshotResponse, error) {
	return protocol.OutputSnapshotResponse{}, nil
}

// RequestMessages answers with one message so the encoded selectors can be
// observed on the way back.
func (messagesRequester) RequestMessages(_ context.Context, endpoint string, query protocol.MessagesQuery) (protocol.MessagesResult, error) {
	return protocol.MessagesResult{
		ProviderSessionID: query.ProviderSessionID,
		Messages:          []protocol.Message{{Role: "user", Content: endpoint, CreatedAtMS: 1000}},
		MessageCount:      1,
	}, nil
}

// TestMessagesHTTPClient verifies auth, method validation, required selectors and
// that the selectors survive URL encoding.
func TestMessagesHTTPClient(t *testing.T) {
	h := &Handler{Authenticator: security.BearerAuthenticator{Token: "test"}, Output: messagesRequester{}}
	server := httptest.NewServer(h)
	defer server.Close()
	api := client.NewAPIClient(server.URL, "test")
	result, err := api.GetMessages(context.Background(), "e /1", "s 1", 0, 0)
	if err != nil || len(result.Messages) != 1 || result.Messages[0].Content != "e /1" {
		t.Fatalf("%#v %v", result, err)
	}
	if result.ProviderSessionID != "s 1" {
		t.Fatalf("session id = %q, want %q", result.ProviderSessionID, "s 1")
	}
	for _, item := range []struct {
		method, path, token string
		status              int
	}{
		{http.MethodGet, "/api/v1/messages?endpoint_id=e&session_id=s", "", 401},
		{http.MethodPost, "/api/v1/messages?endpoint_id=e&session_id=s", "test", 405},
		{http.MethodGet, "/api/v1/messages?session_id=s", "test", 400},
		{http.MethodGet, "/api/v1/messages?endpoint_id=e", "test", 400},
	} {
		req := httptest.NewRequest(item.method, item.path, nil)
		req.Header.Set("Authorization", "Bearer "+item.token)
		out := httptest.NewRecorder()
		h.ServeHTTP(out, req)
		if out.Code != item.status {
			t.Fatalf("%s %s status=%d want=%d body=%s", item.method, item.path, out.Code, item.status, out.Body.String())
		}
	}
}

// messagesFailureRequester fails every messages query, so the handler must
// classify it.
type messagesFailureRequester struct{ messagesRequester }

// RequestMessages always fails, standing in for an offline endpoint.
func (messagesFailureRequester) RequestMessages(context.Context, string, protocol.MessagesQuery) (protocol.MessagesResult, error) {
	return protocol.MessagesResult{}, errors.New("endpoint is offline")
}

// TestMessagesDistinguishesUnknownEndpointFromOffline proves a typo is not
// reported as an availability failure.
func TestMessagesDistinguishesUnknownEndpointFromOffline(t *testing.T) {
	store, err := serverstorage.Open(context.Background(), filepath.Join(t.TempDir(), "server.db"))
	if err != nil {
		t.Fatal(err)
	}
	defer store.Close()
	if err := store.UpsertEndpoint(context.Background(), protocol.Endpoint{EndpointID: "known", InstanceID: "known-1", DisplayName: "known", Hostname: "host-known", ConnectionState: "online", CapabilityRevision: "v1"}, 1000); err != nil {
		t.Fatal(err)
	}
	h := &Handler{Authenticator: security.BearerAuthenticator{Token: "test"}, Output: messagesFailureRequester{}, Store: store}
	for _, item := range []struct {
		endpointID string
		status     int
		code       string
	}{
		{endpointID: "missing", status: http.StatusNotFound, code: "endpoint_not_found"},
		{endpointID: "known", status: http.StatusServiceUnavailable, code: "endpoint_unavailable"},
	} {
		req := httptest.NewRequest(http.MethodGet, "/api/v1/messages?endpoint_id="+item.endpointID+"&session_id=s", nil)
		req.Header.Set("Authorization", "Bearer test")
		out := httptest.NewRecorder()
		h.ServeHTTP(out, req)
		if out.Code != item.status {
			t.Fatalf("endpoint %q status=%d want=%d body=%s", item.endpointID, out.Code, item.status, out.Body.String())
		}
		if !strings.Contains(out.Body.String(), `"`+item.code+`"`) {
			t.Fatalf("endpoint %q body=%s want code %q", item.endpointID, out.Body.String(), item.code)
		}
	}
}

// messagesCodeRequester returns one adapter-reported failure code unchanged.
type messagesCodeRequester struct {
	messagesRequester
	code string
}

// RequestMessages returns the configured adapter failure code.
func (r messagesCodeRequester) RequestMessages(context.Context, string, protocol.MessagesQuery) (protocol.MessagesResult, error) {
	return protocol.MessagesResult{ErrorCode: r.code, ProviderSessionID: "s"}, nil
}

// TestMessagesAdapterFailureCodes proves an unsupported adapter is not an outage
// and a missing session is not a provider failure. Each outcome needs a different
// remedy, so they must not share one status.
func TestMessagesAdapterFailureCodes(t *testing.T) {
	for _, item := range []struct {
		code   string
		status int
	}{
		{code: protocol.MessagesUnsupported, status: http.StatusNotImplemented},
		{code: protocol.MessagesSessionNotFound, status: http.StatusNotFound},
		{code: protocol.MessagesResponseTooLarge, status: http.StatusBadGateway},
		{code: protocol.MessagesProviderError, status: http.StatusBadGateway},
	} {
		h := &Handler{Authenticator: security.BearerAuthenticator{Token: "test"}, Output: messagesCodeRequester{code: item.code}}
		req := httptest.NewRequest(http.MethodGet, "/api/v1/messages?endpoint_id=e&session_id=s", nil)
		req.Header.Set("Authorization", "Bearer test")
		out := httptest.NewRecorder()
		h.ServeHTTP(out, req)
		if out.Code != item.status {
			t.Fatalf("code %q status=%d want=%d body=%s", item.code, out.Code, item.status, out.Body.String())
		}
		if !strings.Contains(out.Body.String(), `"`+item.code+`"`) {
			t.Fatalf("code %q body=%s", item.code, out.Body.String())
		}
	}
}

// TestMessagesEmptySuccessIsNotAnError proves a session with no recorded messages
// is a successful empty result, distinct from a capability or provider failure.
func TestMessagesEmptySuccessIsNotAnError(t *testing.T) {
	h := &Handler{Authenticator: security.BearerAuthenticator{Token: "test"}, Output: messagesRequester{}}
	req := httptest.NewRequest(http.MethodGet, "/api/v1/messages?endpoint_id=e&session_id=s", nil)
	req.Header.Set("Authorization", "Bearer test")
	out := httptest.NewRecorder()
	h.ServeHTTP(out, req)
	if out.Code != http.StatusOK {
		t.Fatalf("status=%d body=%s", out.Code, out.Body.String())
	}
	if strings.Contains(out.Body.String(), "error_code") {
		t.Fatalf("empty success carried an error: %s", out.Body.String())
	}
}

// messagesDisconnectRequester reproduces the real disconnect path: the channel
// reports a lost endpoint as an error code with no Go error, so the handler must
// classify the code rather than fall through to the provider default.
type messagesDisconnectRequester struct{ messagesRequester }

// RequestMessages returns the channel's disconnect result unchanged.
func (messagesDisconnectRequester) RequestMessages(context.Context, string, protocol.MessagesQuery) (protocol.MessagesResult, error) {
	return protocol.MessagesResult{ErrorCode: "endpoint_unavailable"}, nil
}

// TestMessagesDisconnectIsNotReportedAsProviderError proves a lost endpoint is an
// availability failure, never a provider failure.
func TestMessagesDisconnectIsNotReportedAsProviderError(t *testing.T) {
	h := &Handler{Authenticator: security.BearerAuthenticator{Token: "test"}, Output: messagesDisconnectRequester{}}
	req := httptest.NewRequest(http.MethodGet, "/api/v1/messages?endpoint_id=e&session_id=s", nil)
	req.Header.Set("Authorization", "Bearer test")
	out := httptest.NewRecorder()
	h.ServeHTTP(out, req)
	if out.Code != http.StatusServiceUnavailable {
		t.Fatalf("status=%d want=%d body=%s", out.Code, http.StatusServiceUnavailable, out.Body.String())
	}
	if !strings.Contains(out.Body.String(), `"endpoint_unavailable"`) {
		t.Fatalf("body=%s want code endpoint_unavailable", out.Body.String())
	}
	if strings.Contains(out.Body.String(), `"`+protocol.MessagesProviderError+`"`) {
		t.Fatalf("disconnect was reported as a provider failure: %s", out.Body.String())
	}
}

// TestMessagesForwardsCredentialWithoutScope proves the Server no longer
// refuses a conversation read on permission grounds.
//
// Authorization belongs to the Endpoint that owns the machine. A Server-side
// refusal would be a second authority the Endpoint could not revoke, so a
// credential narrowed to an unrelated scope must still reach the transport: the
// Endpoint decides, and it answers with policy_denied.
func TestMessagesForwardsCredentialWithoutScope(t *testing.T) {
	for _, item := range []struct {
		name   string
		scopes security.ScopeSet
	}{
		{name: "unrestricted", scopes: security.ScopeSet{}},
		{name: "view", scopes: security.NewScopeSet(security.ScopeView)},
		{name: "read_output only", scopes: security.NewScopeSet(security.ScopeReadOutput)},
		{name: "send_message only", scopes: security.NewScopeSet(security.ScopeSendMessage)},
	} {
		t.Run(item.name, func(t *testing.T) {
			h := &Handler{
				Authenticator: security.BearerAuthenticator{Token: "test", Scopes: item.scopes},
				Output:        messagesRequester{},
			}
			req := httptest.NewRequest(http.MethodGet, "/api/v1/messages?endpoint_id=e&session_id=s", nil)
			req.Header.Set("Authorization", "Bearer test")
			out := httptest.NewRecorder()
			h.ServeHTTP(out, req)
			if out.Code == http.StatusForbidden {
				t.Fatalf("the Server refused a conversation read on permission grounds: %s", out.Body.String())
			}
		})
	}
}

// TestMessagesForwardsEndpointToken proves the Endpoint token crosses the
// Server unchanged, so the Endpoint can decide which policy applies.
func TestMessagesForwardsEndpointToken(t *testing.T) {
	requester := &messagesTokenRequester{}
	h := &Handler{
		Authenticator: security.BearerAuthenticator{Token: "test"},
		Output:        requester,
	}
	req := httptest.NewRequest(http.MethodGet, "/api/v1/messages?endpoint_id=e&session_id=s", nil)
	req.Header.Set("Authorization", "Bearer test")
	req.Header.Set(endpointTokenHeader, "endpoint-secret")
	out := httptest.NewRecorder()
	h.ServeHTTP(out, req)
	if requester.token != "endpoint-secret" {
		t.Fatalf("forwarded token=%q want endpoint-secret", requester.token)
	}
}

// messagesTokenRequester records the Endpoint token the Server forwarded. It
// implements the snapshot method as well, because the handler field is typed as
// the snapshot requester and a single-surface double would not satisfy it.
type messagesTokenRequester struct {
	token string
}

func (r *messagesTokenRequester) RequestOutput(context.Context, string, protocol.OutputSnapshotRequest) (protocol.OutputSnapshotResponse, error) {
	return protocol.OutputSnapshotResponse{}, nil
}

func (r *messagesTokenRequester) RequestMessages(ctx context.Context, _ string, _ protocol.MessagesQuery) (protocol.MessagesResult, error) {
	r.token = security.EndpointToken(ctx)
	return protocol.MessagesResult{}, nil
}

// messagesMaxCharsRequester records the query the Server forwarded, so a test can
// prove the bound was parsed at the boundary and passed down as an explicit value.
type messagesMaxCharsRequester struct {
	messagesRequester
	queries []protocol.MessagesQuery
}

// RequestMessages records one forwarded query.
func (r *messagesMaxCharsRequester) RequestMessages(_ context.Context, _ string, query protocol.MessagesQuery) (protocol.MessagesResult, error) {
	r.queries = append(r.queries, query)
	return protocol.MessagesResult{ProviderSessionID: query.ProviderSessionID}, nil
}

// TestMessagesMaxCharsReachesTheEndpoint proves the bound travels from the HTTP
// query string to the forwarded protocol query. Without the wiring the capability
// would exist but be unreachable from every surface.
func TestMessagesMaxCharsReachesTheEndpoint(t *testing.T) {
	requester := &messagesMaxCharsRequester{}
	h := &Handler{Authenticator: security.BearerAuthenticator{Token: "test"}, Output: requester}
	server := httptest.NewServer(h)
	defer server.Close()
	api := client.NewAPIClient(server.URL, "test")
	for _, item := range []struct {
		maxChars int
		want     int
	}{
		{0, 0},
		{500, 500},
		{100000, 100000},
	} {
		if _, err := api.GetMessages(context.Background(), "ep-1", "s-1", item.maxChars, 0); err != nil {
			t.Fatalf("maxChars=%d err=%v", item.maxChars, err)
		}
		if got := requester.queries[len(requester.queries)-1].MaxChars; got != item.want {
			t.Fatalf("maxChars=%d forwarded=%d want=%d", item.maxChars, got, item.want)
		}
	}
}

// TestMessagesInvalidMaxCharsKeepsProviderDefault proves an unusable bound is
// ignored rather than silently narrowing every message to zero characters.
func TestMessagesInvalidMaxCharsKeepsProviderDefault(t *testing.T) {
	requester := &messagesMaxCharsRequester{}
	h := &Handler{Authenticator: security.BearerAuthenticator{Token: "test"}, Output: requester}
	server := httptest.NewServer(h)
	defer server.Close()
	for _, value := range []string{"abc", "-3", ""} {
		req := httptest.NewRequest(http.MethodGet, "/api/v1/messages?endpoint_id=ep-1&session_id=s-1&max_chars="+value, nil)
		req.Header.Set("Authorization", "Bearer test")
		out := httptest.NewRecorder()
		h.ServeHTTP(out, req)
		if out.Code != http.StatusOK {
			t.Fatalf("max_chars=%q status=%d body=%s", value, out.Code, out.Body.String())
		}
		if got := requester.queries[len(requester.queries)-1].MaxChars; got != 0 {
			t.Fatalf("max_chars=%q forwarded=%d want=0", value, got)
		}
	}
}
