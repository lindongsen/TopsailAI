//go:build integration

package integration_test

import (
	"encoding/json"
	"io"
	"net/http"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"topsailai_agent_cluster/tests/harness"
)

// messagesEnvelope mirrors the Server response envelope for one messages read.
type messagesEnvelope struct {
	Code    any    `json:"code"`
	Message string `json:"message"`
	Data    struct {
		ProviderSessionID string `json:"provider_session_id"`
		MessageCount      int    `json:"message_count"`
		Truncated         bool   `json:"truncated"`
		Messages          []struct {
			Role    string `json:"role"`
			Content string `json:"content"`
		} `json:"messages"`
	} `json:"data"`
}

// TestMessagesRoundTripStoppedSession proves the real API-to-WSS-to-provider path
// for a session that is absent from the inventory.
//
// The session is deliberately not listed by the fixture workspace document, so the
// read cannot be satisfied from inventory data. That is the whole point of the
// command: a stopped session has no cluster resource ID and no live generation, so
// every other read surface refuses it.
func TestMessagesRoundTripStoppedSession(t *testing.T) {
	cluster, err := harness.StartCluster(t, harness.ClusterOptions{ProviderType: "topsailai"})
	if err != nil {
		t.Fatalf("start cluster: %v", err)
	}
	defer cluster.Stop(t)

	status, body, err := cluster.RequestE(http.MethodGet, "/api/v1/messages?endpoint_id=endpoint-1&session_id=stopped-session", nil)
	if err != nil {
		t.Fatalf("request messages: %v", err)
	}
	if status != http.StatusOK {
		t.Fatalf("messages status %d body %s", status, body)
	}
	var envelope messagesEnvelope
	if err := json.Unmarshal(body, &envelope); err != nil {
		t.Fatalf("decode messages envelope: %v body %s", err, body)
	}
	if envelope.Data.ProviderSessionID != "stopped-session" {
		t.Fatalf("provider session id %q", envelope.Data.ProviderSessionID)
	}
	if envelope.Data.MessageCount != 2 || len(envelope.Data.Messages) != 2 {
		t.Fatalf("message count %d len %d", envelope.Data.MessageCount, len(envelope.Data.Messages))
	}
	if envelope.Data.Messages[0].Role != "user" || envelope.Data.Messages[1].Role != "assistant" {
		t.Fatalf("roles %q %q", envelope.Data.Messages[0].Role, envelope.Data.Messages[1].Role)
	}
	if envelope.Data.Messages[0].Content != "fixture message body" {
		t.Fatalf("content %q", envelope.Data.Messages[0].Content)
	}
}

// TestMessagesRoundTripMissingSession proves a session the provider never recorded
// is reported as missing rather than as an empty conversation.
//
// The provider answers a missing session with a successful empty history document,
// so without the existence pre-check this request would return 200 with zero
// messages and the operator would read "this session recorded nothing".
func TestMessagesRoundTripMissingSession(t *testing.T) {
	cluster, err := harness.StartCluster(t, harness.ClusterOptions{ProviderType: "topsailai"})
	if err != nil {
		t.Fatalf("start cluster: %v", err)
	}
	defer cluster.Stop(t)

	status, body, err := cluster.RequestE(http.MethodGet, "/api/v1/messages?endpoint_id=endpoint-1&session_id=never-recorded", nil)
	if err != nil {
		t.Fatalf("request messages: %v", err)
	}
	if status != http.StatusNotFound {
		t.Fatalf("missing session status %d body %s", status, body)
	}
	var envelope messagesEnvelope
	if err := json.Unmarshal(body, &envelope); err != nil {
		t.Fatalf("decode failure envelope: %v body %s", err, body)
	}
	if envelope.Code != "session_not_found" {
		t.Fatalf("failure code %v", envelope.Code)
	}
}

// TestMessagesRoundTripMaxChars proves the API preserves the complete message body.
//
// max_chars is a presentation bound applied by the CLI after provider-specific
// content is decoded. The Server API therefore returns the whole readable body so
// structured provider records are never cut into invalid fragments in transit.
func TestMessagesRoundTripMaxChars(t *testing.T) {
	cluster, err := harness.StartCluster(t, harness.ClusterOptions{ProviderType: "topsailai"})
	if err != nil {
		t.Fatalf("start cluster: %v", err)
	}
	defer cluster.Stop(t)

	status, body, err := cluster.RequestE(http.MethodGet, "/api/v1/messages?endpoint_id=endpoint-1&session_id=stopped-session&max_chars=5", nil)
	if err != nil {
		t.Fatalf("request messages: %v", err)
	}
	if status != http.StatusOK {
		t.Fatalf("messages status %d body %s", status, body)
	}
	var envelope messagesEnvelope
	if err := json.Unmarshal(body, &envelope); err != nil {
		t.Fatalf("decode messages envelope: %v body %s", err, body)
	}
	if len(envelope.Data.Messages) == 0 {
		t.Fatal("no messages returned")
	}
	if got := envelope.Data.Messages[0].Content; got != "fixture message body" {
		t.Fatalf("complete content %q", got)
	}
}

