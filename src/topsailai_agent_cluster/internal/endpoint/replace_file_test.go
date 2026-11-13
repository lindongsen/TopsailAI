package endpoint

import (
	"context"
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"syscall"
	"testing"
	"time"
)

// writeReplaceRequest writes one request document into dir.
func writeReplaceRequest(t *testing.T, dir string, request ReplaceFileRequest) string {
	t.Helper()
	path := filepath.Join(dir, "replace-request.json")
	data, err := json.Marshal(request)
	if err != nil {
		t.Fatalf("encode request: %v", err)
	}
	if err := os.WriteFile(path, data, 0o644); err != nil {
		t.Fatalf("write request: %v", err)
	}
	return path
}

// readReplaceResult reads the answer document beside the request.
func readReplaceResult(t *testing.T, dir string) ReplaceFileResult {
	t.Helper()
	data, err := os.ReadFile(filepath.Join(dir, replaceResultFileName))
	if err != nil {
		t.Fatalf("read result: %v", err)
	}
	var result ReplaceFileResult
	if err := json.Unmarshal(data, &result); err != nil {
		t.Fatalf("decode result: %v", err)
	}
	return result
}

// TestReplaceFileIgnoresMissingRequest proves an unrelated reload signal is not an
// error. SIGHUP is shared with the allowlist, the catalog and the access policy, so
// most signals arrive with no activation pending.
func TestReplaceFileIgnoresMissingRequest(t *testing.T) {
	dir := t.TempDir()
	fixture := newReplaceTestFixture(t)
	fixture.configure(t, "a", "/opt/prev", nil)
	file := &ReplaceFile{Path: filepath.Join(dir, "replace-request.json"), Replacer: &Replacer{Registry: fixture.registry, Publisher: &replaceTestPublisher{}}}

	result, err := file.Process(context.Background())
	if err != nil {
		t.Fatalf("missing request was reported as an error: %v", err)
	}
	if result != nil {
		t.Fatalf("missing request produced a result: %#v", result)
	}
	if _, err := os.Stat(file.ResultPath()); !os.IsNotExist(err) {
		t.Fatalf("missing request wrote a result document: %v", err)
	}
}

// TestReplaceFileConsumesRequest proves the request document is removed once read,
// so a later unrelated reload cannot replay an activation the operator asked for
// once.
func TestReplaceFileConsumesRequest(t *testing.T) {
	dir := t.TempDir()
	fixture := newReplaceTestFixture(t)
	fixture.configure(t, "a", "/opt/prev", nil)
	path := writeReplaceRequest(t, dir, ReplaceFileRequest{RequestID: "req-1", AdapterID: "a", Executable: candidateFile(t, "next", 0o755, "x")})
	var consumed []string
	file := &ReplaceFile{Path: path, Replacer: &Replacer{Registry: fixture.registry, Publisher: &replaceTestPublisher{}}, LogConsumed: func(path string) { consumed = append(consumed, path) }}

	if _, err := file.Process(context.Background()); err != nil {
		t.Fatalf("activation failed: %v", err)
	}
	if _, err := os.Stat(path); !os.IsNotExist(err) {
		t.Fatalf("request document survived consumption: %v", err)
	}
	if len(consumed) != 1 || consumed[0] != path {
		t.Fatalf("consumption was not logged: %#v", consumed)
	}
	// A second signal must not replay the activation.
	result, err := file.Process(context.Background())
	if err != nil || result != nil {
		t.Fatalf("consumed request was replayed: result=%#v err=%v", result, err)
	}
}

// TestReplaceFileReportsActivation proves a successful activation is answered with
// the effective version, so the controller can report what is now serving.
func TestReplaceFileReportsActivation(t *testing.T) {
	dir := t.TempDir()
	fixture := newReplaceTestFixture(t)
	fixture.configure(t, "a", "/opt/prev", nil)
	path := writeReplaceRequest(t, dir, ReplaceFileRequest{RequestID: "req-2", AdapterID: "a", Executable: candidateFile(t, "next", 0o755, "x")})
	file := &ReplaceFile{Path: path, Replacer: &Replacer{Registry: fixture.registry, Publisher: &replaceTestPublisher{}}}

	result, err := file.Process(context.Background())
	if err != nil {
		t.Fatalf("activation failed: %v", err)
	}
	if result == nil || !result.OK {
		t.Fatalf("activation was not reported as successful: %#v", result)
	}
	if result.RequestID != "req-2" {
		t.Fatalf("result is not correlated: %q", result.RequestID)
	}
	if result.Result.EffectiveVersion != "next" || result.Result.PreviousVersion != "prev" {
		t.Fatalf("result does not name both versions: %#v", result.Result)
	}
	stored := readReplaceResult(t, dir)
	if stored.RequestID != "req-2" || !stored.OK || stored.Result.EffectiveVersion != "next" {
		t.Fatalf("stored result does not match the returned one: %#v", stored)
	}
}

