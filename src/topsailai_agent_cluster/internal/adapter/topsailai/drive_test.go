package topsailai

import (
	"context"
	"os/exec"
	"reflect"
	"testing"

	"topsailai_agent_cluster/internal/adapter"
	"topsailai_agent_cluster/internal/protocol"
)

// driveDiscoveryDocument returns one routable session row carrying the supplied
// driver observation, so a test can vary only the controller evidence.
func driveDiscoveryDocument(driver string) []byte {
	return []byte(`{"items":[{"session_id":"s1","process_generation":"g1","status":"running","driver":` + driver + `}]}`)
}

// TestDiscoverReportsDriverState proves the provider's controller observation
// reaches the standard inventory instead of being silently dropped.
func TestDiscoverReportsDriverState(t *testing.T) {
	runner := &fakeRunner{out: driveDiscoveryDocument(`{"state":"ON","reason":"publication_verified","driver_pid":4242,"run_id":"run-1","verification":"verified","metadata_status":"running"}`)}
	a := newTestAdapter(t, runner)
	result, err := a.Discover(context.Background(), adapter.DiscoverRequest{})
	if err != nil {
		t.Fatalf("discover: %v", err)
	}
	if len(result.Sessions) != 1 || result.Sessions[0].Drive == nil {
		t.Fatalf("drive summary missing: %#v", result.Sessions)
	}
	drive := result.Sessions[0].Drive
	if drive.State != protocol.DriveStateRunning || !drive.Verified {
		t.Fatalf("drive = %#v, want a verified running controller", drive)
	}
	if drive.ControllerPID != 4242 || drive.RunID != "run-1" || drive.Reason != "publication_verified" {
		t.Fatalf("drive evidence = %#v", drive)
	}
	if drive.ObservedAtMS == 0 {
		t.Fatal("drive summary must carry its observation time")
	}
}

// TestDiscoverMapsDriverStatesConservatively proves an unverified or unknown
// controller is never reported as running, because an operator who believes a
// controller is active would stop supervising the session.
func TestDiscoverMapsDriverStatesConservatively(t *testing.T) {
	cases := []struct {
		name       string
		driver     string
		wantState  string
		wantNil    bool
		wantVerify bool
	}{
		{name: "absent observation", driver: `null`, wantNil: true},
		{name: "no record", driver: `{"state":"-"`, wantState: protocol.DriveStateNone},
		{name: "stale record", driver: `{"state":"STALE","verification":"verified"`, wantState: protocol.DriveStateStale},
		{name: "clean exit", driver: `{"state":"EXIT"`, wantState: protocol.DriveStateExited},
		{name: "failed exit", driver: `{"state":"FAIL"`, wantState: protocol.DriveStateFailed},
		{name: "unknown state", driver: `{"state":"?"`, wantState: protocol.DriveStateUnknown},
		{name: "unrecognized state", driver: `{"state":"weird"`, wantState: protocol.DriveStateUnknown},
		{name: "running but unverified", driver: `{"state":"ON","verification":"unverified"`, wantState: protocol.DriveStateRunning},
	}
	for _, testCase := range cases {
		t.Run(testCase.name, func(t *testing.T) {
			document := testCase.driver
			if testCase.driver != `null` {
				document += `}`
			}
			runner := &fakeRunner{out: driveDiscoveryDocument(document)}
			a := newTestAdapter(t, runner)
			result, err := a.Discover(context.Background(), adapter.DiscoverRequest{})
			if err != nil {
				t.Fatalf("discover: %v", err)
			}
			if len(result.Sessions) != 1 {
				t.Fatalf("session count = %d", len(result.Sessions))
			}
			drive := result.Sessions[0].Drive
			if testCase.wantNil {
				if drive != nil {
					t.Fatalf("drive = %#v, want nil for an absent observation", drive)
				}
				return
			}
			if drive == nil {
				t.Fatal("drive summary missing")
			}
			if drive.State != testCase.wantState {
				t.Fatalf("state = %q, want %q", drive.State, testCase.wantState)
			}
			if drive.Verified != testCase.wantVerify {
				t.Fatalf("verified = %t, want %t for state %q", drive.Verified, testCase.wantVerify, drive.State)
			}
		})
	}
}

