package tui

import (
	"context"
	"errors"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"testing"
	"time"

	"topsailai_agent_cluster/internal/protocol"
)

// triggerRecorder is a TriggerRunner that records every invocation instead of
// starting a process, so a test observes the exact environment a script would
// receive without depending on the host's shell or interpreter.
type triggerRecorder struct {
	mu           sync.Mutex
	paths        []string
	environments [][]string
	err          error
	// block, when non-nil, holds RunTrigger until the test releases it, so a test
	// can prove a second transition is dropped while one script is in flight.
	block chan struct{}
}

func (r *triggerRecorder) RunTrigger(ctx context.Context, path string, environment []string) error {
	// The invocation is recorded before any blocking, so a test can observe that
	// the script started even while it is still held open.
	r.mu.Lock()
	r.paths = append(r.paths, path)
	r.environments = append(r.environments, environment)
	r.mu.Unlock()
	if r.block != nil {
		select {
		case <-r.block:
		case <-ctx.Done():
			return ctx.Err()
		}
	}
	return r.err
}

// count reports how many invocations the recorder observed.
func (r *triggerRecorder) count() int {
	r.mu.Lock()
	defer r.mu.Unlock()
	return len(r.paths)
}

func (r *triggerRecorder) lastEnvironment() []string {
	r.mu.Lock()
	defer r.mu.Unlock()
	if len(r.environments) == 0 {
		return nil
	}
	return r.environments[len(r.environments)-1]
}

// environmentValue reads one variable from a captured environment slice.
func environmentValue(environment []string, name string) (string, bool) {
	for _, entry := range environment {
		if index := strings.IndexByte(entry, '='); index > 0 && entry[:index] == name {
			return entry[index+1:], true
		}
	}
	return "", false
}

// triggerRow builds one session row for the tracker tests.
func triggerRow(endpointID, clusterSessionID, generation, state string) SessionRow {
	return SessionRow{
		EndpointID:          endpointID,
		ClusterSessionID:    clusterSessionID,
		ProviderSessionID:   "provider-" + clusterSessionID,
		ProviderDisplayName: "session " + clusterSessionID,
		ProviderGeneration:  generation,
		AdapterID:           "topsailai",
		State:               state,
	}
}

// TestShouldTriggerOnlyFiresOnRunningToWaitingInput pins the single transition
// the mechanism watches today. Every other pair must stay silent, because a
// trigger that fires on a state rather than a transition would fire on every
// tick and on arming.
func TestShouldTriggerOnlyFiresOnRunningToWaitingInput(t *testing.T) {
	cases := []struct {
		name     string
		previous string
		next     string
		want     bool
	}{
		{"running to waiting_input", protocol.SessionStateRunning, protocol.SessionStateWaitingInput, true},
		{"waiting_input to waiting_input", protocol.SessionStateWaitingInput, protocol.SessionStateWaitingInput, false},
		{"running to running", protocol.SessionStateRunning, protocol.SessionStateRunning, false},
		{"waiting_input to running", protocol.SessionStateWaitingInput, protocol.SessionStateRunning, false},
		{"idle to waiting_input", protocol.SessionStateIdle, protocol.SessionStateWaitingInput, false},
		{"unknown to waiting_input", protocol.SessionStateUnknown, protocol.SessionStateWaitingInput, false},
		{"running to idle", protocol.SessionStateRunning, protocol.SessionStateIdle, false},
		{"running to unknown", protocol.SessionStateRunning, protocol.SessionStateUnknown, false},
	}
	for _, testCase := range cases {
		t.Run(testCase.name, func(t *testing.T) {
			if got := shouldTrigger(testCase.previous, testCase.next); got != testCase.want {
				t.Fatalf("shouldTrigger(%q, %q) = %v, want %v", testCase.previous, testCase.next, got, testCase.want)
			}
		})
	}
}

// TestTriggerTrackerEstablishesBaselineWithoutFiring proves the first
// observation of a session never fires. Without this, arming watch would run the
// script once for every session already waiting for input, which is the opposite
// of "tell me when something changes".
func TestTriggerTrackerEstablishesBaselineWithoutFiring(t *testing.T) {
	tracker := triggerTracker{}
	rows := []SessionRow{triggerRow("ep1", "s1", "g1", protocol.SessionStateWaitingInput)}
	if events := tracker.observe(rows); len(events) != 0 {
		t.Fatalf("first observation fired %d events, want 0", len(events))
	}
	// A second observation of the same unchanged state must also stay silent.
	if events := tracker.observe(rows); len(events) != 0 {
		t.Fatalf("unchanged state fired %d events, want 0", len(events))
	}
}

