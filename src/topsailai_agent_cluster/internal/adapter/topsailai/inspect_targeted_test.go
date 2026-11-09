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
	mapper.byKey["provider-session"] = ResourceMapping{AdapterID: "a1", ProviderKey: "provider-session", ResourceID: "res_provider-session"}
	mapper.byID["res_provider-session"] = mapper.byKey["provider-session"]
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
	result, err := a.Inspect(context.Background(), adapter.InspectRequest{Target: protocol.CommandTarget{ResourceID: "res_provider-session", Generation: "g7"}})
	if err != nil {
		t.Fatal(err)
	}
	if !result.Found || result.Generation != "g7" || result.State != "running" {
		t.Fatalf("inspect result=%#v", result)
	}
	if len(runner.calls) != 1 {
		t.Fatalf("provider invocations=%d, want 1: %q", len(runner.calls), runner.calls)
	}
	want := []string{"workspace", "list", "-s", "provider-session", "--json", "--local"}
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
	result, err := a.Inspect(context.Background(), adapter.InspectRequest{Target: protocol.CommandTarget{ResourceID: "res_provider-session", Generation: "g7"}})
	if err != nil {
		t.Fatalf("absence must not be an error: %v", err)
	}
	if result.Found {
		t.Fatalf("absent resource reported as found: %#v", result)
	}
}
