//go:build integration

package integration_test

import (
	"bytes"
	"encoding/json"
	"io"
	"net/http"
	"testing"
	"time"
)

// ctlCommandView is the durable command projection the control tests assert on.
// It carries the delivery boundary because a control acknowledgement is a
// submitted boundary, not a confirmed exit.
type ctlCommandView struct {
	Status           string `json:"status"`
	EffectCertainty  string `json:"effect_certainty"`
	DeliveryBoundary string `json:"delivery_boundary"`
	ErrorCode        string `json:"error_code"`
	ProviderResponse string `json:"provider_response"`
}

// TestCtlActionReachesTheProvider proves an advertised control action travels the
// whole chain: Server admission, Endpoint capability check, adapter argv build and
// provider invocation. The provider acknowledges delivery, which is not a claim
// about agent work, so the command finishes with an acknowledged submitted boundary.
func TestCtlActionReachesTheProvider(t *testing.T) {
	c := startExecCluster(t, "")
	defer c.stop(t)
	status, code := postCtlCommand(t, c, "ctl-heartbeat", "ctl.heartbeat", "v1", map[string]any{})
	if status != http.StatusAccepted {
		t.Fatalf("admit status=%d code=%s", status, code)
	}
	view := waitCtlCommand(t, c, "ctl-heartbeat", func(v ctlCommandView) bool { return v.Status == "finished" })
	if view.EffectCertainty != "acknowledged" {
		t.Fatalf("expected an acknowledged delivery, got %+v", view)
	}
	if view.DeliveryBoundary != "submitted" {
		t.Fatalf("expected a submitted boundary, got %+v", view)
	}
	// The provider document is stored verbatim, so the action name proves the
	// adapter built the argv for the requested action rather than a default one.
	var document struct {
		Action        string `json:"action"`
		DeliveryState string `json:"delivery_state"`
	}
	if err := json.Unmarshal([]byte(view.ProviderResponse), &document); err != nil {
		t.Fatalf("decode provider response %q: %v", view.ProviderResponse, err)
	}
	if document.Action != "heartbeat" {
		t.Fatalf("provider saw action %q, want heartbeat", document.Action)
	}
	if document.DeliveryState != "control_acknowledged" {
		t.Fatalf("provider reported %q, want control_acknowledged", document.DeliveryState)
	}
}

// TestCtlActionIsAuthorizedByTheEndpoint proves the Server admits both commands
// while the Endpoint policy permits only the explicitly granted action.
func TestCtlActionIsAuthorizedByTheEndpoint(t *testing.T) {
	c := startExecClusterWithPolicy(t, "", "ctl-token", "token ctl-token\npermissions ctl.heartbeat\n")
	defer c.stop(t)
	status, code := postCtlCommand(t, c, "ctl-read-messages", "ctl.get_session_messages", "v1", map[string]any{})
	if status != http.StatusAccepted {
		t.Fatalf("Server must route the command, got status=%d code=%s", status, code)
	}
	refused := waitCtlCommand(t, c, "ctl-read-messages", func(v ctlCommandView) bool { return v.ErrorCode != "" })
	if refused.ErrorCode != "policy_denied" || refused.EffectCertainty != "not_applied" {
		t.Fatalf("expected an Endpoint policy refusal, got %+v", refused)
	}

	status, code = postCtlCommand(t, c, "ctl-heartbeat-scoped", "ctl.heartbeat", "v1", map[string]any{})
	if status != http.StatusAccepted {
		t.Fatalf("Server must route the granted command, got status=%d code=%s", status, code)
	}
	allowed := waitCtlCommand(t, c, "ctl-heartbeat-scoped", func(v ctlCommandView) bool { return v.Status == "finished" })
	if allowed.ErrorCode != "" || allowed.EffectCertainty != "acknowledged" {
		t.Fatalf("expected the granted action to reach the provider, got %+v", allowed)
	}
}

// TestCtlActionRejectsUnadvertisedAction proves the Server routes the intent but
// the Endpoint rejects an action absent from its advertised capability catalog.
func TestCtlActionRejectsUnadvertisedAction(t *testing.T) {
	c := startExecCluster(t, "")
	defer c.stop(t)
	status, code := postCtlCommand(t, c, "ctl-unadvertised", "ctl.not_a_reviewed_action", "v1", map[string]any{})
	if status != http.StatusAccepted {
		t.Fatalf("Server must route the command, got status=%d code=%s", status, code)
	}
	view := waitCtlCommand(t, c, "ctl-unadvertised", func(v ctlCommandView) bool { return v.ErrorCode != "" })
	if view.ErrorCode != "unsupported" || view.EffectCertainty != "not_applied" {
		t.Fatalf("expected the Endpoint to reject the unadvertised action, got %+v", view)
	}
}

// postCtlCommand admits one control intent against the published session and
// returns the HTTP status plus the machine error code, if any.
func postCtlCommand(t *testing.T, c *execCluster, id, operation, version string, payload map[string]any) (int, string) {
	t.Helper()
	encoded, err := json.Marshal(payload)
	if err != nil {
		t.Fatal(err)
	}
	intent := map[string]any{
		"hash_version": "v1", "command_id": id, "endpoint_id": "endpoint-1",
		"launch_profile_id": "topsailai-main", "operation": operation,
		"operation_version": version, "capability_revision": "topsailai-v1",
		"payload_schema_version": "v1", "payload": json.RawMessage(encoded),
		"execute_before_at_ms": time.Now().Add(20 * time.Second).UnixMilli(),
	}
	if err := addExecTarget(c, intent); err != nil {
		t.Fatal(err)
	}
	body, err := json.Marshal(intent)
	if err != nil {
		t.Fatal(err)
	}
	req, err := http.NewRequest(http.MethodPost, c.url("/api/v1/commands"), bytes.NewReader(body))
	if err != nil {
		t.Fatal(err)
	}
	req.Header.Set("Authorization", "Bearer secret")
	if c.endpointToken != "" {
		req.Header.Set("X-Endpoint-Token", c.endpointToken)
	}
	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		t.Fatal(err)
	}
	defer resp.Body.Close()
	data, err := io.ReadAll(resp.Body)
	if err != nil {
		t.Fatal(err)
	}
	var envelope struct {
		Code string `json:"code"`
	}
	_ = json.Unmarshal(data, &envelope)
	return resp.StatusCode, envelope.Code
}

// waitCtlCommand polls the durable command projection until done reports true.
func waitCtlCommand(t *testing.T, c *execCluster, id string, done func(ctlCommandView) bool) ctlCommandView {
	t.Helper()
	deadline := time.Now().Add(20 * time.Second)
	var last ctlCommandView
	for time.Now().Before(deadline) {
		req, _ := http.NewRequest(http.MethodGet, c.url("/api/v1/commands/"+id), nil)
		req.Header.Set("Authorization", "Bearer secret")
		resp, err := http.DefaultClient.Do(req)
		if err == nil {
			body, _ := io.ReadAll(resp.Body)
			resp.Body.Close()
			var envelope struct {
				Data ctlCommandView `json:"data"`
			}
			if resp.StatusCode == http.StatusOK && json.Unmarshal(body, &envelope) == nil {
				last = envelope.Data
				if done(last) {
					return last
				}
			}
		}
		time.Sleep(100 * time.Millisecond)
	}
	t.Fatalf("command %s did not reach the expected state: %+v", id, last)
	return last
}
