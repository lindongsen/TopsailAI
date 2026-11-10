package main

import (
	"context"
	"strings"
	"testing"

	"topsailai_agent_cluster/internal/protocol"
)

// modelSelectStub serves one session whose inventory generation is configurable,
// and records the catalog reads and admitted intents so a test can prove what the
// standalone surface did before it asked the operator anything.
type modelSelectStub struct {
	generation    string
	catalogReads  []string
	intents       []protocol.ImmutableIntent
	inventoryErr  error
	catalogErr    error
	profiles      []protocol.ModelProfile
	capabilities  []protocol.Capability
	admittedCount int
}

// ListEndpoints returns one endpoint so the model command has a target.
func (s *modelSelectStub) ListEndpoints(context.Context) ([]protocol.Endpoint, error) {
	return []protocol.Endpoint{{EndpointID: "ep"}}, nil
}

// GetInventory returns one session carrying the configured generation.
func (s *modelSelectStub) GetInventory(context.Context, string) (protocol.InventoryReport, error) {
	if s.inventoryErr != nil {
		return protocol.InventoryReport{}, s.inventoryErr
	}
	return protocol.InventoryReport{
		ReportComplete:   true,
		CollectionStatus: protocol.CollectionSucceeded,
		Sessions: []protocol.Session{{
			SessionID:        "session",
			AdapterID:        "adapter-1",
			Generation:       s.generation,
			State:            "running",
			CollectionStatus: protocol.CollectionSucceeded,
		}},
	}, nil
}

// GetCapabilities advertises the model select operation so preflight can pass.
func (s *modelSelectStub) GetCapabilities(context.Context, string) (protocol.CapabilityDescriptor, error) {
	capabilities := s.capabilities
	if capabilities == nil {
		capabilities = []protocol.Capability{{Name: protocol.OperationAgentModelSelect}}
	}
	return protocol.CapabilityDescriptor{Revision: "rev-1", Capabilities: capabilities}, nil
}

// GetCommand returns an immediate terminal result.
func (s *modelSelectStub) GetCommand(context.Context, string) (map[string]any, error) {
	return map[string]any{"status": "finished"}, nil
}

// ListCommands returns no history.
func (s *modelSelectStub) ListCommands(context.Context, string, string, int) ([]map[string]any, error) {
	return nil, nil
}

// GetOutput returns an empty bounded snapshot.
func (s *modelSelectStub) GetOutput(context.Context, string, string, string, int, int) (protocol.OutputSnapshotResponse, error) {
	return protocol.OutputSnapshotResponse{}, nil
}

// AdmitCommand records the intent and returns a durable command identifier.
func (s *modelSelectStub) AdmitCommand(_ context.Context, intent protocol.ImmutableIntent) (map[string]any, error) {
	s.intents = append(s.intents, intent)
	s.admittedCount++
	return map[string]any{"command_id": "cmd-1"}, nil
}

// GetModelCatalog records the generation it was asked with, so a test can prove
// the catalog read already carried the resolved generation.
func (s *modelSelectStub) GetModelCatalog(_ context.Context, _, _, generation string) (protocol.ModelCatalog, error) {
	s.catalogReads = append(s.catalogReads, generation)
	if s.catalogErr != nil {
		return protocol.ModelCatalog{}, s.catalogErr
	}
	profiles := s.profiles
	if profiles == nil {
		profiles = []protocol.ModelProfile{{ModelProfileID: "mp-1", DisplayName: "first", Available: true}}
	}
	return protocol.ModelCatalog{Profiles: profiles, ObservedAtMS: 1700000000000}, nil
}

