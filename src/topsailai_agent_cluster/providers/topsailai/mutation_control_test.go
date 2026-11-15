package main

import (
	"context"
	"encoding/json"
	"os"
	"path/filepath"
	"reflect"
	"strings"
	"testing"
	"time"
)

// controlProvider builds a Provider with one loaded control catalog.
func controlProvider(t *testing.T, runner commandRunner, catalog controlCatalog) *provider {
	t.Helper()
	return &provider{runner: runner, now: func() time.Time { return time.UnixMilli(1700000000123) }, control: catalog}
}

// writeCatalog writes one catalog document into a temporary directory.
func writeCatalog(t *testing.T, document string) string {
	t.Helper()
	path := filepath.Join(t.TempDir(), "control-actions.json")
	if err := os.WriteFile(path, []byte(document), 0o600); err != nil {
		t.Fatalf("write catalog: %v", err)
	}
	return path
}

// TestControlCatalogIsDisabledWithoutConfiguration proves the fail-closed default.
//
// An unconfigured deployment advertises no action and refuses every ctl. operation,
// so the executable cannot be talked into running an action nobody configured.
func TestControlCatalogIsDisabledWithoutConfiguration(t *testing.T) {
	catalog, err := loadControlCatalog(nil)
	if err != nil {
		t.Fatalf("load catalog: %v", err)
	}
	if len(catalog.contracts()) != 0 {
		t.Fatalf("contracts=%v", catalog.contracts())
	}
	runner := &scriptedRunner{t: t, answers: map[string][]runnerAnswer{authorityCall: answer(liveWorkspaceDocument("7"))}}
	got := controlProvider(t, runner, catalog).dispatch(context.Background(), mutationRequest("ctl.heartbeat", liveSessionTarget(t, "7"), `{}`))
	if got.OK || got.Error == nil || got.Error.Code != "unsupported" {
		t.Fatalf("response=%+v", got)
	}
	if len(runner.calls) != 1 {
		t.Fatalf("calls=%v", runner.calls)
	}
}

// TestControlCatalogExpandsConfiguredTemplate proves a configured action runs its
// own argv with the revalidated session substituted per token.
func TestControlCatalogExpandsConfiguredTemplate(t *testing.T) {
	path := writeCatalog(t, `{"actions":[{"name":"heartbeat","command":["runtime","control","heartbeat","-s","{session}","--json"]}]}`)
	catalog, err := loadControlCatalog([]string{controlActionsEnvironment + "=" + path})
	if err != nil {
		t.Fatalf("load catalog: %v", err)
	}
	// The contract also declares what the action is, because the provider that
	// implements it is the source of its target kinds and safety class.
	wantContract := namedContract{
		Name:        "ctl.heartbeat",
		Version:     operationVersion,
		TargetKinds: []string{"session"},
		SafetyClass: "mutating",
	}
	if got := catalog.contracts(); !reflect.DeepEqual(got, []namedContract{wantContract}) {
		t.Fatalf("contracts=%v", got)
	}
	session := liveSessionTarget(t, "7")
	want := []string{"runtime", "control", "heartbeat", "-s", "s-1", "--json"}
	runner := &scriptedRunner{t: t, answers: map[string][]runnerAnswer{
		authorityCall:              answer(liveWorkspaceDocument("7")),
		strings.Join(want, "\x00"): answer(`{"ok":true}`),
	}}
	got := controlProvider(t, runner, catalog).dispatch(context.Background(), mutationRequest("ctl.heartbeat", session, `{}`))
	if !got.OK || got.Result == nil {
		t.Fatalf("response=%+v", got)
	}
	if last := runner.calls[len(runner.calls)-1].args; !reflect.DeepEqual(last, want) {
		t.Fatalf("argv=%v want %v", last, want)
	}
}