// TestTriggerTrackerFiresOncePerTransition proves one transition produces
// exactly one event, and that the event carries the previous state so a script
// can distinguish the direction of the change.
func TestTriggerTrackerFiresOncePerTransition(t *testing.T) {
	tracker := triggerTracker{}
	tracker.observe([]SessionRow{triggerRow("ep1", "s1", "g1", protocol.SessionStateRunning)})
	events := tracker.observe([]SessionRow{triggerRow("ep1", "s1", "g1", protocol.SessionStateWaitingInput)})
	if len(events) != 1 {
		t.Fatalf("transition fired %d events, want 1", len(events))
	}
	event := events[0]
	if event.Event != triggerEventName {
		t.Fatalf("event = %q, want %q", event.Event, triggerEventName)
	}
	if event.State != protocol.SessionStateWaitingInput {
		t.Fatalf("state = %q, want %q", event.State, protocol.SessionStateWaitingInput)
	}
	if event.PreviousState != protocol.SessionStateRunning {
		t.Fatalf("previous state = %q, want %q", event.PreviousState, protocol.SessionStateRunning)
	}
	if event.ClusterSessionID != "s1" || event.EndpointID != "ep1" || event.ProviderGeneration != "g1" {
		t.Fatalf("event identity = %+v, want ep1/s1/g1", event)
	}
	// The same state observed again must not fire a second time.
	if again := tracker.observe([]SessionRow{triggerRow("ep1", "s1", "g1", protocol.SessionStateWaitingInput)}); len(again) != 0 {
		t.Fatalf("repeated state fired %d events, want 0", len(again))
	}
}

// TestTriggerTrackerFiresAgainAfterRoundTrip proves the baseline is a state, not
// a one-shot latch: a session that goes back to running and waits again is a new
// transition and must fire again.
func TestTriggerTrackerFiresAgainAfterRoundTrip(t *testing.T) {
	tracker := triggerTracker{}
	tracker.observe([]SessionRow{triggerRow("ep1", "s1", "g1", protocol.SessionStateRunning)})
	if events := tracker.observe([]SessionRow{triggerRow("ep1", "s1", "g1", protocol.SessionStateWaitingInput)}); len(events) != 1 {
		t.Fatalf("first transition fired %d events, want 1", len(events))
	}
	tracker.observe([]SessionRow{triggerRow("ep1", "s1", "g1", protocol.SessionStateRunning)})
	if events := tracker.observe([]SessionRow{triggerRow("ep1", "s1", "g1", protocol.SessionStateWaitingInput)}); len(events) != 1 {
		t.Fatalf("second transition fired %d events, want 1", len(events))
	}
}

// TestTriggerTrackerResetsBaselineOnGenerationChange proves a replaced process
// is treated as a new session. A new generation means the previous state
// belonged to a process that no longer exists, so comparing across generations
// would report a transition that never happened.
func TestTriggerTrackerResetsBaselineOnGenerationChange(t *testing.T) {
	tracker := triggerTracker{}
	tracker.observe([]SessionRow{triggerRow("ep1", "s1", "g1", protocol.SessionStateRunning)})
	events := tracker.observe([]SessionRow{triggerRow("ep1", "s1", "g2", protocol.SessionStateWaitingInput)})
	if len(events) != 0 {
		t.Fatalf("generation change fired %d events, want 0", len(events))
	}
	// The new generation now has its own baseline, so a real transition on it
	// still fires.
	tracker.observe([]SessionRow{triggerRow("ep1", "s1", "g2", protocol.SessionStateRunning)})
	if events := tracker.observe([]SessionRow{triggerRow("ep1", "s1", "g2", protocol.SessionStateWaitingInput)}); len(events) != 1 {
		t.Fatalf("transition on the new generation fired %d events, want 1", len(events))
	}
}

