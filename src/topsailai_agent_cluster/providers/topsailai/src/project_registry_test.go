package main

import (
	"context"
	"crypto/sha256"
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"reflect"
	"strings"
	"testing"
	"time"
)

// projectProvider returns a provider confined to one resolved project root.
//
// The root is resolved here exactly as startup resolves it, so a test exercises the
// same value the confinement decision compares against.
func projectProvider(r commandRunner, root string) *provider {
	return &provider{
		runner:      r,
		now:         func() time.Time { return time.UnixMilli(1700000000123) },
		platform:    supportedPlatform,
		projectRoot: root,
	}
}

// projectAddRequest builds one target-less project.add execute request.
func projectAddRequest(payload string) request {
	value := validRequest(functionExecute)
	value.InvocationID = "invocation-1"
	value.Operation = &namedContract{Name: operationProjectAdd, Version: operationVersion}
	value.Target = nil
	value.Payload = json.RawMessage(payload)
	return value
}

// projectRemoveRequest builds one project.remove execute request addressing a
// registry entry through the opaque provider_target slot.
//
// The addressed key is derived from the folder exactly as the catalog derives it,
// because the Provider binds the caller's slot to that key before building argv.
// A hardcoded key would make every removal test fail the binding check instead of
// exercising the behaviour it names.
func projectRemoveRequest(slot, folder string) request {
	value := validRequest(functionExecute)
	value.InvocationID = "invocation-1"
	value.Operation = &namedContract{Name: operationProjectRemove, Version: operationVersion}
	value.Target = &target{ResourceKind: resourceProject, ProviderResourceKey: projectResourceKey(folder), ProviderTarget: slot}
	value.Payload = json.RawMessage(`{}`)
	return value
}

// projectResourceKey mirrors the catalog's provider key for one folder.
func projectResourceKey(folder string) string {
	digest := sha256.Sum256([]byte(folder))
	return fmt.Sprintf("project:v1:%x", digest)
}

// TestResolveProjectRootRequiresAnExistingAbsoluteDirectory proves an unusable
// configuration disables registration instead of falling back to a default.
func TestResolveProjectRootRequiresAnExistingAbsoluteDirectory(t *testing.T) {
	directory := t.TempDir()
	file := filepath.Join(directory, "file.txt")
	if err := os.WriteFile(file, []byte("x"), 0o600); err != nil {
		t.Fatalf("write file: %v", err)
	}
	cases := []struct {
		name     string
		value    string
		wantSame bool
	}{
		{name: "unset", value: ""},
		{name: "relative", value: "relative/path"},
		{name: "missing", value: filepath.Join(directory, "absent")},
		{name: "file", value: file},
		{name: "directory", value: directory, wantSame: true},
	}
	for _, testCase := range cases {
		t.Run(testCase.name, func(t *testing.T) {
			environment := []string{}
			if testCase.value != "" {
				environment = []string{projectRootEnvironment + "=" + testCase.value}
			}
			got := resolveProjectRoot(environment)
			if testCase.wantSame {
				if got == "" {
					t.Fatalf("resolveProjectRoot(%q) = empty, want a resolved directory", testCase.value)
				}
				return
			}
			if got != "" {
				t.Fatalf("resolveProjectRoot(%q) = %q, want empty", testCase.value, got)
			}
		})
	}
}

// TestProjectAddRefusesWithoutAConfiguredRoot proves the fail-closed default.
//
// An unconfigured root must refuse before any provider process starts, because a
// default directory would silently grant a remote caller the right to register
// folders nobody approved.
func TestProjectAddRefusesWithoutAConfiguredRoot(t *testing.T) {
	runner := &scriptedRunner{t: t, answers: map[string][]runnerAnswer{}}
	got := projectProvider(runner, "").dispatch(context.Background(), projectAddRequest(`{"folder":"/tmp"}`))
	if got.OK || got.Error == nil {
		t.Fatalf("response = %+v", got)
	}
	if got.Error.Code != "project_root_unconfigured" {
		t.Fatalf("code = %q want project_root_unconfigured", got.Error.Code)
	}
	if len(runner.calls) != 0 {
		t.Fatalf("calls = %v, want none", runner.calls)
	}
}