// TestControlCatalogInjectsTargetSelector proves the payload selector is filled from
// the revalidated target and a disagreeing value is rejected.
func TestControlCatalogInjectsTargetSelector(t *testing.T) {
	path := writeCatalog(t, `{"actions":[{"name":"inspect","command":["runtime","control","inspect","-a","{payload}","--json"],"payload_session_field":"session"}]}`)
	catalog, err := loadControlCatalog([]string{controlActionsEnvironment + "=" + path})
	if err != nil {
		t.Fatalf("load catalog: %v", err)
	}
	session := liveSessionTarget(t, "7")
	want := []string{"runtime", "control", "inspect", "-a", `{"session":"s-1"}`, "--json"}
	runner := &scriptedRunner{t: t, answers: map[string][]runnerAnswer{
		authorityCall:              answer(liveWorkspaceDocument("7")),
		strings.Join(want, "\x00"): answer(`{"ok":true}`),
	}}
	got := controlProvider(t, runner, catalog).dispatch(context.Background(), mutationRequest("ctl.inspect", session, `{}`))
	if !got.OK || got.Result == nil {
		t.Fatalf("response=%+v", got)
	}
	if last := runner.calls[len(runner.calls)-1].args; !reflect.DeepEqual(last, want) {
		t.Fatalf("argv=%v want %v", last, want)
	}
	conflicting := &scriptedRunner{t: t, answers: map[string][]runnerAnswer{authorityCall: answer(liveWorkspaceDocument("7"))}}
	got = controlProvider(t, conflicting, catalog).dispatch(context.Background(), mutationRequest("ctl.inspect", session, `{"session":"other"}`))
	if got.OK || got.Error == nil || got.Error.Code != "invalid_request" {
		t.Fatalf("response=%+v", got)
	}
	if len(conflicting.calls) != 1 {
		t.Fatalf("calls=%v", conflicting.calls)
	}
}

// TestControlCatalogRejectsInvalidConfiguration proves a broken catalog fails at load
// time instead of at the first command.
func TestControlCatalogRejectsInvalidConfiguration(t *testing.T) {
	tests := map[string]string{
		"duplicate action":     `{"actions":[{"name":"a","command":["x"]},{"name":"a","command":["y"]}]}`,
		"empty command":        `{"actions":[{"name":"a","command":[]}]}`,
		"empty token":          `{"actions":[{"name":"a","command":["x",""]}]}`,
		"unknown placeholder":  `{"actions":[{"name":"a","command":["x","{other}"]}]}`,
		"unterminated":         `{"actions":[{"name":"a","command":["x","{session"]}]}`,
		"repeated placeholder": `{"actions":[{"name":"a","command":["x","{session}{session}"]}]}`,
		"missing name":         `{"actions":[{"command":["x"]}]}`,
		"unknown field":        `{"actions":[{"name":"a","command":["x"],"executable":"/bin/sh"}]}`,
		"extra document":       `{"actions":[]} {}`,
	}
	for name, document := range tests {
		t.Run(name, func(t *testing.T) {
			path := writeCatalog(t, document)
			if _, err := loadControlCatalog([]string{controlActionsEnvironment + "=" + path}); err == nil {
				t.Fatal("invalid catalog was accepted")
			}
		})
	}
	if _, err := loadControlCatalog([]string{controlActionsEnvironment + "=/nonexistent/catalog.json"}); err == nil {
		t.Fatal("unreadable catalog was accepted")
	}
}

// TestControlCatalogRejectsUnknownAction proves an unconfigured action never reaches
// the provider even when a caller submits it directly.
func TestControlCatalogRejectsUnknownAction(t *testing.T) {
	path := writeCatalog(t, `{"actions":[{"name":"heartbeat","command":["runtime","control","heartbeat","-s","{session}","--json"]}]}`)
	catalog, err := loadControlCatalog([]string{controlActionsEnvironment + "=" + path})
	if err != nil {
		t.Fatalf("load catalog: %v", err)
	}
	runner := &scriptedRunner{t: t, answers: map[string][]runnerAnswer{authorityCall: answer(liveWorkspaceDocument("7"))}}
	got := controlProvider(t, runner, catalog).dispatch(context.Background(), mutationRequest("ctl.unknown", liveSessionTarget(t, "7"), `{}`))
	if got.OK || got.Error == nil || got.Error.Code != "unsupported" {
		t.Fatalf("response=%+v", got)
	}
	if len(runner.calls) != 1 {
		t.Fatalf("calls=%v", runner.calls)
	}
}

