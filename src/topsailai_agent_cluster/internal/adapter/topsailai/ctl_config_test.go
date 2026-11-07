package topsailai

import (
	"context"
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"topsailai_agent_cluster/internal/security"
)

// writeControlActionFile writes a control action document into a temporary file
// and returns its path.
func writeControlActionFile(t *testing.T, body string) string {
	t.Helper()
	path := filepath.Join(t.TempDir(), "control-actions.json")
	if err := os.WriteFile(path, []byte(body), 0o600); err != nil {
		t.Fatalf("write control action file: %v", err)
	}
	return path
}

func TestLoadControlActionSetAcceptsReviewedSubset(t *testing.T) {
	path := writeControlActionFile(t, `{"actions":[
		{"name":"heartbeat","permission":"control"},
		{"name":"pause","permission":"control","payload_schema":{"type":"object","properties":{"reason":{"type":"string"}}}}
	]}`)
	set, err := LoadControlActionSet(path)
	if err != nil {
		t.Fatalf("load: %v", err)
	}
	if set.Len() != 2 {
		t.Fatalf("len = %d, want 2", set.Len())
	}
	if got := set.Names(); len(got) != 2 || got[0] != "heartbeat" || got[1] != "pause" {
		t.Fatalf("names = %v, want file order [heartbeat pause]", got)
	}
	if set.Path != path {
		t.Fatalf("path = %q, want %q", set.Path, path)
	}
	action, ok := set.Get("pause")
	if !ok {
		t.Fatal("pause is not enabled")
	}
	if action.Permission != security.ScopeControl {
		t.Fatalf("pause permission = %q, want %q", action.Permission, security.ScopeControl)
	}
	if !strings.Contains(action.PayloadSchema, `"reason"`) {
		t.Fatalf("pause payload schema = %q, want it to carry reason", action.PayloadSchema)
	}
}

func TestLoadControlActionSetRejectsUnreviewedName(t *testing.T) {
	path := writeControlActionFile(t, `{"actions":[{"name":"rm_rf","permission":"control"}]}`)
	_, err := LoadControlActionSet(path)
	if err == nil {
		t.Fatal("unreviewed action was accepted")
	}
	if !strings.Contains(err.Error(), "not a reviewed provider control action") {
		t.Fatalf("error = %v, want it to name the reviewed contract", err)
	}
}

func TestLoadControlActionSetRejectsPermissionWidening(t *testing.T) {
	// get_session_messages returns conversation content, so control must not be
	// accepted in place of read_output.
	path := writeControlActionFile(t, `{"actions":[{"name":"get_session_messages","permission":"control"}]}`)
	_, err := LoadControlActionSet(path)
	if err == nil {
		t.Fatal("permission widening was accepted")
	}
	if !strings.Contains(err.Error(), "does not match the reviewed permission") {
		t.Fatalf("error = %v, want it to name the permission mismatch", err)
	}
}

func TestLoadControlActionSetRejectsDuplicateName(t *testing.T) {
	path := writeControlActionFile(t, `{"actions":[
		{"name":"heartbeat","permission":"control"},
		{"name":"heartbeat","permission":"control"}
	]}`)
	_, err := LoadControlActionSet(path)
	if err == nil {
		t.Fatal("duplicate action was accepted")
	}
	if !strings.Contains(err.Error(), "listed more than once") {
		t.Fatalf("error = %v, want it to name the duplicate", err)
	}
}

func TestLoadControlActionSetRejectsUnknownField(t *testing.T) {
	path := writeControlActionFile(t, `{"actions":[{"name":"heartbeat","permission":"control","enabled":true}]}`)
	_, err := LoadControlActionSet(path)
	if err == nil {
		t.Fatal("unknown field was accepted")
	}
	if !strings.Contains(err.Error(), "unknown field") {
		t.Fatalf("error = %v, want it to name the unknown field", err)
	}
}

func TestLoadControlActionSetRejectsNonObjectPayloadSchema(t *testing.T) {
	path := writeControlActionFile(t, `{"actions":[{"name":"pause","permission":"control","payload_schema":"nope"}]}`)
	_, err := LoadControlActionSet(path)
	if err == nil {
		t.Fatal("non-object payload schema was accepted")
	}
	if !strings.Contains(err.Error(), "must be a JSON object") {
		t.Fatalf("error = %v, want it to name the schema shape", err)
	}
}

func TestLoadControlActionSetAcceptsEmptyList(t *testing.T) {
	// An explicitly configured empty list disables the whole ctl. family. It must
	// load successfully, because a security default fails closed rather than
	// silently falling back to the reviewed set.
	path := writeControlActionFile(t, `{"actions":[]}`)
	set, err := LoadControlActionSet(path)
	if err != nil {
		t.Fatalf("load: %v", err)
	}
	if set.Len() != 0 {
		t.Fatalf("len = %d, want 0", set.Len())
	}
	if capabilities := controlActionCapabilities(set); len(capabilities) != 0 {
		t.Fatalf("capabilities = %d, want 0 so the family is unreachable", len(capabilities))
	}
	if _, err := controlActionArgs(set, security.ProviderControlPrefix+"heartbeat", "s-1", nil); err == nil {
		t.Fatal("a disabled action still built provider argv")
	}
}