// TestDiscoverBoundsDriverReason proves a long provider reason cannot grow the
// inventory document without bound.
func TestDiscoverBoundsDriverReason(t *testing.T) {
	reason := ""
	for len(reason) < 200 {
		reason += "é"
	}
	runner := &fakeRunner{out: driveDiscoveryDocument(`{"state":"ON","reason":"` + reason + `"}`)}
	a := newTestAdapter(t, runner)
	result, err := a.Discover(context.Background(), adapter.DiscoverRequest{})
	if err != nil {
		t.Fatalf("discover: %v", err)
	}
	drive := result.Sessions[0].Drive
	if drive == nil {
		t.Fatal("drive summary missing")
	}
	if len(drive.Reason) > 64 {
		t.Fatalf("reason length = %d, want at most 64", len(drive.Reason))
	}
	if drive.Reason == "" {
		t.Fatal("a bounded reason must not become empty")
	}
}

// TestExecuteDriveUsesProviderDriverSubcommands proves the adapter invokes the
// provider's own driver surface and never invents a PID from a cluster
// generation, which is not a provider process identity.
func TestExecuteDriveUsesProviderDriverSubcommands(t *testing.T) {
	cases := []struct {
		operation string
		want      []string
	}{
		{operation: protocol.OperationAgentDriveStart, want: []string{"workspace", "driver", "start", "-s", "s1", "--json"}},
		{operation: protocol.OperationAgentDriveStop, want: []string{"workspace", "driver", "stop", "-s", "s1", "--json"}},
	}
	for _, testCase := range cases {
		t.Run(testCase.operation, func(t *testing.T) {
			runner := &fakeRunner{out: driveDiscoveryDocument(`null`)}
			a := newTestAdapter(t, runner)
			discovered, err := a.Discover(context.Background(), adapter.DiscoverRequest{})
			if err != nil {
				t.Fatalf("discover: %v", err)
			}
			runner.out = []byte(`{"ok":true,"delivery_state":"launched","response":{"state":"ON"}}`)
			_, err = a.Execute(context.Background(), adapter.ExecuteRequest{Intent: protocol.ImmutableIntent{
				CommandID: "c1", Operation: testCase.operation,
				Target: &protocol.CommandTarget{ResourceID: discovered.Sessions[0].SessionID, Generation: "g1"},
			}})
			if err != nil {
				t.Fatalf("execute: %v", err)
			}
			if !reflect.DeepEqual(runner.args, testCase.want) {
				t.Fatalf("argv = %#v, want %#v", runner.args, testCase.want)
			}
		})
	}
}