// TestControlCatalogRequiresLiveGeneration proves a ctl. operation is a live mutation
// and therefore needs target evidence like any other live operation.
func TestControlCatalogRequiresLiveGeneration(t *testing.T) {
	path := writeCatalog(t, `{"actions":[{"name":"heartbeat","command":["runtime","control","heartbeat","-s","{session}","--json"]}]}`)
	catalog, err := loadControlCatalog([]string{controlActionsEnvironment + "=" + path})
	if err != nil {
		t.Fatalf("load catalog: %v", err)
	}
	runner := &scriptedRunner{t: t, answers: map[string][]runnerAnswer{}}
	got := controlProvider(t, runner, catalog).dispatch(context.Background(), mutationRequest("ctl.heartbeat", sessionTarget(t), `{}`))
	if got.OK || got.Error == nil || got.Error.Code != "invalid_request" {
		t.Fatalf("response=%+v", got)
	}
	if len(runner.calls) != 0 {
		t.Fatalf("calls=%v", runner.calls)
	}
}

// TestControlCatalogRejectsNonObjectPayload proves the forwarded payload is always one
// JSON object, so the provider never reinterprets an operator document.
func TestControlCatalogRejectsNonObjectPayload(t *testing.T) {
	path := writeCatalog(t, `{"actions":[{"name":"heartbeat","command":["runtime","control","heartbeat","-a","{payload}","--json"]}]}`)
	catalog, err := loadControlCatalog([]string{controlActionsEnvironment + "=" + path})
	if err != nil {
		t.Fatalf("load catalog: %v", err)
	}
	for name, payload := range map[string]string{"array": `[]`, "string": `"x"`, "null": `null`} {
		t.Run(name, func(t *testing.T) {
			runner := &scriptedRunner{t: t, answers: map[string][]runnerAnswer{authorityCall: answer(liveWorkspaceDocument("7"))}}
			got := controlProvider(t, runner, catalog).dispatch(context.Background(), mutationRequest("ctl.heartbeat", liveSessionTarget(t, "7"), payload))
			if got.OK || got.Error == nil || got.Error.Code != "invalid_request" {
				t.Fatalf("response=%+v", got)
			}
			if len(runner.calls) != 1 {
				t.Fatalf("calls=%v", runner.calls)
			}
		})
	}
}

// TestControlCatalogConstantsAreEnforced proves an action that fixes a payload field
// cannot be reached with a different value.
func TestControlCatalogConstantsAreEnforced(t *testing.T) {
	path := writeCatalog(t, `{"actions":[{"name":"models","command":["runtime","control","call_instruction","-s","{session}","-a","{payload}","--json"],"payload_constants":{"instruction":"agent.models"}}]}`)
	catalog, err := loadControlCatalog([]string{controlActionsEnvironment + "=" + path})
	if err != nil {
		t.Fatalf("load catalog: %v", err)
	}
	session := liveSessionTarget(t, "7")
	want := []string{"runtime", "control", "call_instruction", "-s", "s-1", "-a", `{"args":["fast"],"instruction":"agent.models"}`, "--json"}
	runner := &scriptedRunner{t: t, answers: map[string][]runnerAnswer{
		authorityCall:              answer(liveWorkspaceDocument("7")),
		strings.Join(want, "\x00"): answer(`{"ok":true}`),
	}}
	got := controlProvider(t, runner, catalog).dispatch(context.Background(), mutationRequest("ctl.models", session, `{"args":["fast"]}`))
	if !got.OK || got.Result == nil {
		t.Fatalf("response=%+v", got)
	}
	if last := runner.calls[len(runner.calls)-1].args; !reflect.DeepEqual(last, want) {
		t.Fatalf("argv=%v want %v", last, want)
	}
	conflicting := &scriptedRunner{t: t, answers: map[string][]runnerAnswer{authorityCall: answer(liveWorkspaceDocument("7"))}}
	got = controlProvider(t, conflicting, catalog).dispatch(context.Background(), mutationRequest("ctl.models", session, `{"instruction":"other"}`))
	if got.OK || got.Error == nil || got.Error.Code != "invalid_request" {
		t.Fatalf("response=%+v", got)
	}
	if len(conflicting.calls) != 1 {
		t.Fatalf("calls=%v", conflicting.calls)
	}
}