// TestTriggerTrackerDropsVanishedSessions proves the baseline cannot grow
// without bound. A session that is no longer reported is removed, so a long
// watch over a churning fleet keeps one entry per live session.
func TestTriggerTrackerDropsVanishedSessions(t *testing.T) {
	tracker := triggerTracker{}
	tracker.observe([]SessionRow{
		triggerRow("ep1", "s1", "g1", protocol.SessionStateRunning),
		triggerRow("ep1", "s2", "g1", protocol.SessionStateRunning),
	})
	if len(tracker.states) != 2 {
		t.Fatalf("baseline holds %d entries, want 2", len(tracker.states))
	}
	tracker.observe([]SessionRow{triggerRow("ep1", "s1", "g1", protocol.SessionStateRunning)})
	if len(tracker.states) != 1 {
		t.Fatalf("baseline holds %d entries after one session vanished, want 1", len(tracker.states))
	}
}

// TestTriggerTrackerReportsEveryTransitionInOneCollection proves a collection
// that observes several transitions reports all of them, so one tick is not
// limited to one script run by the tracker itself.
func TestTriggerTrackerReportsEveryTransitionInOneCollection(t *testing.T) {
	tracker := triggerTracker{}
	tracker.observe([]SessionRow{
		triggerRow("ep1", "s1", "g1", protocol.SessionStateRunning),
		triggerRow("ep1", "s2", "g1", protocol.SessionStateRunning),
	})
	events := tracker.observe([]SessionRow{
		triggerRow("ep1", "s1", "g1", protocol.SessionStateWaitingInput),
		triggerRow("ep1", "s2", "g1", protocol.SessionStateWaitingInput),
	})
	if len(events) != 2 {
		t.Fatalf("two transitions fired %d events, want 2", len(events))
	}
}

// TestTriggerEnvironmentForwardsOnlyTheWhitelist is the security test. The REPL
// process environment carries the cluster credentials, including the map of
// every endpoint token, so inheriting it would hand each notification script the
// authority to operate the whole fleet.
func TestTriggerEnvironmentForwardsOnlyTheWhitelist(t *testing.T) {
	t.Setenv("AGENT_CLUSTER_CLI_ENDPOINT_TOKENS", "ep1=secret-token")
	t.Setenv("AGENT_CLUSTER_ENDPOINT_TOKENS", "ep1=deprecated-secret-token")
	t.Setenv("AGENT_CLUSTER_SERVER_TOKEN", "server-secret")
	t.Setenv("UNRELATED_SECRET", "leaked")
	event := TriggerEvent{
		Event:              triggerEventName,
		State:              protocol.SessionStateWaitingInput,
		PreviousState:      protocol.SessionStateRunning,
		EndpointID:         "ep1",
		ClusterSessionID:   "s1",
		ProviderSessionID:  "provider-s1",
		SessionName:        "session s1",
		ProviderGeneration: "g1",
		AdapterID:          "topsailai",
		ProjectWorkspace:   "/work/project",
		Unverified:         false,
		Stale:              true,
		ObservedAtMS:       "1700000000000",
	}
	environment := triggerEnvironment(event)
	for _, forbidden := range []string{"AGENT_CLUSTER_CLI_ENDPOINT_TOKENS", "AGENT_CLUSTER_ENDPOINT_TOKENS", "AGENT_CLUSTER_SERVER_TOKEN", "UNRELATED_SECRET"} {
		if value, ok := environmentValue(environment, forbidden); ok {
			t.Fatalf("environment leaked %s=%q to the trigger script", forbidden, value)
		}
	}
	// The payload must be complete, because a script cannot query the cluster.
	want := map[string]string{
		"AGENT_CLUSTER_EVENT":               triggerEventName,
		"AGENT_CLUSTER_STATE":               protocol.SessionStateWaitingInput,
		"AGENT_CLUSTER_PREVIOUS_STATE":      protocol.SessionStateRunning,
		"AGENT_CLUSTER_ENDPOINT_ID":         "ep1",
		"AGENT_CLUSTER_CLUSTER_SESSION_ID":  "s1",
		"AGENT_CLUSTER_PROVIDER_SESSION_ID": "provider-s1",
		"AGENT_CLUSTER_SESSION_NAME":        "session s1",
		"AGENT_CLUSTER_PROVIDER_GENERATION": "g1",
		"AGENT_CLUSTER_ADAPTER_ID":          "topsailai",
		"AGENT_CLUSTER_PROJECT_WORKSPACE":   "/work/project",
		"AGENT_CLUSTER_UNVERIFIED":          "false",
		"AGENT_CLUSTER_STALE":               "true",
		"AGENT_CLUSTER_OBSERVED_AT_MS":      "1700000000000",
	}
	for name, expected := range want {
		value, ok := environmentValue(environment, name)
		if !ok {
			t.Fatalf("environment is missing %s", name)
		}
		if value != expected {
			t.Fatalf("%s = %q, want %q", name, value, expected)
		}
	}
	// A dumb terminal keeps a script from emitting escape sequences into the
	// table the editor owns.
	if value, ok := environmentValue(environment, "TERM"); !ok || value != "dumb" {
		t.Fatalf("TERM = %q (present=%v), want dumb", value, ok)
	}
}

