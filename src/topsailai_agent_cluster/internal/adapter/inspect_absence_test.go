package adapter

import (
	"context"
	"testing"

	"topsailai_agent_cluster/internal/protocol"
)

// TestCommandAdapterInspectReportsAbsenceWithoutError proves the command adapter
// reports an absent resource as a legitimate absence rather than an observation
// failure. The caller distinguishes the two: an error becomes
// target_observation_failed, while Found=false is the authoritative absence that
// authorizes operations such as agent.resume. Returning an error here made
// resume permanently unreachable for every command/fixture adapter.
func TestCommandAdapterInspectReportsAbsenceWithoutError(t *testing.T) {
	t.Setenv("AGENT_CLUSTER_COMMAND_HELPER", "1")
	t.Setenv("AGENT_CLUSTER_COMMAND_HELPER_OUTPUT", "discover")
	a := commandAdapterForTest(t, commandMapper{mapping: ResourceMapping{AdapterID: "adapter-1", ProviderKey: "native-1", ResourceID: "res-1"}})
	result, err := a.Inspect(context.Background(), InspectRequest{Target: protocol.CommandTarget{ResourceID: "res-absent", ProviderGeneration: "gen-1"}})
	if err != nil {
		t.Fatalf("absence must not be an error: %v", err)
	}
	if result.Found {
		t.Fatalf("absent resource reported as found: %#v", result)
	}
}

// TestCommandAdapterInspectDoesNotRequireGeneration proves the command adapter
// accepts a target without a generation, matching the TopsailAI adapter.
//
// Resume authorizes on the absence of a live target, and a history row has no
// generation because the session is not running. Demanding one here made the two
// adapters disagree: the same resume request would be admitted through one adapter
// and rejected before the provider was ever asked through the other.
func TestCommandAdapterInspectDoesNotRequireGeneration(t *testing.T) {
	t.Setenv("AGENT_CLUSTER_COMMAND_HELPER", "1")
	t.Setenv("AGENT_CLUSTER_COMMAND_HELPER_OUTPUT", "discover-listed")
	a := commandAdapterForTest(t, commandMapper{mapping: ResourceMapping{AdapterID: "adapter-1", ProviderKey: "native-1", ResourceID: "res-1"}})
	result, err := a.Inspect(context.Background(), InspectRequest{Target: protocol.CommandTarget{ResourceID: "res-1"}})
	if err != nil {
		t.Fatalf("a target without a generation must be accepted: %v", err)
	}
	if !result.Found {
		t.Fatalf("listed resource reported as absent: %#v", result)
	}
	if result.Live {
		t.Fatalf("resource without a generation must not be live: %#v", result)
	}
}