// TestControlCatalogPublishesTheConfiguredPayloadSchema proves the advertised
// contract carries the schema the interactive prompt follows.
//
// The prompt walks the advertised payload_schema to ask for named fields. A catalog
// that accepted a schema but never published it would leave every action on the
// generic parameter prompt, so the field has to survive the whole path from the
// document to the descriptor.
func TestControlCatalogPublishesTheConfiguredPayloadSchema(t *testing.T) {
	path := writeCatalog(t, `{"actions":[{"name":"models","command":["runtime","control","models","-s","{session}","--json"],"payload_schema":{"type":"object","properties":{"instruction":{"type":"string"}}}}]}`)
	catalog, err := loadControlCatalog([]string{controlActionsEnvironment + "=" + path})
	if err != nil {
		t.Fatalf("load catalog: %v", err)
	}
	got := catalog.contracts()
	if len(got) != 1 {
		t.Fatalf("contracts=%v", got)
	}
	want := `{"properties":{"instruction":{"type":"string"}},"type":"object"}`
	if got[0].PayloadSchema != want {
		t.Fatalf("payload schema=%q want %q", got[0].PayloadSchema, want)
	}
}

// TestControlCatalogRejectsANonObjectPayloadSchema proves a schema the prompt cannot
// walk is refused at load time.
//
// The prompt asks for named fields, so a scalar or array document describes nothing
// it can render. Accepting one would advertise a capability whose guided prompt is
// silently empty, which looks like an action with no parameters.
func TestControlCatalogRejectsANonObjectPayloadSchema(t *testing.T) {
	for _, document := range []string{
		`{"actions":[{"name":"models","command":["runtime","control","models"],"payload_schema":["type","object"]}]}`,
		`{"actions":[{"name":"models","command":["runtime","control","models"],"payload_schema":"object"}]}`,
	} {
		path := writeCatalog(t, document)
		if _, err := loadControlCatalog([]string{controlActionsEnvironment + "=" + path}); err == nil {
			t.Fatalf("load catalog accepted a non-object payload schema: %s", document)
		}
	}
}

// TestControlCatalogAllowsAnAbsentPayloadSchema proves a minimal catalog still works.
//
// An action that takes no documented parameters must not be forced to invent a
// schema, because an empty schema and an absent one both fall back to the generic
// parameter prompt.
func TestControlCatalogAllowsAnAbsentPayloadSchema(t *testing.T) {
	path := writeCatalog(t, `{"actions":[{"name":"heartbeat","command":["runtime","control","heartbeat","-s","{session}","--json"]}]}`)
	catalog, err := loadControlCatalog([]string{controlActionsEnvironment + "=" + path})
	if err != nil {
		t.Fatalf("load catalog: %v", err)
	}
	got := catalog.contracts()
	if len(got) != 1 || got[0].PayloadSchema != "" {
		t.Fatalf("contracts=%v", got)
	}
}

// TestControlCatalogAdvertisesOnlyConfiguredActions proves the descriptor reports the
// catalog rather than a compiled-in list.
func TestControlCatalogAdvertisesOnlyConfiguredActions(t *testing.T) {
	path := writeCatalog(t, `{"actions":[{"name":"heartbeat","command":["runtime","control","heartbeat","-s","{session}","--json"]},{"name":"models","command":["runtime","control","models","-s","{session}","--json"]}]}`)
	catalog, err := loadControlCatalog([]string{controlActionsEnvironment + "=" + path})
	if err != nil {
		t.Fatalf("load catalog: %v", err)
	}
	got := topsailaiDescriptor(catalog, supportedPlatform)
	want := []namedContract{
		{Name: "ctl.heartbeat", Version: operationVersion, TargetKinds: []string{"session"}, SafetyClass: "mutating"},
		{Name: "ctl.models", Version: operationVersion, TargetKinds: []string{"session"}, SafetyClass: "mutating"},
	}
	if !reflect.DeepEqual(got.ControlActions, want) {
		t.Fatalf("control actions=%v want %v", got.ControlActions, want)
	}
	document, err := json.Marshal(got)
	if err != nil {
		t.Fatal(err)
	}
	if strings.Contains(string(document), "executable") {
		t.Fatalf("descriptor leaked a command template: %s", document)
	}
}