// TestReplaceFileReportsRejection proves a rejected activation is answered rather
// than left to a deadline, and that the previous version keeps serving.
func TestReplaceFileReportsRejection(t *testing.T) {
	dir := t.TempDir()
	fixture := newReplaceTestFixture(t)
	fixture.configure(t, "a", "/opt/prev", nil)
	path := writeReplaceRequest(t, dir, ReplaceFileRequest{RequestID: "req-3", AdapterID: "a", Executable: candidateFile(t, "bad-bootstrap", 0o755, "x")})
	file := &ReplaceFile{Path: path, Replacer: &Replacer{Registry: fixture.registry, Publisher: &replaceTestPublisher{}}}

	result, err := file.Process(context.Background())
	if err == nil {
		t.Fatal("rejected activation was reported as successful")
	}
	if result == nil || result.OK {
		t.Fatalf("rejection was not reported: %#v", result)
	}
	if !strings.Contains(result.Error, "bootstrap candidate") {
		t.Fatalf("rejection reason is not the bootstrap failure: %q", result.Error)
	}
	stored := readReplaceResult(t, dir)
	if stored.OK || stored.RequestID != "req-3" {
		t.Fatalf("stored result does not report the rejection: %#v", stored)
	}
	serving, ok := fixture.registry.Get("a")
	if !ok {
		t.Fatal("no adapter is serving after a rejected activation")
	}
	descriptor, err := serving.Describe(context.Background())
	if err != nil {
		t.Fatalf("describe serving adapter: %v", err)
	}
	if descriptor.Version != "prev" {
		t.Fatalf("serving version = %q, want prev", descriptor.Version)
	}
}

// TestReplaceFileRejectsRequestWithoutID proves an uncorrelatable request is
// refused instead of being executed with an answer nobody can match.
func TestReplaceFileRejectsRequestWithoutID(t *testing.T) {
	dir := t.TempDir()
	fixture := newReplaceTestFixture(t)
	fixture.configure(t, "a", "/opt/prev", nil)
	path := writeReplaceRequest(t, dir, ReplaceFileRequest{AdapterID: "a", Executable: candidateFile(t, "next", 0o755, "x")})
	file := &ReplaceFile{Path: path, Replacer: &Replacer{Registry: fixture.registry, Publisher: &replaceTestPublisher{}}}

	result, err := file.Process(context.Background())
	if err == nil || !strings.Contains(err.Error(), "has no request_id") {
		t.Fatalf("missing request ID was not reported: %v", err)
	}
	if result == nil || result.OK {
		t.Fatalf("uncorrelatable request produced a success: %#v", result)
	}
	if !strings.Contains(result.Error, "request_id is required") {
		t.Fatalf("result does not state the missing field: %q", result.Error)
	}
	// The activation must not have happened.
	serving, ok := fixture.registry.Get("a")
	if !ok {
		t.Fatal("no adapter is serving")
	}
	descriptor, err := serving.Describe(context.Background())
	if err != nil {
		t.Fatalf("describe serving adapter: %v", err)
	}
	if descriptor.Version != "prev" {
		t.Fatalf("serving version = %q, want prev", descriptor.Version)
	}
}