// TestMessagesRoundTripRequiresView proves the Endpoint, rather than the Server,
// refuses a conversation read when the caller's token lacks messages.read.
func TestMessagesRoundTripRequiresView(t *testing.T) {
	policyDir := filepath.Join(t.TempDir(), "endpoint-access.d")
	if err := os.MkdirAll(policyDir, 0o700); err != nil {
		t.Fatalf("create access policy directory: %v", err)
	}
	if err := os.WriteFile(filepath.Join(policyDir, "reader.conf"), []byte("token reader-token\nscopes read_output\n"), 0o600); err != nil {
		t.Fatalf("write access policy: %v", err)
	}
	cluster, err := harness.StartCluster(t, harness.ClusterOptions{
		ProviderType:        "topsailai",
		EndpointEnvironment: map[string]string{"AGENT_CLUSTER_ENDPOINT_ACCESS_POLICY_DIR": policyDir},
	})
	if err != nil {
		t.Fatalf("start cluster: %v", err)
	}
	defer cluster.Stop(t)

	req, err := http.NewRequest(http.MethodGet, cluster.URL("/api/v1/messages?endpoint_id=endpoint-1&session_id=stopped-session"), nil)
	if err != nil {
		t.Fatalf("create messages request: %v", err)
	}
	req.Header.Set("Authorization", "Bearer secret")
	req.Header.Set("X-Endpoint-Token", "reader-token")
	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		t.Fatalf("request messages: %v", err)
	}
	defer resp.Body.Close()
	body, err := io.ReadAll(resp.Body)
	if err != nil {
		t.Fatalf("read messages response: %v", err)
	}
	if resp.StatusCode != http.StatusForbidden {
		t.Fatalf("Endpoint policy status %d body %s", resp.StatusCode, body)
	}
	var envelope messagesEnvelope
	if err := json.Unmarshal(body, &envelope); err != nil {
		t.Fatalf("decode failure envelope: %v body %s", err, body)
	}
	if envelope.Code != "policy_denied" {
		t.Fatalf("failure code %v", envelope.Code)
	}
}

// TestMessagesRoundTripWithDefaultPolicy proves the same request succeeds when
// the Endpoint has no configured access-policy directory.
func TestMessagesRoundTripWithDefaultPolicy(t *testing.T) {
	cluster, err := harness.StartCluster(t, harness.ClusterOptions{ProviderType: "topsailai"})
	if err != nil {
		t.Fatalf("start cluster: %v", err)
	}
	defer cluster.Stop(t)

	status, body, err := cluster.RequestE(http.MethodGet, "/api/v1/messages?endpoint_id=endpoint-1&session_id=stopped-session", nil)
	if err != nil {
		t.Fatalf("request messages: %v", err)
	}
	if status != http.StatusOK {
		t.Fatalf("read_output status %d body %s", status, body)
	}
}

// TestMessagesRoundTripUnknownEndpoint proves a typo is reported as an unknown
// endpoint rather than as an outage.
func TestMessagesRoundTripUnknownEndpoint(t *testing.T) {
	cluster, err := harness.StartCluster(t, harness.ClusterOptions{ProviderType: "topsailai"})
	if err != nil {
		t.Fatalf("start cluster: %v", err)
	}
	defer cluster.Stop(t)

	status, body, err := cluster.RequestE(http.MethodGet, "/api/v1/messages?endpoint_id=no-such-endpoint&session_id=stopped-session", nil)
	if err != nil {
		t.Fatalf("request messages: %v", err)
	}
	if status != http.StatusNotFound {
		t.Fatalf("unknown endpoint status %d body %s", status, body)
	}
	var envelope messagesEnvelope
	if err := json.Unmarshal(body, &envelope); err != nil {
		t.Fatalf("decode failure envelope: %v body %s", err, body)
	}
	if envelope.Code != "endpoint_not_found" {
		t.Fatalf("failure code %v", envelope.Code)
	}
}