// TestModelSelectResolvesTheGenerationBeforeAskingForConfirmation proves the
// generation is resolved from the inventory before the catalog read and before
// the confirmation question, so an operator never answers a question and then
// receives a late generation_required rejection.
func TestModelSelectResolvesTheGenerationBeforeAskingForConfirmation(t *testing.T) {
	stub := &modelSelectStub{generation: "gen-7"}
	var output, diagnostics strings.Builder
	err := modelSelectWithProgress(context.Background(), stub, &output, &diagnostics, "ep", "session", "mp-1", true, false, 0, "")
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if len(stub.catalogReads) != 1 {
		t.Fatalf("expected one catalog read, got %d", len(stub.catalogReads))
	}
	if stub.catalogReads[0] != "gen-7" {
		t.Fatalf("the catalog read must already carry the resolved generation, got %q", stub.catalogReads[0])
	}
	if len(stub.intents) != 1 {
		t.Fatalf("expected one admitted intent, got %d", len(stub.intents))
	}
	if got := stub.intents[0].Target.Generation; got != "gen-7" {
		t.Fatalf("the admitted intent must carry the resolved generation, got %q", got)
	}
}

// TestModelSelectRefusesAnUnresolvableGenerationBeforeConfirmation proves an
// inventory that reports no verified generation fails immediately, with a reason
// that names the real cause, instead of submitting and letting the Endpoint
// reject the command after the operator already confirmed.
func TestModelSelectRefusesAnUnresolvableGenerationBeforeConfirmation(t *testing.T) {
	stub := &modelSelectStub{generation: ""}
	var output, diagnostics strings.Builder
	err := modelSelectWithProgress(context.Background(), stub, &output, &diagnostics, "ep", "session", "mp-1", true, false, 0, "")
	if err == nil {
		t.Fatal("expected an error when the inventory reports no verified generation")
	}
	if !strings.Contains(err.Error(), "no verified generation") {
		t.Fatalf("the error must name the real cause, got %q", err.Error())
	}
	if len(stub.catalogReads) != 0 {
		t.Fatalf("the catalog must not be read when the generation cannot be resolved, got %d reads", len(stub.catalogReads))
	}
	if stub.admittedCount != 0 {
		t.Fatalf("no command may be admitted when the generation cannot be resolved, got %d", stub.admittedCount)
	}
}

// TestModelSelectKeepsAnExplicitGeneration proves an explicit --generation skips
// the inventory read entirely, so the new resolution adds no cost to the path
// that already supplied the value.
func TestModelSelectKeepsAnExplicitGeneration(t *testing.T) {
	stub := &modelSelectStub{generation: "gen-from-inventory"}
	var output, diagnostics strings.Builder
	err := modelSelectWithProgress(context.Background(), stub, &output, &diagnostics, "ep", "session", "mp-1", true, false, 0, "gen-explicit")
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if len(stub.catalogReads) != 1 || stub.catalogReads[0] != "gen-explicit" {
		t.Fatalf("the explicit generation must be used unchanged, got %v", stub.catalogReads)
	}
	if len(stub.intents) != 1 || stub.intents[0].Target.Generation != "gen-explicit" {
		t.Fatalf("the admitted intent must carry the explicit generation, got %v", stub.intents)
	}
}

// TestResolveSessionGenerationReportsAnAbsentSessionAsEmpty proves the shared
// lookup distinguishes "the inventory does not list this session" from an error,
// so each caller can apply its own policy instead of the helper guessing.
func TestResolveSessionGenerationReportsAnAbsentSessionAsEmpty(t *testing.T) {
	stub := &modelSelectStub{generation: "gen-1"}
	generation, err := resolveSessionGeneration(context.Background(), stub, "ep", "another-session")
	if err != nil {
		t.Fatalf("an absent session is not an error, got %v", err)
	}
	if generation != "" {
		t.Fatalf("an absent session must report an empty generation, got %q", generation)
	}
}

// TestResolveSessionGenerationPropagatesAnInventoryFailure proves a transport
// failure is reported as an error rather than being flattened into an empty
// generation, which a caller would misread as "the session has no generation".
func TestResolveSessionGenerationPropagatesAnInventoryFailure(t *testing.T) {
	stub := &modelSelectStub{inventoryErr: context.DeadlineExceeded}
	_, err := resolveSessionGeneration(context.Background(), stub, "ep", "session")
	if err == nil {
		t.Fatal("an inventory failure must be reported as an error")
	}
	if !strings.Contains(err.Error(), "deadline exceeded") {
		t.Fatalf("the error must preserve the cause, got %q", err.Error())
	}
}