// TestProjectAddConfinesTheResolvedFolderToTheRoot proves every escape shape is
// refused by the same comparison.
//
// The decision is made on the resolved path, so a parent traversal, an absolute
// path outside the root and a symlink that points outside the root are all refused
// even though the text the operator typed looks different in each case.
func TestProjectAddConfinesTheResolvedFolderToTheRoot(t *testing.T) {
	root := t.TempDir()
	inside := filepath.Join(root, "project")
	if err := os.Mkdir(inside, 0o750); err != nil {
		t.Fatalf("mkdir: %v", err)
	}
	outside := t.TempDir()
	link := filepath.Join(root, "escape")
	if err := os.Symlink(outside, link); err != nil {
		t.Fatalf("symlink: %v", err)
	}
	file := filepath.Join(root, "file.txt")
	if err := os.WriteFile(file, []byte("x"), 0o600); err != nil {
		t.Fatalf("write file: %v", err)
	}

	refused := []struct {
		name string
		path string
		code string
	}{
		{name: "outside", path: outside, code: "project_path_outside_root"},
		{name: "parent traversal", path: filepath.Join(root, "..", filepath.Base(outside)), code: "project_path_outside_root"},
		{name: "symlink escape", path: link, code: "project_path_outside_root"},
		{name: "missing", path: filepath.Join(root, "absent"), code: "project_path_not_directory"},
		{name: "file", path: file, code: "project_path_not_directory"},
	}
	for _, testCase := range refused {
		t.Run(testCase.name, func(t *testing.T) {
			runner := &scriptedRunner{t: t, answers: map[string][]runnerAnswer{}}
			payload, err := json.Marshal(projectAddPayload{Folder: testCase.path})
			if err != nil {
				t.Fatalf("marshal payload: %v", err)
			}
			got := projectProvider(runner, root).dispatch(context.Background(), projectAddRequest(string(payload)))
			if got.OK || got.Error == nil {
				t.Fatalf("response = %+v", got)
			}
			if got.Error.Code != testCase.code {
				t.Fatalf("code = %q want %q", got.Error.Code, testCase.code)
			}
			if len(runner.calls) != 0 {
				t.Fatalf("calls = %v, want none", runner.calls)
			}
		})
	}

	t.Run("inside", func(t *testing.T) {
		runner := &scriptedRunner{t: t, answers: map[string][]runnerAnswer{
			"project\x00add\x00" + inside: answer(""),
		}}
		payload, err := json.Marshal(projectAddPayload{Folder: inside})
		if err != nil {
			t.Fatalf("marshal payload: %v", err)
		}
		got := projectProvider(runner, root).dispatch(context.Background(), projectAddRequest(string(payload)))
		if !got.OK {
			t.Fatalf("response = %+v", got)
		}
		if len(runner.calls) != 1 {
			t.Fatalf("calls = %v, want one", runner.calls)
		}
		want := []string{"project", "add", inside}
		if !reflect.DeepEqual(runner.calls[0].args, want) {
			t.Fatalf("argv = %v want %v", runner.calls[0].args, want)
		}
	})
}