// TestTriggerEnvironmentOmitsAbsentObservationTime proves an absent observation
// time is forwarded as an empty value rather than as a fabricated zero, so a
// script can tell "not reported" from "reported as the epoch".
func TestTriggerEnvironmentOmitsAbsentObservationTime(t *testing.T) {
	environment := triggerEnvironment(TriggerEvent{Event: triggerEventName})
	value, ok := environmentValue(environment, "AGENT_CLUSTER_OBSERVED_AT_MS")
	if !ok {
		t.Fatal("AGENT_CLUSTER_OBSERVED_AT_MS is missing")
	}
	if value != "" {
		t.Fatalf("AGENT_CLUSTER_OBSERVED_AT_MS = %q, want empty", value)
	}
}

// TestResolveTriggerScriptRejectsUnusableExplicitPath proves an explicit path is
// validated strictly. The operator named the file, so a missing or
// non-executable script is an error rather than a silent no-op that would leave
// the operator believing a script is armed.
func TestResolveTriggerScriptRejectsUnusableExplicitPath(t *testing.T) {
	dir := t.TempDir()
	missing := filepath.Join(dir, "absent.trigger")
	if _, _, err := resolveTriggerScript(watchRequest{TriggerSet: true, TriggerPath: missing}); err == nil {
		t.Fatal("a missing explicit script was accepted")
	}
	plain := filepath.Join(dir, "plain.trigger")
	if err := os.WriteFile(plain, []byte("#!/bin/sh\n"), 0o644); err != nil {
		t.Fatalf("write plain script: %v", err)
	}
	if _, _, err := resolveTriggerScript(watchRequest{TriggerSet: true, TriggerPath: plain}); err == nil {
		t.Fatal("a non-executable explicit script was accepted")
	}
	if _, _, err := resolveTriggerScript(watchRequest{TriggerSet: true, TriggerPath: dir}); err == nil {
		t.Fatal("a directory was accepted as an explicit script")
	}
	executable := filepath.Join(dir, "run.trigger")
	if err := os.WriteFile(executable, []byte("#!/bin/sh\n"), 0o755); err != nil {
		t.Fatalf("write executable script: %v", err)
	}
	resolved, note, err := resolveTriggerScript(watchRequest{TriggerSet: true, TriggerPath: executable})
	if err != nil {
		t.Fatalf("an executable explicit script was rejected: %v", err)
	}
	if note != "" {
		t.Fatalf("an executable explicit script produced note %q, want none", note)
	}
	if resolved != executable {
		t.Fatalf("resolved = %q, want %q", resolved, executable)
	}
}

// TestResolveTriggerScriptReportsMissingDefaultAsNote proves the default
// location is validated leniently. The operator asked for the convention rather
// than for one exact file, so an absent script is a note instead of an error,
// and the banner never claims a script will run when none is installed.
func TestResolveTriggerScriptReportsMissingDefaultAsNote(t *testing.T) {
	home := t.TempDir()
	t.Setenv("HOME", home)
	path, note, err := resolveTriggerScript(watchRequest{TriggerSet: true})
	if err != nil {
		t.Fatalf("a missing default script was an error: %v", err)
	}
	if path != "" {
		t.Fatalf("path = %q, want empty", path)
	}
	if note == "" {
		t.Fatal("a missing default script produced no note")
	}
	if !strings.Contains(note, defaultTriggerFileName) {
		t.Fatalf("note %q does not name the expected file %q", note, defaultTriggerFileName)
	}
}