// TestExecuteDriveMapsProviderOutcomes proves each provider drive outcome keeps
// its real effect certainty, including the unconfirmed case that must never be
// reported as a definite failure.
func TestExecuteDriveMapsProviderOutcomes(t *testing.T) {
	cases := []struct {
		name          string
		document      string
		exitError     bool
		wantOutcome   string
		wantBoundary  protocol.DeliveryBoundary
		wantCertainty protocol.EffectCertainty
		wantExit      bool
		wantError     string
	}{
		{
			name: "launched", document: `{"ok":true,"delivery_state":"launched","response":{"state":"ON"}}`,
			wantOutcome: "succeeded", wantBoundary: protocol.DeliverySubmitted, wantCertainty: protocol.EffectAcknowledged,
		},
		{
			name: "already running", document: `{"ok":true,"delivery_state":"already_running"}`,
			wantOutcome: "succeeded", wantBoundary: protocol.DeliverySubmitted, wantCertainty: protocol.EffectAcknowledged,
		},
		{
			name: "stopped", document: `{"ok":true,"delivery_state":"stopped","response":{"state":"-"}}`,
			wantOutcome: "succeeded", wantBoundary: protocol.DeliverySignalSent, wantCertainty: protocol.EffectAcknowledged, wantExit: true,
		},
		{
			name: "already stopped", document: `{"ok":true,"delivery_state":"already_stopped"}`,
			wantOutcome: "succeeded", wantBoundary: protocol.DeliverySignalSent, wantCertainty: protocol.EffectAcknowledged, wantExit: true,
		},
		{
			name: "rejected", document: `{"ok":false,"exit_code":4,"delivery_state":"rejected","error_code":"preflight_owner_changed"}`, exitError: true,
			wantOutcome: "rejected", wantCertainty: protocol.EffectNotApplied, wantError: "preflight_owner_changed",
		},
		{
			name: "failed", document: `{"ok":false,"exit_code":5,"delivery_state":"failed","error_code":"child_exited"}`, exitError: true,
			wantOutcome: "failed", wantCertainty: protocol.EffectNotApplied, wantError: "child_exited",
		},
		{
			name: "unconfirmed", document: `{"ok":false,"exit_code":6,"delivery_state":"unconfirmed","error_code":"stop_timeout","delivery_unknown":true}`, exitError: true,
			wantOutcome: "unconfirmed", wantCertainty: protocol.EffectUnknown, wantError: "stop_timeout",
		},
	}
	for _, testCase := range cases {
		t.Run(testCase.name, func(t *testing.T) {
			runner := &fakeRunner{out: driveDiscoveryDocument(`null`)}
			a := newTestAdapter(t, runner)
			discovered, err := a.Discover(context.Background(), adapter.DiscoverRequest{})
			if err != nil {
				t.Fatalf("discover: %v", err)
			}
			runner.out = []byte(testCase.document)
			if testCase.exitError {
				runner.err = &exec.ExitError{}
			}
			result, err := a.Execute(context.Background(), adapter.ExecuteRequest{Intent: protocol.ImmutableIntent{
				CommandID: "c1", Operation: protocol.OperationAgentDriveStop,
				Target: &protocol.CommandTarget{ResourceID: discovered.Sessions[0].SessionID, Generation: "g1"},
			}})
			if testCase.exitError && err == nil {
				t.Fatal("a non-zero provider exit must still return an error")
			}
			if !testCase.exitError && err != nil {
				t.Fatalf("execute: %v", err)
			}
			receipt := result.Receipt
			if receipt.Outcome != testCase.wantOutcome {
				t.Fatalf("outcome = %q, want %q", receipt.Outcome, testCase.wantOutcome)
			}
			if receipt.EffectCertainty != testCase.wantCertainty {
				t.Fatalf("effect certainty = %q, want %q", receipt.EffectCertainty, testCase.wantCertainty)
			}
			if receipt.DeliveryBoundary != testCase.wantBoundary {
				t.Fatalf("delivery boundary = %q, want %q", receipt.DeliveryBoundary, testCase.wantBoundary)
			}
			if receipt.ExitConfirmed != testCase.wantExit {
				t.Fatalf("exit confirmed = %t, want %t", receipt.ExitConfirmed, testCase.wantExit)
			}
			if receipt.ErrorCode != testCase.wantError {
				t.Fatalf("error code = %q, want %q", receipt.ErrorCode, testCase.wantError)
			}
			if receipt.ProviderResponse != testCase.document {
				t.Fatalf("provider response = %q, want the provider document", receipt.ProviderResponse)
			}
		})
	}
}

// TestExecuteKeepsStderrWhenStdoutIsNotAProviderDocument proves a non-JSON
// stdout does not mask the provider's stderr diagnostic.
func TestExecuteKeepsStderrWhenStdoutIsNotAProviderDocument(t *testing.T) {
	runner := &fakeRunner{out: driveDiscoveryDocument(`null`)}
	a := newTestAdapter(t, runner)
	discovered, err := a.Discover(context.Background(), adapter.DiscoverRequest{})
	if err != nil {
		t.Fatalf("discover: %v", err)
	}
	runner.out = []byte("not-a-provider-document\n")
	runner.err = &exec.ExitError{Stderr: []byte("provider: driver unavailable\n")}
	result, err := a.Execute(context.Background(), adapter.ExecuteRequest{Intent: protocol.ImmutableIntent{
		CommandID: "c1", Operation: protocol.OperationAgentDriveStart,
		Target: &protocol.CommandTarget{ResourceID: discovered.Sessions[0].SessionID, Generation: "g1"},
	}})
	if err == nil {
		t.Fatal("a failed provider invocation must return an error")
	}
	if result.Receipt.ProviderResponse != "provider: driver unavailable\n" {
		t.Fatalf("provider response = %q, want the stderr diagnostic", result.Receipt.ProviderResponse)
	}
	if result.Receipt.EffectCertainty != protocol.EffectUnknown {
		t.Fatalf("effect certainty = %q, want unknown", result.Receipt.EffectCertainty)
	}
}