// TestProjectAddPassesTheOptionalNameAsOneArgvElement proves the label reaches the
// provider without a shell and without being parsed as an option.
func TestProjectAddPassesTheOptionalNameAsOneArgvElement(t *testing.T) {
	root := t.TempDir()
	inside := filepath.Join(root, "project")
	if err := os.Mkdir(inside, 0o750); err != nil {
		t.Fatalf("mkdir: %v", err)
	}
	runner := &scriptedRunner{t: t, answers: map[string][]runnerAnswer{
		"project\x00add\x00" + inside + "\x00demo": answer(""),
	}}
	payload, err := json.Marshal(projectAddPayload{Folder: inside, Name: "demo"})
	if err != nil {
		t.Fatalf("marshal payload: %v", err)
	}
	got := projectProvider(runner, root).dispatch(context.Background(), projectAddRequest(string(payload)))
	if !got.OK {
		t.Fatalf("response = %+v", got)
	}
	want := []string{"project", "add", inside, "demo"}
	if !reflect.DeepEqual(runner.calls[0].args, want) {
		t.Fatalf("argv = %v want %v", runner.calls[0].args, want)
	}
}

// TestProjectRemoveAddressesTheExactProviderTarget proves removal never scans the
// registry to recover a path the caller already held.
func TestProjectRemoveAddressesTheExactProviderTarget(t *testing.T) {
	root := t.TempDir()
	inside := filepath.Join(root, "project")
	if err := os.Mkdir(inside, 0o750); err != nil {
		t.Fatalf("mkdir: %v", err)
	}
	slot, err := json.Marshal(projectTargetSlot{ProjectPath: inside})
	if err != nil {
		t.Fatalf("marshal slot: %v", err)
	}
	runner := &scriptedRunner{t: t, answers: map[string][]runnerAnswer{
		"project\x00del\x00" + inside: answer(""),
	}}
	got := projectProvider(runner, root).dispatch(context.Background(), projectRemoveRequest(string(slot), inside))
	if !got.OK {
		t.Fatalf("response = %+v", got)
	}
	want := []string{"project", "del", inside}
	if !reflect.DeepEqual(runner.calls[0].args, want) {
		t.Fatalf("argv = %v want %v", runner.calls[0].args, want)
	}
}

// TestProjectRemoveLeavesTheFolderOnDisk proves removal edits the registry only.
//
// The operation exists to change configuration, so the folder and its contents must
// survive. The argv is asserted exactly, because a flag that deletes data would be the
// only way this Provider could destroy a project, and an exact comparison refuses any
// such flag instead of trusting that none was added.
func TestProjectRemoveLeavesTheFolderOnDisk(t *testing.T) {
	root := t.TempDir()
	inside := filepath.Join(root, "project")
	if err := os.Mkdir(inside, 0o750); err != nil {
		t.Fatalf("mkdir: %v", err)
	}
	marker := filepath.Join(inside, "keep.txt")
	if err := os.WriteFile(marker, []byte("project data"), 0o600); err != nil {
		t.Fatalf("write marker: %v", err)
	}
	slot, err := json.Marshal(projectTargetSlot{ProjectPath: inside})
	if err != nil {
		t.Fatalf("marshal slot: %v", err)
	}
	runner := &scriptedRunner{t: t, answers: map[string][]runnerAnswer{
		"project\x00del\x00" + inside: answer(""),
	}}
	got := projectProvider(runner, root).dispatch(context.Background(), projectRemoveRequest(string(slot), inside))
	if !got.OK {
		t.Fatalf("response = %+v", got)
	}
	want := []string{"project", "del", inside}
	if !reflect.DeepEqual(runner.calls[0].args, want) {
		t.Fatalf("argv = %v want %v; removal must not carry a flag that deletes data", runner.calls[0].args, want)
	}
	if _, err := os.Stat(inside); err != nil {
		t.Fatalf("folder was removed: %v", err)
	}
	content, err := os.ReadFile(marker)
	if err != nil {
		t.Fatalf("read marker: %v", err)
	}
	if string(content) != "project data" {
		t.Fatalf("marker content = %q", content)
	}
}