// TestResolveTriggerScriptFindsDefaultScript proves the default location is the
// documented one, so an operator installs one file and every watch in that
// account finds it.
func TestResolveTriggerScriptFindsDefaultScript(t *testing.T) {
	home := t.TempDir()
	t.Setenv("HOME", home)
	directory := filepath.Join(home, triggerHomeRelativeDir)
	if err := os.MkdirAll(directory, 0o755); err != nil {
		t.Fatalf("create config directory: %v", err)
	}
	script := filepath.Join(directory, defaultTriggerFileName)
	if err := os.WriteFile(script, []byte("#!/bin/sh\n"), 0o755); err != nil {
		t.Fatalf("write default script: %v", err)
	}
	path, note, err := resolveTriggerScript(watchRequest{TriggerSet: true})
	if err != nil {
		t.Fatalf("the default script was rejected: %v", err)
	}
	if note != "" {
		t.Fatalf("the default script produced note %q, want none", note)
	}
	if path != script {
		t.Fatalf("path = %q, want %q", path, script)
	}
}

// TestResolveTriggerScriptIgnoresRequestWithoutTrigger proves a watch without
// --trigger resolves nothing, so the plain loop keeps its previous behaviour
// exactly.
func TestResolveTriggerScriptIgnoresRequestWithoutTrigger(t *testing.T) {
	path, note, err := resolveTriggerScript(watchRequest{})
	if err != nil || path != "" || note != "" {
		t.Fatalf("resolveTriggerScript without --trigger = (%q, %q, %v), want empty", path, note, err)
	}
}

// TestResolveTriggerScriptFromShortFlag proves the -t spelling reaches script
// resolution instead of stopping at the parser. A shorthand that only sets a
// parser field would look correct in a grammar test while the loop still ran
// without a script, so this drives the parsed request into the resolver.
func TestResolveTriggerScriptFromShortFlag(t *testing.T) {
	home := t.TempDir()
	t.Setenv("HOME", home)
	directory := filepath.Join(home, triggerHomeRelativeDir)
	if err := os.MkdirAll(directory, 0o755); err != nil {
		t.Fatalf("create config directory: %v", err)
	}
	script := filepath.Join(directory, defaultTriggerFileName)
	if err := os.WriteFile(script, []byte("#!/bin/sh\n"), 0o755); err != nil {
		t.Fatalf("write default script: %v", err)
	}
	request, err := parseWatchArguments("-t")
	if err != nil {
		t.Fatalf("parseWatchArguments(-t) failed: %v", err)
	}
	path, note, err := resolveTriggerScript(request)
	if err != nil {
		t.Fatalf("the default script resolved from -t was rejected: %v", err)
	}
	if note != "" {
		t.Fatalf("the default script resolved from -t produced note %q, want none", note)
	}
	if path != script {
		t.Fatalf("path = %q, want %q", path, script)
	}
}

// TestParseWatchArgumentsAcceptsTriggerForms pins the grammar. A bare --trigger
// selects the default location, and --trigger=<path> names one; both are flags
// rather than positionals because the interval is already positional. -t is a
// spelling of the same flag, so it accepts exactly the same two forms.
func TestParseWatchArgumentsAcceptsTriggerForms(t *testing.T) {
	cases := []struct {
		name         string
		rest         string
		wantSet      bool
		wantPath     string
		wantForce    bool
		wantInterval time.Duration
	}{
		{"bare trigger", "--trigger", true, "", false, defaultWatchInterval},
		{"trigger with path", "--trigger=/tmp/run.trigger", true, "/tmp/run.trigger", false, defaultWatchInterval},
		{"trigger with interval", "2s --trigger", true, "", false, 2 * time.Second},
		{"trigger with force", "--force --trigger", true, "", true, defaultForcedInterval},
		{"trigger path with force", "--trigger=/tmp/run.trigger --force", true, "/tmp/run.trigger", true, defaultForcedInterval},
		{"bare short trigger", "-t", true, "", false, defaultWatchInterval},
		{"short trigger with path", "-t=/tmp/run.trigger", true, "/tmp/run.trigger", false, defaultWatchInterval},
		{"short trigger with interval", "2s -t", true, "", false, 2 * time.Second},
		{"short trigger with force", "--force -t", true, "", true, defaultForcedInterval},
		{"short trigger path with force", "-t=/tmp/run.trigger --force", true, "/tmp/run.trigger", true, defaultForcedInterval},
		{"no trigger", "3s", false, "", false, 3 * time.Second},
	}
	for _, testCase := range cases {
		t.Run(testCase.name, func(t *testing.T) {
			request, err := parseWatchArguments(testCase.rest)
			if err != nil {
				t.Fatalf("parseWatchArguments(%q) failed: %v", testCase.rest, err)
			}
			if request.TriggerSet != testCase.wantSet {
				t.Fatalf("TriggerSet = %v, want %v", request.TriggerSet, testCase.wantSet)
			}
			if request.TriggerPath != testCase.wantPath {
				t.Fatalf("TriggerPath = %q, want %q", request.TriggerPath, testCase.wantPath)
			}
			if request.Force != testCase.wantForce {
				t.Fatalf("Force = %v, want %v", request.Force, testCase.wantForce)
			}
			if request.Interval != testCase.wantInterval {
				t.Fatalf("Interval = %s, want %s", request.Interval, testCase.wantInterval)
			}
		})
	}
}

