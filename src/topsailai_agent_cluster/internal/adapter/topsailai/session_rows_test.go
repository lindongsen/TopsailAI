package topsailai

import (
	"context"
	"reflect"
	"testing"

	"topsailai_agent_cluster/internal/adapter"
	"topsailai_agent_cluster/internal/protocol"
)

// TestDiscoverMapsSiblingProviderRowsToDistinctResources proves one provider
// session can expose independently selectable rows without leaking provider
// selectors into the public cluster identity.
func TestDiscoverMapsSiblingProviderRowsToDistinctResources(t *testing.T) {
	runner := &fakeRunner{out: []byte(`{"items":[` +
		`{"session_id":"shared","filename":"manager.session.stdout","session_name":"work","pid":101,"is_task":false,"process_generation":"g1"},` +
		`{"session_id":"shared","filename":"first.task.stdout","session_name":"work","session_qualifier":"task","pid":101,"is_task":true,"process_generation":"g1"},` +
		`{"session_id":"shared","filename":"second.task.stdout","session_name":"work","session_qualifier":"task","pid":101,"is_task":true,"process_generation":"g1"},` +
		`{"session_id":"shared","filename":"member.session.stdout","session_name":"work","session_qualifier":"member","pid":202,"is_task":false,"process_generation":"g2"}` +
		`]}`)}
	a := newTestAdapter(t, runner)
	result, err := a.Discover(context.Background(), adapter.DiscoverRequest{})
	if err != nil {
		t.Fatal(err)
	}
	if len(result.Sessions) != 4 {
		t.Fatalf("sessions=%#v", result.Sessions)
	}
	seen := make(map[string]bool)
	for _, session := range result.Sessions {
		if seen[session.ClusterSessionID] {
			t.Fatalf("duplicate cluster session ID %q", session.ClusterSessionID)
		}
		seen[session.ClusterSessionID] = true
		if session.ProviderSessionID != "shared" {
			t.Fatalf("provider session ID=%q want shared", session.ProviderSessionID)
		}
	}
	if result.Sessions[1].ProviderSessionQualifier != "task" {
		t.Fatalf("task qualifier=%q", result.Sessions[1].ProviderSessionQualifier)
	}
}

// TestRuntimeLogArgsAddressNormalTaskAndTeamRows proves the adapter expresses
// provider row selection only through the provider's supported CLI contract.
func TestRuntimeLogArgsAddressNormalTaskAndTeamRows(t *testing.T) {
	cases := []struct {
		name   string
		target providerSessionTarget
		follow bool
		want   []string
	}{
		{name: "normal", target: providerSessionTarget{SessionID: "s", PID: 101}, want: []string{"runtime", "logs", "-s", "s", "-p", "101", "-n", "7", "--json"}},
		{name: "subagent task", target: providerSessionTarget{SessionID: "s", PID: 101, IsTask: true}, want: []string{"runtime", "logs", "-s", "s", "-p", "101", "--is-task", "-n", "7", "--json"}},
		{name: "team member follow", target: providerSessionTarget{SessionID: "s", PID: 202}, follow: true, want: []string{"runtime", "logs", "-s", "s", "-p", "202", "-n", "7", "--follow"}},
	}
	for _, testCase := range cases {
		t.Run(testCase.name, func(t *testing.T) {
			if got := runtimeLogArgs(testCase.target, 7, testCase.follow); !reflect.DeepEqual(got, testCase.want) {
				t.Fatalf("args=%q want=%q", got, testCase.want)
			}
		})
	}
}

// TestInspectSelectsTheMappedSiblingRow proves a targeted provider query is
// narrowed again by the adapter-private PID/task selectors before evidence is
// returned to the cluster.
func TestInspectSelectsTheMappedSiblingRow(t *testing.T) {
	runner := &recordingRunner{out: []byte(`{"items":[` +
		`{"session_id":"shared","filename":"manager.stdout","pid":101,"is_task":false,"process_generation":"manager"},` +
		`{"session_id":"shared","filename":"task.stdout","pid":101,"is_task":true,"process_generation":"task"}` +
		`]}`)}
	mapper := newFakeMapper()
	key, err := providerSessionKey(workspaceItem{SessionID: "shared", ProviderRowKey: "task.stdout", PID: 101, IsTask: true})
	if err != nil {
		t.Fatal(err)
	}
	mapping := ResourceMapping{AdapterID: "a1", ProviderKey: key, ResourceID: "res-task"}
	mapper.byKey[key] = mapping
	mapper.byID[mapping.ResourceID] = mapping
	a, err := newWithRunner(Config{AdapterID: "a1", Executable: "/provider", MaxOutput: 4096, ResourceMapper: mapper}, runner)
	if err != nil {
		t.Fatal(err)
	}
	result, err := a.Inspect(context.Background(), adapter.InspectRequest{Target: protocol.CommandTarget{ResourceID: mapping.ResourceID}})
	if err != nil {
		t.Fatal(err)
	}
	if !result.Found || result.ProviderGeneration != "task" {
		t.Fatalf("result=%#v", result)
	}
	want := []string{"workspace", "list", "-s", "shared", "--json"}
	if len(runner.calls) != 1 || !reflect.DeepEqual(runner.calls[0], want) {
		t.Fatalf("calls=%q want=%q", runner.calls, want)
	}
}