// TestMessagesRoundTripStandaloneCLI proves the noninteractive command reaches the
// same route and renders the conversation.
//
// The standalone surface is the automation contract, so it is exercised through the
// real binary rather than through the client package.
func TestMessagesRoundTripStandaloneCLI(t *testing.T) {
	cluster, err := harness.StartCluster(t, harness.ClusterOptions{ProviderType: "topsailai"})
	if err != nil {
		t.Fatalf("start cluster: %v", err)
	}
	defer cluster.Stop(t)
	if _, err := cluster.BuildTUI(t); err != nil {
		t.Fatalf("build CLI: %v", err)
	}

	stdout, stderr, code, err := cluster.RunTUI("messages", "endpoint-1", "stopped-session")
	if err != nil && code == 0 {
		t.Fatalf("run messages: %v stderr=%s", err, stderr)
	}
	if code != 0 {
		t.Fatalf("messages exit code %d stderr=%s stdout=%s", code, stderr, stdout)
	}
	if !containsAll(stdout, "fixture message body", "Role: USER", "Role: ASSISTANT") {
		t.Fatalf("rendered conversation missing content: %s", stdout)
	}
}

// TestMessagesRoundTripStandaloneJSON proves the machine-readable form carries the
// conversation without terminal decoration.
func TestMessagesRoundTripStandaloneJSON(t *testing.T) {
	cluster, err := harness.StartCluster(t, harness.ClusterOptions{ProviderType: "topsailai"})
	if err != nil {
		t.Fatalf("start cluster: %v", err)
	}
	defer cluster.Stop(t)
	if _, err := cluster.BuildTUI(t); err != nil {
		t.Fatalf("build CLI: %v", err)
	}

	stdout, stderr, code, err := cluster.RunTUI("messages", "endpoint-1", "stopped-session", "--json")
	if err != nil && code == 0 {
		t.Fatalf("run messages: %v stderr=%s", err, stderr)
	}
	if code != 0 {
		t.Fatalf("messages exit code %d stderr=%s stdout=%s", code, stderr, stdout)
	}
	var document struct {
		ProviderSessionID string `json:"provider_session_id"`
		MessageCount      int    `json:"message_count"`
		Messages          []struct {
			Role    string `json:"role"`
			Content string `json:"content"`
		} `json:"messages"`
	}
	if err := json.Unmarshal([]byte(stdout), &document); err != nil {
		t.Fatalf("decode standalone json: %v stdout=%s", err, stdout)
	}
	if document.ProviderSessionID != "stopped-session" || document.MessageCount != 2 {
		t.Fatalf("standalone document %+v", document)
	}
	if len(document.Messages) != 2 || document.Messages[0].Content != "fixture message body" {
		t.Fatalf("standalone messages %+v", document.Messages)
	}
}

// TestMessagesRoundTripMissingSessionCLI proves the standalone command reports a
// missing session as a failure instead of printing an empty conversation.
func TestMessagesRoundTripMissingSessionCLI(t *testing.T) {
	cluster, err := harness.StartCluster(t, harness.ClusterOptions{ProviderType: "topsailai"})
	if err != nil {
		t.Fatalf("start cluster: %v", err)
	}
	defer cluster.Stop(t)
	if _, err := cluster.BuildTUI(t); err != nil {
		t.Fatalf("build CLI: %v", err)
	}

	stdout, stderr, code, err := cluster.RunTUI("messages", "endpoint-1", "never-recorded")
	if err != nil && code == 0 {
		t.Fatalf("run messages: %v stderr=%s", err, stderr)
	}
	if code == 0 {
		t.Fatalf("missing session exit code 0 stdout=%s", stdout)
	}
	// The assertion targets the stable machine code, which the shared client
	// decoder now surfaces. Before that fix the envelope `code` field was
	// discarded, so only the human-readable message reached stderr and this
	// assertion had to match message text.
	if !containsAll(stderr, "404", "session_not_found", "provider does not know session", "never-recorded") {
		t.Fatalf("missing session diagnostic: stderr=%s stdout=%s", stderr, stdout)
	}
	// A missing session must never render as an empty conversation, because an
	// empty list is a successful answer for a session that recorded nothing.
	if strings.TrimSpace(stdout) != "" {
		t.Fatalf("missing session wrote to stdout: %q", stdout)
	}
}

// containsAll reports whether every fragment appears in the text.
func containsAll(text string, fragments ...string) bool {
	for _, fragment := range fragments {
		if !strings.Contains(text, fragment) {
			return false
		}
	}
	return true
}