// TestParseWatchArgumentsRejectsMalformedTrigger proves a repeated or empty
// trigger is rejected rather than resolved by precedence, because either choice
// would silently ignore something the operator stated.
func TestParseWatchArgumentsRejectsMalformedTrigger(t *testing.T) {
	for _, rest := range []string{"--trigger --trigger", "--trigger=/a --trigger=/b", "--trigger=", "--trigger=/a --trigger", "-t -t", "-t=/a -t=/b", "-t=", "-t --trigger", "-t=/a --trigger=/b", "--trigger -t"} {
		if _, err := parseWatchArguments(rest); err == nil {
			t.Fatalf("parseWatchArguments(%q) was accepted", rest)
		}
	}
}

// triggerStub serves one endpoint whose single session state the test changes
// between ticks, so a controller test can observe a real transition without a
// Server or a provider.
type triggerStub struct {
	interactiveStub
	mu    sync.Mutex
	state string
}

// GetInventory shadows the embedded stub so the served state can change.
func (s *triggerStub) GetInventory(ctx context.Context, id string) (protocol.InventoryReport, error) {
	s.mu.Lock()
	state := s.state
	s.mu.Unlock()
	report := scopeInventory("res-1", "generation-1")
	report.Sessions[0].State = state
	return report, nil
}

// setState changes the state the next collection observes.
func (s *triggerStub) setState(state string) {
	s.mu.Lock()
	s.state = state
	s.mu.Unlock()
}

// newTriggerStub serves one endpoint with one session in the given state.
func newTriggerStub(state string) *triggerStub {
	stub := &triggerStub{state: state}
	stub.endpoints = []protocol.Endpoint{{EndpointID: "endpoint-1", Hostname: "host-one"}}
	return stub
}

// TestWatchControllerRunsTriggerOnTransition proves the controller wires the
// tracker to the runner: one collection establishes the baseline, the next
// collection observes the transition, and the script runs exactly once with the
// complete payload.
func TestWatchControllerRunsTriggerOnTransition(t *testing.T) {
	recorder := &triggerRecorder{}
	ticks := newWatchManualTicks()
	stub := newTriggerStub(protocol.SessionStateRunning)
	controller := newWatchController(context.Background(), stub, "", watchRequest{
		Interval:      time.Second,
		TriggerSet:    true,
		TriggerScript: "/tmp/run.trigger",
	}, ticks.ticker, ColorPolicy{}, staticLayout(TableLayout{}), recorder)
	defer controller.Stop()
	waitForResult(t, controller)
	if recorder.count() != 0 {
		t.Fatalf("the baseline collection ran the script %d times, want 0", recorder.count())
	}
	stub.setState(protocol.SessionStateWaitingInput)
	ticks.tick(t)
	waitForResult(t, controller)
	waitForTriggerCount(t, recorder, 1)
	environment := recorder.lastEnvironment()
	if value, _ := environmentValue(environment, "AGENT_CLUSTER_STATE"); value != protocol.SessionStateWaitingInput {
		t.Fatalf("AGENT_CLUSTER_STATE = %q, want %q", value, protocol.SessionStateWaitingInput)
	}
	if value, _ := environmentValue(environment, "AGENT_CLUSTER_CLUSTER_SESSION_ID"); value != "res-1" {
		t.Fatalf("AGENT_CLUSTER_CLUSTER_SESSION_ID = %q, want res-1", value)
	}
	if value, _ := environmentValue(environment, "AGENT_CLUSTER_PREVIOUS_STATE"); value != protocol.SessionStateRunning {
		t.Fatalf("AGENT_CLUSTER_PREVIOUS_STATE = %q, want %q", value, protocol.SessionStateRunning)
	}
}

