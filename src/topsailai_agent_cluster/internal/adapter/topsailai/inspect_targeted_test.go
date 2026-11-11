package topsailai

import (
	"context"
	"testing"

	"topsailai_agent_cluster/internal/adapter"
	"topsailai_agent_cluster/internal/protocol"
)

// recordingRunner records every provider invocation so a test can prove which
// argv the adapter actually issued, not only the most recent one.
type recordingRunner struct {
	calls [][]string
	out   []byte
	err   error
}

func (r *recordingRunner) Run(_ context.Context, _ string, args []string, _ []byte) ([]byte, error) {
	r.calls = append(r.calls, append([]string(nil), args...))
	return r.out, r.err
}

// newInspectAdapter builds an adapter whose mapper already knows one resource,
// so Inspect can resolve the provider key without a discovery round trip.
func newInspectAdapter(t *testing.T, runner *recordingRunner) *Adapter {
	t.Helper()
	mapper := newFakeMapper()
	providerKey, err := providerSessionKey(workspaceItem{SessionID: "provider-session"})
	if err != nil {
		t.Fatal(err)
	}
	mapping := ResourceMapping{AdapterID: "a1", ProviderKey: providerKey, ResourceID: "res_provider-session"}
	mapper.byKey[providerKey] = mapping
	mapper.byID[mapping.ResourceID] = mapping
	result, err := newWithRunner(Config{AdapterID: "a1", Executable: "/provider", MaxOutput: 4096, ResourceMapper: mapper, PlatformProbe: func() (PlatformCapabilities, error) {
		return PlatformCapabilities{ProcAvailable: true, PidfdAvailable: true}, nil
	}}, runner)
	if err != nil {
		t.Fatal(err)
	}
	return result
}

// TestInspectUsesTargetedProviderQuery proves Inspect asks the provider about the
// single requested session instead of scanning the complete workspace history.
// A full discovery costs seconds per command, so a regression here silently
// restores that latency on every targeted command.
func TestInspectUsesTargetedProviderQuery(t *testing.T) {
	runner := &recordingRunner{out: []byte(`{"items":[{"session_id":"provider-session","process_generation":"g7","status":"running"}]}`)}
	a := newInspectAdapter(t, runner)
	result, err := a.Inspect(context.Background(), adapter.InspectRequest{Target: protocol.CommandTarget{ResourceID: "res_provider-session", ProviderGeneration: "g7"}})
	if err != nil {
		t.Fatal(err)
	}
	if !result.Found || result.ProviderGeneration != "g7" || result.State != "running" {
		t.Fatalf("inspect result=%#v", result)
	}
	if len(runner.calls) != 1 {
		t.Fatalf("provider invocations=%d, want 1: %q", len(runner.calls), runner.calls)
	}
	// --local must be absent: a session recorded on another host is invisible to a
	// local read, and resume authorizes on the absence of a live target, so a local
	// read would report that session as not found and admit the resume anyway.
	want := []string{"workspace", "list", "-s", "provider-session", "--json"}
	if got := runner.calls[0]; len(got) != len(want) {
		t.Fatalf("argv=%q want=%q", got, want)
	} else {
		for i := range want {
			if got[i] != want[i] {
				t.Fatalf("argv=%q want=%q", got, want)
			}
		}
	}
}

// TestInspectReportsAbsenceWithoutError proves an empty targeted result is a
// legitimate absence. Reporting it as an error would make the caller treat
// "not found" as "could not observe" and permanently block operations that
// authorize on absence, such as agent.resume.
func TestInspectReportsAbsenceWithoutError(t *testing.T) {
	runner := &recordingRunner{out: []byte(`{"items":[]}`)}
	a := newInspectAdapter(t, runner)
	result, err := a.Inspect(context.Background(), adapter.InspectRequest{Target: protocol.CommandTarget{ResourceID: "res_provider-session", ProviderGeneration: "g7"}})
	if err != nil {
		t.Fatalf("absence must not be an error: %v", err)
	}
	if result.Found {
		t.Fatalf("absent resource reported as found: %#v", result)
	}
}

// TestInspectReportsCrossHostSessionAsFoundNotLive proves a session recorded on
// another host is found but not live, so resume can reach it.
//
// The provider reports process_generation as null for such a row, because this
// host cannot verify a process it cannot see. Reporting it as not found would be
// wrong in the other direction: the record exists, and resume authorizes on the
// absence of a live target, so a not-found answer would admit the resume while
// claiming the target does not exist. A task directory shared between hosts is
// exactly the case where resuming another host's session is intended.
func TestInspectReportsCrossHostSessionAsFoundNotLive(t *testing.T) {
	runner := &recordingRunner{out: []byte(`{"items":[{"session_id":"provider-session","process_generation":null,"status":"idle","hostname":"other-host"}]}`)}
	a := newInspectAdapter(t, runner)
	result, err := a.Inspect(context.Background(), adapter.InspectRequest{Target: protocol.CommandTarget{ResourceID: "res_provider-session"}})
	if err != nil {
		t.Fatal(err)
	}
	if !result.Found {
		t.Fatalf("cross-host record must be found: %#v", result)
	}
	if result.Live {
		t.Fatalf("cross-host record must not be live: %#v", result)
	}
	if result.ProviderGeneration != "" {
		t.Fatalf("cross-host record must report no generation: %#v", result)
	}
	if result.State != "idle" {
		t.Fatalf("state=%q want idle", result.State)
	}
}

// TestInspectReportsLiveSessionAsLive proves a session whose process is verified
// to hold the output file is reported live, so resume refuses it. Without this
// guard a resume would start a second process against a session already running.
func TestInspectReportsLiveSessionAsLive(t *testing.T) {
	runner := &recordingRunner{out: []byte(`{"items":[{"session_id":"provider-session","process_generation":"g7","status":"running"}]}`)}
	a := newInspectAdapter(t, runner)
	result, err := a.Inspect(context.Background(), adapter.InspectRequest{Target: protocol.CommandTarget{ResourceID: "res_provider-session"}})
	if err != nil {
		t.Fatal(err)
	}
	if !result.Found || !result.Live {
		t.Fatalf("live session must be found and live: %#v", result)
	}
	if result.ProviderGeneration != "g7" {
		t.Fatalf("generation=%q want g7", result.ProviderGeneration)
	}
}
