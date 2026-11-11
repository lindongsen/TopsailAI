package client

import (
	"context"
	"fmt"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"topsailai_agent_cluster/internal/protocol"
)

// TestReadRequestsCarryTheEndpointToken verifies that every read route presents
// the token the target Endpoint accepts.
//
// The token is asserted on the header rather than in the URL because a URL is
// recorded by access logs, reverse proxies and shell history, so a token in a
// query parameter would leak into places the operator never inspects.
func TestReadRequestsCarryTheEndpointToken(t *testing.T) {
	seen := make(map[string]string)
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		seen[r.URL.Path] = r.Header.Get(endpointTokenHeader)
		w.Header().Set("Content-Type", "application/json")
		_, _ = fmt.Fprint(w, `{"code":0,"message":"ok","data":null}`)
	}))
	defer server.Close()

	api := NewAPIClient(server.URL, "server-token")
	api.EndpointTokens = map[string]string{"gd-dev": "endpoint-token"}
	ctx := context.Background()

	if _, err := api.GetOutput(ctx, "gd-dev", "res_1", "g1", 1024, 10); err != nil {
		t.Fatalf("GetOutput: %v", err)
	}
	if _, err := api.GetHistory(ctx, "gd-dev", 5); err != nil {
		t.Fatalf("GetHistory: %v", err)
	}
	if _, err := api.GetMessages(ctx, "gd-dev", "s1", 0, 0); err != nil {
		t.Fatalf("GetMessages: %v", err)
	}
	if _, err := api.GetModelCatalog(ctx, "gd-dev", "res_1", "g1"); err != nil {
		t.Fatalf("GetModelCatalog: %v", err)
	}
	if _, err := api.GetLaunchOptions(ctx, "gd-dev", "topsailai"); err != nil {
		t.Fatalf("GetLaunchOptions: %v", err)
	}

	for _, path := range []string{"/api/v1/output", "/api/v1/history", "/api/v1/messages", "/api/v1/model-catalog", "/api/v1/launch-options"} {
		if seen[path] != "endpoint-token" {
			t.Fatalf("%s carried token %q, want endpoint-token", path, seen[path])
		}
	}
}

// TestCommandRequestCarriesTheEndpointToken verifies the command route, which is
// the only mutating path and therefore the one a policy most needs to see.
func TestCommandRequestCarriesTheEndpointToken(t *testing.T) {
	var carried string
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		carried = r.Header.Get(endpointTokenHeader)
		w.Header().Set("Content-Type", "application/json")
		_, _ = fmt.Fprint(w, `{"code":0,"message":"ok","data":null}`)
	}))
	defer server.Close()

	api := NewAPIClient(server.URL, "server-token")
	api.EndpointTokens = map[string]string{"gd-dev": "endpoint-token"}
	intent := protocol.ImmutableIntent{CommandID: "c1", EndpointID: "gd-dev", Operation: protocol.OperationAgentStop}
	if _, err := api.AdmitCommand(context.Background(), intent); err != nil {
		t.Fatalf("AdmitCommand: %v", err)
	}
	if carried != "endpoint-token" {
		t.Fatalf("command carried token %q, want endpoint-token", carried)
	}
}

// TestFollowRequestCarriesTheEndpointToken verifies the streaming route, which
// builds its own request instead of reusing the shared helper.
func TestFollowRequestCarriesTheEndpointToken(t *testing.T) {
	var carried string
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		carried = r.Header.Get(endpointTokenHeader)
		w.Header().Set("Content-Type", "application/x-ndjson")
		_, _ = fmt.Fprint(w, `{"type":"end","error_code":""}`+"\n")
	}))
	defer server.Close()

	api := NewAPIClient(server.URL, "server-token")
	api.EndpointTokens = map[string]string{"gd-dev": "endpoint-token"}
	records, err := api.FollowOutput(context.Background(), "gd-dev", "res_1", "g1", 1024, 10)
	if err != nil {
		t.Fatalf("FollowOutput: %v", err)
	}
	for range records {
	}
	if carried != "endpoint-token" {
		t.Fatalf("follow carried token %q, want endpoint-token", carried)
	}
}