// TestProjectRemoveRefusesAnAbsentOrEscapingTarget proves removal fails closed.
//
// An absent slot is refused rather than resolved by scanning, and a path outside the
// configured root is refused because the operation exists to manage the folders this
// Endpoint approved.
func TestProjectRemoveRefusesAnAbsentOrEscapingTarget(t *testing.T) {
	root := t.TempDir()
	outside := t.TempDir()
	inside := filepath.Join(root, "inside")
	if err := os.MkdirAll(inside, 0o755); err != nil {
		t.Fatalf("create inside: %v", err)
	}
	outsideSlot, err := json.Marshal(projectTargetSlot{ProjectPath: outside})
	if err != nil {
		t.Fatalf("marshal slot: %v", err)
	}
	insideSlot, err := json.Marshal(projectTargetSlot{ProjectPath: inside})
	if err != nil {
		t.Fatalf("marshal slot: %v", err)
	}
	cases := []struct {
		name   string
		slot   string
		folder string
		code   string
	}{
		{name: "absent", slot: "", folder: outside, code: "invalid_request"},
		{name: "empty document", slot: `{}`, folder: outside, code: "invalid_request"},
		{name: "outside root", slot: string(outsideSlot), folder: outside, code: "project_path_outside_root"},
		// The slot names a folder inside the root while the addressed key belongs to
		// a different folder. Confinement passes, so only the binding check can
		// refuse this, which is what makes the case prove the binding rather than
		// the root rule.
		{name: "key mismatch", slot: string(insideSlot), folder: outside, code: "invalid_request"},
	}
	for _, testCase := range cases {
		t.Run(testCase.name, func(t *testing.T) {
			runner := &scriptedRunner{t: t, answers: map[string][]runnerAnswer{}}
			got := projectProvider(runner, root).dispatch(context.Background(), projectRemoveRequest(testCase.slot, testCase.folder))
			if got.OK || got.Error == nil {
				t.Fatalf("response = %+v", got)
			}
			if got.Error.Code != testCase.code {
				t.Fatalf("code = %q want %q", got.Error.Code, testCase.code)
			}
			if len(runner.calls) != 0 {
				t.Fatalf("calls = %v, want none", runner.calls)
			}
		})
	}
}

// TestProjectAddIsTheOnlyTargetlessMutation proves the exception is named rather
// than general.
//
// Every other execute still requires a target, so a missing target remains a defect
// the Provider reports instead of a form it accepts.
func TestProjectAddIsTheOnlyTargetlessMutation(t *testing.T) {
	runner := &scriptedRunner{t: t, answers: map[string][]runnerAnswer{}}
	value := validRequest(functionExecute)
	value.InvocationID = "invocation-1"
	value.Operation = &namedContract{Name: operationMessageSend, Version: operationVersion}
	value.Target = nil
	value.Payload = json.RawMessage(`{"text":"hello"}`)
	got := projectProvider(runner, t.TempDir()).dispatch(context.Background(), value)
	if got.OK || got.Error == nil {
		t.Fatalf("response = %+v", got)
	}
	if got.Error.Code != "invalid_request" {
		t.Fatalf("code = %q want invalid_request", got.Error.Code)
	}
	if len(runner.calls) != 0 {
		t.Fatalf("calls = %v, want none", runner.calls)
	}
}

// TestProjectRemoveDoesNotRequireAGeneration proves removal addresses a registry
// entry rather than a live process.
func TestProjectRemoveDoesNotRequireAGeneration(t *testing.T) {
	if operationNeedsLiveGeneration(operationProjectRemove) {
		t.Fatal("project.remove must not require a live generation")
	}
	if !operationNeedsLiveGeneration(operationMessageSend) {
		t.Fatal("message.send must require a live generation")
	}
}

// TestDecodeProjectTargetRejectsAnOversizedSlot proves the opaque slot stays bounded.
func TestDecodeProjectTargetRejectsAnOversizedSlot(t *testing.T) {
	oversized := `{"project_path":"` + strings.Repeat("a", maxProviderTargetBytes) + `"}`
	if _, err := decodeProjectTarget(oversized); err == nil {
		t.Fatal("oversized provider_target must be refused")
	} else if !errors.Is(err, errInvalidRequest) {
		t.Fatalf("error = %v want invalid request", err)
	}
}