func TestControlActionCapabilitiesKeepReviewedDefaultWhenUnconfigured(t *testing.T) {
	capabilities := controlActionCapabilities(nil)
	if len(capabilities) != len(providerControlActions) {
		t.Fatalf("capabilities = %d, want %d", len(capabilities), len(providerControlActions))
	}
	for _, capability := range capabilities {
		if capability.PayloadSchema != "" {
			t.Fatalf("capability %q payload schema = %q, want empty for the reviewed default", capability.Name, capability.PayloadSchema)
		}
	}
}

func TestControlActionCapabilitiesCarryConfiguredPayloadSchema(t *testing.T) {
	path := writeControlActionFile(t, `{"actions":[{"name":"pause","permission":"control","payload_schema":{"type":"object","properties":{"reason":{"type":"string"}}}}]}`)
	set, err := LoadControlActionSet(path)
	if err != nil {
		t.Fatalf("load: %v", err)
	}
	capabilities := controlActionCapabilities(set)
	if len(capabilities) != 1 {
		t.Fatalf("capabilities = %d, want 1", len(capabilities))
	}
	if capabilities[0].Name != security.ProviderControlPrefix+"pause" {
		t.Fatalf("name = %q, want %q", capabilities[0].Name, security.ProviderControlPrefix+"pause")
	}
	if !strings.Contains(capabilities[0].PayloadSchema, `"reason"`) {
		t.Fatalf("payload schema = %q, want it to carry reason", capabilities[0].PayloadSchema)
	}
}

func TestControlActionArgsRejectDisabledAction(t *testing.T) {
	path := writeControlActionFile(t, `{"actions":[{"name":"heartbeat","permission":"control"}]}`)
	set, err := LoadControlActionSet(path)
	if err != nil {
		t.Fatalf("load: %v", err)
	}
	if _, err := controlActionArgs(set, security.ProviderControlPrefix+"pause", "s-1", nil); err == nil {
		t.Fatal("a disabled action built provider argv")
	}
	args, err := controlActionArgs(set, security.ProviderControlPrefix+"heartbeat", "s-1", nil)
	if err != nil {
		t.Fatalf("enabled action: %v", err)
	}
	want := []string{"runtime", "control", "heartbeat", "-s", "s-1", "-a", "{}", "--json"}
	if len(args) != len(want) {
		t.Fatalf("args = %v, want %v", args, want)
	}
	for index := range want {
		if args[index] != want[index] {
			t.Fatalf("args = %v, want %v", args, want)
		}
	}
}

func TestControlActionSetReloadKeepsPreviousSetOnParseFailure(t *testing.T) {
	path := writeControlActionFile(t, `{"actions":[{"name":"heartbeat","permission":"control"}]}`)
	set, err := LoadControlActionSet(path)
	if err != nil {
		t.Fatalf("load: %v", err)
	}
	if err := set.Reload([]byte(`{"actions":[{"name":"not_reviewed","permission":"control"}]}`)); err == nil {
		t.Fatal("invalid reload was accepted")
	}
	if set.Len() != 1 {
		t.Fatalf("len = %d, want the previous set to stay in force", set.Len())
	}
	if _, ok := set.Get("heartbeat"); !ok {
		t.Fatal("heartbeat was dropped by a failed reload")
	}
}

func TestControlActionSetReloadSwapsAtomically(t *testing.T) {
	path := writeControlActionFile(t, `{"actions":[{"name":"heartbeat","permission":"control"}]}`)
	set, err := LoadControlActionSet(path)
	if err != nil {
		t.Fatalf("load: %v", err)
	}
	if err := set.Reload([]byte(`{"actions":[{"name":"pause","permission":"control"}]}`)); err != nil {
		t.Fatalf("reload: %v", err)
	}
	if _, ok := set.Get("heartbeat"); ok {
		t.Fatal("heartbeat survived a reload that omitted it")
	}
	if _, ok := set.Get("pause"); !ok {
		t.Fatal("pause was not enabled by reload")
	}
}

func TestControlActionSetReloadFromDiskReadsTheFile(t *testing.T) {
	path := writeControlActionFile(t, `{"actions":[{"name":"heartbeat","permission":"control"}]}`)
	set, err := LoadControlActionSet(path)
	if err != nil {
		t.Fatalf("load: %v", err)
	}
	if err := os.WriteFile(path, []byte(`{"actions":[{"name":"pause","permission":"control"}]}`), 0o600); err != nil {
		t.Fatalf("rewrite: %v", err)
	}
	if err := set.ReloadFromDisk(); err != nil {
		t.Fatalf("reload from disk: %v", err)
	}
	if _, ok := set.Get("pause"); !ok {
		t.Fatal("pause was not enabled by reload from disk")
	}
}