// TestUnconfiguredEndpointSendsNoToken verifies that a machine with no configured
// token is addressed without one.
//
// An Endpoint with no policy directory accepts every caller, so inventing a local
// refusal would break a deployment where only some machines enforce a policy. The
// client therefore stays silent and lets the Endpoint decide.
func TestUnconfiguredEndpointSendsNoToken(t *testing.T) {
	var carried string
	var present bool
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		carried = r.Header.Get(endpointTokenHeader)
		_, present = r.Header[endpointTokenHeader]
		w.Header().Set("Content-Type", "application/json")
		_, _ = fmt.Fprint(w, `{"code":0,"message":"ok","data":null}`)
	}))
	defer server.Close()

	api := NewAPIClient(server.URL, "server-token")
	api.EndpointTokens = map[string]string{"other": "endpoint-token"}
	if _, err := api.GetHistory(context.Background(), "gd-dev", 5); err != nil {
		t.Fatalf("GetHistory: %v", err)
	}
	if present || carried != "" {
		t.Fatalf("unconfigured endpoint carried token %q", carried)
	}
}

// TestRefusalNamesTheMissingLocalToken verifies that a policy refusal on a machine
// with no configured token is explained locally.
//
// The Endpoint cannot distinguish a caller that forgot to configure a token from
// one that deliberately presented none, so only the client can name the real
// cause. Without this the operator sees a policy refusal on a machine they can
// reach and has no reason to look at their own configuration.
func TestRefusalNamesTheMissingLocalToken(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(http.StatusForbidden)
		_, _ = fmt.Fprint(w, `{"code":"policy_denied","message":"operation history.read requires an endpoint token"}`)
	}))
	defer server.Close()

	api := NewAPIClient(server.URL, "server-token")
	_, err := api.GetHistory(context.Background(), "gd-dev", 5)
	if err == nil {
		t.Fatal("GetHistory succeeded, want a refusal")
	}
	if !strings.Contains(err.Error(), endpointTokensEnvName) {
		t.Fatalf("refusal did not name the local configuration: %v", err)
	}
	if !strings.Contains(err.Error(), "policy_denied") {
		t.Fatalf("refusal dropped the Endpoint own code: %v", err)
	}
}

// TestRefusalOnConfiguredEndpointIsUnchanged verifies that a refusal from a
// machine whose token is configured is reported verbatim, because the local
// configuration is then not the cause and naming it would mislead.
func TestRefusalOnConfiguredEndpointIsUnchanged(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(http.StatusForbidden)
		_, _ = fmt.Fprint(w, `{"code":"policy_denied","message":"operation history.read is not permitted"}`)
	}))
	defer server.Close()

	api := NewAPIClient(server.URL, "server-token")
	api.EndpointTokens = map[string]string{"gd-dev": "endpoint-token"}
	_, err := api.GetHistory(context.Background(), "gd-dev", 5)
	if err == nil {
		t.Fatal("GetHistory succeeded, want a refusal")
	}
	if strings.Contains(err.Error(), endpointTokensEnvName) {
		t.Fatalf("refusal blamed the local configuration: %v", err)
	}
}

// TestNonPolicyFailureIsUnchanged verifies that an unrelated failure is not
// annotated, because the annotation would claim a cause that does not apply.
func TestNonPolicyFailureIsUnchanged(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(http.StatusServiceUnavailable)
		_, _ = fmt.Fprint(w, `{"code":"endpoint_offline","message":"endpoint is offline"}`)
	}))
	defer server.Close()

	api := NewAPIClient(server.URL, "server-token")
	_, err := api.GetHistory(context.Background(), "gd-dev", 5)
	if err == nil {
		t.Fatal("GetHistory succeeded, want a failure")
	}
	if strings.Contains(err.Error(), endpointTokensEnvName) {
		t.Fatalf("unrelated failure was annotated: %v", err)
	}
}