// TestReplaceFileRejectsMalformedRequest proves a malformed document is answered
// instead of silently ignored, so the controller does not wait for a deadline.
func TestReplaceFileRejectsMalformedRequest(t *testing.T) {
	dir := t.TempDir()
	fixture := newReplaceTestFixture(t)
	fixture.configure(t, "a", "/opt/prev", nil)
	path := filepath.Join(dir, "replace-request.json")
	if err := os.WriteFile(path, []byte("{not json"), 0o644); err != nil {
		t.Fatalf("write request: %v", err)
	}
	file := &ReplaceFile{Path: path, Replacer: &Replacer{Registry: fixture.registry, Publisher: &replaceTestPublisher{}}}

	result, err := file.Process(context.Background())
	if err == nil || !strings.Contains(err.Error(), "decode replace request") {
		t.Fatalf("malformed request was not reported: %v", err)
	}
	if result == nil || result.OK {
		t.Fatalf("malformed request produced a success: %#v", result)
	}
	stored := readReplaceResult(t, dir)
	if stored.OK || !strings.Contains(stored.Error, "decode replace request") {
		t.Fatalf("stored result does not report the decode failure: %#v", stored)
	}
}

// TestReplaceFileResultPathIsBesideRequest proves the answer location is derived
// from the request path, so the controller and the Endpoint cannot disagree.
func TestReplaceFileResultPathIsBesideRequest(t *testing.T) {
	file := &ReplaceFile{Path: "/opt/agent-cluster/conf/endpoint/replace-request.json"}
	if got := file.ResultPath(); got != "/opt/agent-cluster/conf/endpoint/replace-result.json" {
		t.Fatalf("result path = %q", got)
	}
	if got := (&ReplaceFile{}).ResultPath(); got != "" {
		t.Fatalf("empty path produced %q", got)
	}
}

// TestReplaceFileWatchReloadActivatesOnSignal proves the SIGHUP path actually
// reaches the replacer. Without this test the transport is only assumed: the
// handler registration, the callback and the stop semantics would all be
// unverified, and a signal that silently did nothing would look identical to a
// signal that was never sent.
func TestReplaceFileWatchReloadActivatesOnSignal(t *testing.T) {
	dir := t.TempDir()
	fixture := newReplaceTestFixture(t)
	fixture.configure(t, "a", "/opt/prev", nil)
	file := &ReplaceFile{
		Path:     filepath.Join(dir, "replace-request.json"),
		Replacer: &Replacer{Registry: fixture.registry, Publisher: &replaceTestPublisher{}},
	}
	writeReplaceRequest(t, dir, ReplaceFileRequest{
		RequestID:  "req-signal",
		AdapterID:  "a",
		Executable: candidateFile(t, "next", 0o755, "x"),
	})

	results := make(chan ReplaceFileResult, 1)
	stop, err := file.WatchReload(context.Background(), func(result ReplaceFileResult, processErr error) {
		if processErr != nil {
			t.Errorf("activation reported an error: %v", processErr)
		}
		results <- result
	})
	if err != nil {
		t.Fatalf("watch replace file: %v", err)
	}
	defer stop()

	if err := syscall.Kill(os.Getpid(), syscall.SIGHUP); err != nil {
		t.Fatalf("signal self: %v", err)
	}
	select {
	case result := <-results:
		if result.RequestID != "req-signal" {
			t.Fatalf("callback request ID = %q", result.RequestID)
		}
		if !result.OK {
			t.Fatalf("activation did not succeed: %#v", result)
		}
		if result.Result.EffectiveVersion != "next" {
			t.Fatalf("effective version = %q", result.Result.EffectiveVersion)
		}
	case <-time.After(5 * time.Second):
		t.Fatal("SIGHUP did not reach the replacer")
	}
}

// TestReplaceFileWatchReloadStopIsIdempotent proves stop can be called twice and
// that it unregisters the handler, so a deferred stop after an explicit stop does
// not panic or block.
func TestReplaceFileWatchReloadStopIsIdempotent(t *testing.T) {
	dir := t.TempDir()
	file := &ReplaceFile{Path: filepath.Join(dir, "replace-request.json")}
	stop, err := file.WatchReload(context.Background(), nil)
	if err != nil {
		t.Fatalf("watch replace file: %v", err)
	}
	stop()
	stop()
}

// TestReplaceFileWatchReloadRequiresPath proves an Endpoint that names no request
// file cannot start a watcher, which keeps the fail-closed default explicit.
func TestReplaceFileWatchReloadRequiresPath(t *testing.T) {
	if _, err := (&ReplaceFile{}).WatchReload(context.Background(), nil); err == nil {
		t.Fatal("watcher started without a request path")
	}
}
