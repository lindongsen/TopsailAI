package main

import (
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

// wantOperations is the complete operation surface the mock must advertise and
// answer. It is written out literally rather than derived from the evidence
// table, because a test that reads the same table it verifies cannot detect a
// missing entry.
var wantOperations = []string{
	"agent.drive.start",
	"agent.drive.stop",
	"agent.model.select",
	"agent.resume",
	"agent.start",
	"agent.stop",
	"command.exec",
	"context.inject",
	"execution.interrupt",
	"message.send",
	"workspace.clean",
}

// wantVersions states the advertised version of every operation whose payload
// schema is versioned independently of the generic "v1". The Cluster intersects
// the configured capability list with the advertised one by name AND version, so
// an operation advertised at the wrong version is silently dropped and every
// command for it is rejected as unsupported. The map is written out literally
// rather than read from the evidence table for the same reason wantOperations is:
// a test that reads the table it verifies cannot detect a wrong entry.
var wantVersions = map[string]string{
	"agent.model.select": "1",
	"command.exec":       "1",
}

// TestDescriptorAdvertisesEveryOperation proves the advertised surface is the
// full eleven-operation set, so a scenario that drives one of them cannot fail
// with "unsupported" merely because the mock forgot to advertise it.
func TestDescriptorAdvertisesEveryOperation(t *testing.T) {
	descriptor := mockDescriptor("")
	if len(descriptor.Operations) != len(wantOperations) {
		t.Fatalf("advertised %d operations, want %d: %#v", len(descriptor.Operations), len(wantOperations), descriptor.Operations)
	}
	for index, want := range wantOperations {
		got := descriptor.Operations[index]
		wantVersion := "v1"
		if versioned, ok := wantVersions[want]; ok {
			wantVersion = versioned
		}
		if got.Name != want || got.Version != wantVersion {
			t.Fatalf("operation %d = %#v, want %q/%s", index, got, want, wantVersion)
		}
	}
}

// executeTestTarget returns the target an operation must carry to be answered.
//
// agent.start addresses a launch profile, so its generation is the profile
// revision rather than a session process generation. Reusing the session target
// for every operation asserted that one target shape fits all of them, which is
// the assumption the mock had to stop making when start began validating its own
// target.
func executeTestTarget(operation string) *target {
	if operation == "agent.start" {
		return &target{ResourceKind: resourceLaunchProfile, ProviderResourceKey: "launch:mock", ExpectedGeneration: launchProfileRevision}
	}
	return &target{ResourceKind: resourceSession, ProviderResourceKey: "session:stable", ExpectedGeneration: "generation-1"}
}

// TestExecuteAnswersEveryAdvertisedOperation proves the answered surface equals
// the advertised surface. An operation that is advertised but rejected would be
// a capability lie, and the Cluster would surface it as a provider failure
// rather than as a missing mock entry.
func TestExecuteAnswersEveryAdvertisedOperation(t *testing.T) {
	for _, name := range wantOperations {
		request := request{
			RequestID: "req-" + name,
			Function:  functionExecute,
			// The version comes from the table, because two operations carry their
			// own payload schema version. Hardcoding "v1" here asserted that every
			// operation shares one version, which is exactly the assumption the
			// descriptor had to stop making.
			Operation: &namedContract{Name: name, Version: operationEvidenceTable[name].version},
			Target:    executeTestTarget(name),
			Payload:   json.RawMessage(`{}`),
		}
		response := executeResponse(request, "")
		if !response.OK {
			t.Fatalf("operation %q rejected: %#v", name, response.Error)
		}
		if response.Result == nil {
			t.Fatalf("operation %q returned no result", name)
		}
		if response.Result.DeliveryBoundary == "" || response.Result.EffectCertainty == "" || response.Result.ProviderOutcome == "" {
			t.Fatalf("operation %q returned incomplete evidence: %#v", name, response.Result)
		}
	}
}

// TestExecutePreservesStopEvidence proves the evidence shape the Cluster receipt
// depends on. A stop that reported pipe_written would make the TUI render
// "delivered" instead of "stop request sent", so the boundary is behaviour, not
// decoration.
func TestExecutePreservesStopEvidence(t *testing.T) {
	cases := map[string]string{
		"agent.stop":          "signal_sent",
		"execution.interrupt": "signal_sent",
		"agent.drive.stop":    "signal_sent",
		"message.send":        "pipe_written",
		"context.inject":      "pipe_written",
	}
	for name, wantBoundary := range cases {
		request := request{
			RequestID: "req-" + name,
			Function:  functionExecute,
			Operation: &namedContract{Name: name, Version: "v1"},
			Target:    &target{ResourceKind: resourceSession, ProviderResourceKey: "session:stable", ExpectedGeneration: "generation-1"},
			Payload:   json.RawMessage(`{}`),
		}
		response := executeResponse(request, "")
		if !response.OK || response.Result == nil {
			t.Fatalf("operation %q rejected: %#v", name, response.Error)
		}
		if response.Result.DeliveryBoundary != wantBoundary {
			t.Fatalf("operation %q delivery boundary = %q, want %q", name, response.Result.DeliveryBoundary, wantBoundary)
		}
	}
}

// TestExecuteRejectsLiveOperationWithoutGeneration proves the fail-closed rule
// survives the widened surface: a live operation with no generation is rejected
// before any effect is claimed, while a non-live operation is allowed to carry
// none because it addresses a durable record rather than a process.
func TestExecuteRejectsLiveOperationWithoutGeneration(t *testing.T) {
	live := request{
		RequestID: "req-live",
		Function:  functionExecute,
		Operation: &namedContract{Name: "message.send", Version: "v1"},
		Target:    &target{ResourceKind: resourceSession, ProviderResourceKey: "session:stable"},
		Payload:   json.RawMessage(`{}`),
	}
	if response := executeResponse(live, ""); response.OK || response.Error == nil || response.Error.Code != "generation_mismatch" {
		t.Fatalf("live operation without generation was not rejected: %#v", response)
	}
	for _, name := range []string{"agent.resume", "agent.drive.stop", "workspace.clean"} {
		nonLive := request{
			RequestID: "req-" + name,
			Function:  functionExecute,
			Operation: &namedContract{Name: name, Version: "v1"},
			Target:    &target{ResourceKind: resourceSession, ProviderResourceKey: "session:stable"},
			Payload:   json.RawMessage(`{}`),
		}
		if response := executeResponse(nonLive, ""); !response.OK {
			t.Fatalf("non-live operation %q rejected: %#v", name, response.Error)
		}
	}
}

// TestExecuteRejectsUnknownOperation proves an operation outside the advertised
// set is rejected rather than silently succeeding.
func TestExecuteRejectsUnknownOperation(t *testing.T) {
	request := request{
		RequestID: "req-unknown",
		Function:  functionExecute,
		Operation: &namedContract{Name: "agent.teleport", Version: "v1"},
		Target:    &target{ResourceKind: resourceSession, ProviderResourceKey: "session:stable", ExpectedGeneration: "generation-1"},
		Payload:   json.RawMessage(`{}`),
	}
	response := executeResponse(request, "")
	if response.OK || response.Error == nil || response.Error.Code != "unsupported" {
		t.Fatalf("unknown operation was not rejected: %#v", response)
	}
}

// TestDiscoveryObservationsCoverEveryMode proves each discovery mode produces
// the document a migrated scenario depends on. "mixed" is load-bearing: a resume
// scenario needs a row the provider lists but cannot prove is live, and "empty"
// proves an empty inventory is not a failure.
func TestDiscoveryObservationsCoverEveryMode(t *testing.T) {
	cases := []struct {
		mode      string
		wantCount int
		wantLive  bool
	}{
		{mode: "one", wantCount: 1, wantLive: true},
		{mode: "", wantCount: 1, wantLive: true},
		{mode: "mixed", wantCount: 2, wantLive: true},
		{mode: "empty", wantCount: 0},
	}
	for _, testCase := range cases {
		observations, err := discoveryObservations(mockOptions{mode: testCase.mode, failAfterN: -1})
		if err != nil {
			t.Fatalf("mode %q: unexpected error: %v", testCase.mode, err)
		}
		if len(observations) != testCase.wantCount {
			t.Fatalf("mode %q: got %d observations, want %d", testCase.mode, len(observations), testCase.wantCount)
		}
		if testCase.wantLive && observations[0].ProviderGeneration != "generation-1" {
			t.Fatalf("mode %q: first observation generation = %q, want generation-1", testCase.mode, observations[0].ProviderGeneration)
		}
	}
}

// TestDiscoveryObservationsMixedKeepsUnverifiedRow proves the second row of the
// mixed document carries an empty generation, because that emptiness is the
// provider's own statement that no process holds the session. A non-empty value
// would make resume refuse the very target it exists for.
func TestDiscoveryObservationsMixedKeepsUnverifiedRow(t *testing.T) {
	observations, err := discoveryObservations(mockOptions{mode: "mixed", failAfterN: -1})
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if len(observations) != 2 {
		t.Fatalf("got %d observations, want 2", len(observations))
	}
	if observations[1].ProviderGeneration != "" {
		t.Fatalf("unverified row generation = %q, want empty", observations[1].ProviderGeneration)
	}
	if observations[1].State != "stopped" {
		t.Fatalf("unverified row state = %q, want stopped", observations[1].State)
	}
}

// TestDiscoveryObservationsHonourFailureKnobs proves the two failure knobs the
// harness uses still work: always-fail fails every call, and fail-after-n fails
// only once the durable counter passes the threshold.
func TestDiscoveryObservationsHonourFailureKnobs(t *testing.T) {
	if _, err := discoveryObservations(mockOptions{mode: "one", alwaysFail: true, failAfterN: -1}); err == nil {
		t.Fatal("always-fail produced no error")
	}
	counter := filepath.Join(t.TempDir(), "discovery-count")
	options := mockOptions{mode: "one", discoveryCountFile: counter, failAfterN: 2}
	for attempt := 1; attempt <= 2; attempt++ {
		if _, err := discoveryObservations(options); err != nil {
			t.Fatalf("attempt %d failed before the threshold: %v", attempt, err)
		}
	}
	if _, err := discoveryObservations(options); err == nil {
		t.Fatal("attempt 3 succeeded past fail-after-n=2")
	}
}

// TestDiscoveryObservationsRejectUnknownMode proves a stale mode fails loudly
// instead of silently falling back to a default document.
func TestDiscoveryObservationsRejectUnknownMode(t *testing.T) {
	if _, err := discoveryObservations(mockOptions{mode: "nonsense", failAfterN: -1}); err == nil {
		t.Fatal("unknown mode produced no error")
	}
}

// TestRecordInvocationWritesOneRecordPerCall proves the invocation record is the
// evidence a scenario reads to assert the provider was reached. Without it, a
// "provider was not called" assertion has no source.
func TestRecordInvocationWritesOneRecordPerCall(t *testing.T) {
	recordFile := filepath.Join(t.TempDir(), "records.jsonl")
	options := mockOptions{recordFile: recordFile}
	request := request{
		RequestID: "req-1",
		Operation: &namedContract{Name: "agent.stop", Version: "v1"},
		Target:    &target{ProviderResourceKey: "session:stable", ExpectedGeneration: "generation-1"},
	}
	recordInvocation(options, request, "execute")
	recordInvocation(options, request, "execute")
	data, err := os.ReadFile(recordFile)
	if err != nil {
		t.Fatalf("read record file: %v", err)
	}
	lines := strings.Split(strings.TrimSpace(string(data)), "\n")
	if len(lines) != 2 {
		t.Fatalf("got %d records, want 2: %q", len(lines), string(data))
	}
	var record map[string]any
	if err := json.Unmarshal([]byte(lines[0]), &record); err != nil {
		t.Fatalf("decode record: %v", err)
	}
	if record["operation"] != "agent.stop" {
		t.Fatalf("record operation = %v, want agent.stop", record["operation"])
	}
	if record["target_generation"] != "generation-1" {
		t.Fatalf("record target_generation = %v, want generation-1", record["target_generation"])
	}
}

// TestRecordInvocationNamesFunctionCalls proves a read invocation is recorded
// with an operation name even though it carries no Operation field. A caller
// counting provider reads by operation name counted zero while the provider had
// been invoked, so the record has to name the operation for a function call too.
func TestRecordInvocationNamesFunctionCalls(t *testing.T) {
	recordFile := filepath.Join(t.TempDir(), "records.jsonl")
	options := mockOptions{recordFile: recordFile}
	request := request{
		RequestID: "req-read",
		Function:  functionReadOutput,
		Target:    &target{ProviderResourceKey: "session:stable", ExpectedGeneration: "generation-1"},
	}
	recordInvocation(options, request, "output.read")
	data, err := os.ReadFile(recordFile)
	if err != nil {
		t.Fatalf("read record file: %v", err)
	}
	var record map[string]any
	if err := json.Unmarshal([]byte(strings.TrimSpace(string(data))), &record); err != nil {
		t.Fatalf("decode record: %v", err)
	}
	if record["operation"] != "output.read" {
		t.Fatalf("record operation = %v, want output.read", record["operation"])
	}
	if record["kind"] != "output.read" {
		t.Fatalf("record kind = %v, want output.read", record["kind"])
	}
}

// TestRecordInvocationIsOptional proves an unconfigured record file is not an
// error, because the conformance suite launches the mock without one.
func TestRecordInvocationIsOptional(t *testing.T) {
	recordInvocation(mockOptions{}, request{RequestID: "req-1"}, "execute")
}