// TestWatchControllerSkipsTriggerWithoutScript proves a watch without --trigger
// never calls the runner, so the plain loop is unchanged.
func TestWatchControllerSkipsTriggerWithoutScript(t *testing.T) {
	recorder := &triggerRecorder{}
	ticks := newWatchManualTicks()
	stub := newTriggerStub(protocol.SessionStateRunning)
	controller := newWatchController(context.Background(), stub, "", watchRequest{Interval: time.Second}, ticks.ticker, ColorPolicy{}, staticLayout(TableLayout{}), recorder)
	defer controller.Stop()
	waitForResult(t, controller)
	stub.setState(protocol.SessionStateWaitingInput)
	ticks.tick(t)
	waitForResult(t, controller)
	if recorder.count() != 0 {
		t.Fatalf("a watch without --trigger ran the script %d times, want 0", recorder.count())
	}
}

// TestWatchControllerDropsTransitionWhileScriptRuns proves an overlapping
// transition is dropped rather than queued. A notification script that cannot
// keep up must not accumulate a backlog of events describing a state the
// operator already saw.
func TestWatchControllerDropsTransitionWhileScriptRuns(t *testing.T) {
	recorder := &triggerRecorder{block: make(chan struct{})}
	ticks := newWatchManualTicks()
	stub := newTriggerStub(protocol.SessionStateRunning)
	controller := newWatchController(context.Background(), stub, "", watchRequest{
		Interval:      time.Second,
		TriggerSet:    true,
		TriggerScript: "/tmp/run.trigger",
	}, ticks.ticker, ColorPolicy{}, staticLayout(TableLayout{}), recorder)
	defer controller.Stop()
	waitForResult(t, controller)
	// The first transition starts a script that blocks until the test releases it.
	stub.setState(protocol.SessionStateWaitingInput)
	ticks.tick(t)
	waitForResult(t, controller)
	waitForTriggerCount(t, recorder, 1)
	// A second transition arrives while the first script is still running, so it
	// must be dropped instead of queued.
	stub.setState(protocol.SessionStateRunning)
	ticks.tick(t)
	waitForResult(t, controller)
	stub.setState(protocol.SessionStateWaitingInput)
	ticks.tick(t)
	waitForResult(t, controller)
	if recorder.count() != 1 {
		t.Fatalf("an overlapping transition ran the script %d times, want 1", recorder.count())
	}
	close(recorder.block)
}

// TestWatchControllerReportsScriptFailure proves a failing script is reported
// through the controller's own failure channel, so the operator learns the
// notification did not happen instead of assuming it did.
func TestWatchControllerReportsScriptFailure(t *testing.T) {
	recorder := &triggerRecorder{err: errors.New("script failed")}
	ticks := newWatchManualTicks()
	stub := newTriggerStub(protocol.SessionStateRunning)
	controller := newWatchController(context.Background(), stub, "", watchRequest{
		Interval:      time.Second,
		TriggerSet:    true,
		TriggerScript: "/tmp/run.trigger",
	}, ticks.ticker, ColorPolicy{}, staticLayout(TableLayout{}), recorder)
	defer controller.Stop()
	waitForResult(t, controller)
	stub.setState(protocol.SessionStateWaitingInput)
	ticks.tick(t)
	waitForResult(t, controller)
	waitForTriggerCount(t, recorder, 1)
	deadline := time.Now().Add(2 * time.Second)
	for time.Now().Before(deadline) {
		controller.mu.Lock()
		lastErr := controller.lastErr
		controller.mu.Unlock()
		if strings.Contains(lastErr, "script failed") {
			return
		}
		time.Sleep(5 * time.Millisecond)
	}
	t.Fatal("the script failure was never reported")
}

// waitForTriggerCount waits until the recorder observed want invocations. The
// script runs on its own goroutine, so a test cannot assume it finished when the
// collection result was published.
func waitForTriggerCount(t *testing.T, recorder *triggerRecorder, want int) {
	t.Helper()
	deadline := time.Now().Add(2 * time.Second)
	for time.Now().Before(deadline) {
		if recorder.count() == want {
			return
		}
		time.Sleep(5 * time.Millisecond)
	}
	t.Fatalf("trigger ran %d times, want %d", recorder.count(), want)
}