func TestControlActionSetReloadFromDiskKeepsPreviousSetOnBrokenFile(t *testing.T) {
	path := writeControlActionFile(t, `{"actions":[{"name":"heartbeat","permission":"control"}]}`)
	set, err := LoadControlActionSet(path)
	if err != nil {
		t.Fatalf("load: %v", err)
	}
	if err := os.WriteFile(path, []byte(`{"actions":[`), 0o600); err != nil {
		t.Fatalf("rewrite: %v", err)
	}
	if err := set.ReloadFromDisk(); err == nil {
		t.Fatal("broken file was accepted")
	}
	if _, ok := set.Get("heartbeat"); !ok {
		t.Fatal("a broken edit disabled the policy")
	}
}

func TestControlActionSetWatchReloadRequiresConfiguration(t *testing.T) {
	var set *ControlActionSet
	if _, err := set.WatchReload(context.Background(), nil); err == nil {
		t.Fatal("a nil set started a watcher")
	}
}

func TestControlActionSetWatchReloadStopsCleanly(t *testing.T) {
	path := writeControlActionFile(t, `{"actions":[{"name":"heartbeat","permission":"control"}]}`)
	set, err := LoadControlActionSet(path)
	if err != nil {
		t.Fatalf("load: %v", err)
	}
	stop, err := set.WatchReload(context.Background(), nil)
	if err != nil {
		t.Fatalf("watch: %v", err)
	}
	done := make(chan struct{})
	go func() {
		stop()
		close(done)
	}()
	select {
	case <-done:
	case <-time.After(5 * time.Second):
		t.Fatal("stop did not return")
	}
}

func TestControlActionSetNilAccessorsAreSafe(t *testing.T) {
	var set *ControlActionSet
	if set.Actions() != nil {
		t.Fatal("nil Actions returned entries")
	}
	if _, ok := set.Get("heartbeat"); ok {
		t.Fatal("nil Get reported an action")
	}
	if set.Len() != 0 {
		t.Fatal("nil Len was non-zero")
	}
	if set.Names() != nil {
		t.Fatal("nil Names returned entries")
	}
}

func TestControlActionTargetPayloadInjectsSessionID(t *testing.T) {
	// get_session_messages needs a provider session_id, and the Endpoint already
	// holds it as the provider key, so the operator never supplies it.
	payload, err := controlActionTargetPayload("get_session_messages", "sess-42", []byte(`{}`))
	if err != nil {
		t.Fatalf("inject: %v", err)
	}
	var decoded map[string]string
	if err := json.Unmarshal(payload, &decoded); err != nil {
		t.Fatalf("decode: %v", err)
	}
	if decoded["session_id"] != "sess-42" {
		t.Fatalf("session_id = %q, want sess-42", decoded["session_id"])
	}
}

func TestControlActionTargetPayloadKeepsOtherActionsUntouched(t *testing.T) {
	payload, err := controlActionTargetPayload("pause", "sess-42", []byte(`{"reason":"x"}`))
	if err != nil {
		t.Fatalf("inject: %v", err)
	}
	if string(payload) != `{"reason":"x"}` {
		t.Fatalf("payload = %s, want it unchanged", payload)
	}
}

func TestControlActionTargetPayloadRejectsMismatchedSessionID(t *testing.T) {
	// Honouring a supplied value would bypass the target the Endpoint just
	// revalidated, so a disagreement is a definite failure.
	_, err := controlActionTargetPayload("get_session_messages", "sess-42", []byte(`{"session_id":"other"}`))
	if err == nil {
		t.Fatal("a mismatched session_id was accepted")
	}
	if !strings.Contains(err.Error(), "does not match the selected session") {
		t.Fatalf("error = %v, want it to name the mismatch", err)
	}
}

func TestControlActionTargetPayloadAcceptsMatchingSessionID(t *testing.T) {
	payload, err := controlActionTargetPayload("get_session_messages", "sess-42", []byte(`{"session_id":"sess-42"}`))
	if err != nil {
		t.Fatalf("inject: %v", err)
	}
	var decoded map[string]string
	if err := json.Unmarshal(payload, &decoded); err != nil {
		t.Fatalf("decode: %v", err)
	}
	if decoded["session_id"] != "sess-42" {
		t.Fatalf("session_id = %q, want sess-42", decoded["session_id"])
	}
}

func TestControlActionTargetPayloadRequiresResolvedSession(t *testing.T) {
	if _, err := controlActionTargetPayload("get_session_messages", "", []byte(`{}`)); err == nil {
		t.Fatal("an empty provider key was accepted")
	}
}

func TestControlActionArgsInjectSessionIDForGetSessionMessages(t *testing.T) {
	args, err := controlActionArgs(nil, security.ProviderControlPrefix+"get_session_messages", "sess-42", nil)
	if err != nil {
		t.Fatalf("args: %v", err)
	}
	joined := strings.Join(args, " ")
	if !strings.Contains(joined, `"session_id":"sess-42"`) {
		t.Fatalf("args = %v, want the injected session_id", args)
	}
}
