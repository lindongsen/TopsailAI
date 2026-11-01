package main

import (
	"context"
	"strings"
	"testing"

	"topsailai_agent_cluster/internal/protocol"
	"topsailai_agent_cluster/internal/tui"
)

func TestInteractiveRejectsNonTerminalBeforeNetwork(t *testing.T) {
	err := runWithIO([]string{"--server-url", "http://127.0.0.1:1", "interactive"}, strings.NewReader("quit\n"), &strings.Builder{}, &strings.Builder{}, false)
	if err == nil || err.Error() != "interactive mode requires a terminal on stdin" {
		t.Fatalf("unexpected non-terminal result: %v", err)
	}
}

type sharedPathStub struct {
	calls   []string
	intents []protocol.ImmutableIntent
}

func (s *sharedPathStub) ListEndpoints(context.Context) ([]protocol.Endpoint, error) {
	s.calls = append(s.calls, "list")
	return []protocol.Endpoint{{EndpointID: "ep"}}, nil
}
func (s *sharedPathStub) GetInventory(context.Context, string) (protocol.InventoryReport, error) {
	s.calls = append(s.calls, "inventory")
	return protocol.InventoryReport{CollectionStatus: protocol.CollectionSucceeded}, nil
}
func (s *sharedPathStub) GetCapabilities(context.Context, string) (protocol.CapabilityDescriptor, error) {
	s.calls = append(s.calls, "capabilities")
	return protocol.CapabilityDescriptor{}, nil
}
func (s *sharedPathStub) GetCommand(context.Context, string) (map[string]any, error) {
	s.calls = append(s.calls, "command")
	return map[string]any{"status": "finished"}, nil
}
func (s *sharedPathStub) ListCommands(context.Context, string, string, int) ([]map[string]any, error) {
	s.calls = append(s.calls, "history")
	return nil, nil
}
func (s *sharedPathStub) GetOutput(context.Context, string, string, string, int) (protocol.OutputSnapshotResponse, error) {
	s.calls = append(s.calls, "output")
	return protocol.OutputSnapshotResponse{}, nil
}
func (s *sharedPathStub) AdmitCommand(_ context.Context, intent protocol.ImmutableIntent) (map[string]any, error) {
	s.calls = append(s.calls, "admit")
	s.intents = append(s.intents, intent)
	return map[string]any{"command_id": "cmd-1"}, nil
}

func TestLegacyAndInteractiveShowUseSharedRunnerMethods(t *testing.T) {
	legacy := &sharedPathStub{}
	var legacyOut strings.Builder
	if err := show(context.Background(), legacy, &legacyOut, "ep", false); err != nil {
		t.Fatal(err)
	}
	interactive := &sharedPathStub{}
	var interactiveOut, interactiveErr strings.Builder
	if err := tui.RunInteractive(context.Background(), interactive, strings.NewReader("show ep\nquit\n"), &interactiveOut, &interactiveErr, tui.InteractiveOptions{}); err != nil {
		t.Fatal(err)
	}
	if got, want := strings.Join(legacy.calls, ","), "list,inventory,capabilities,history"; got != want {
		t.Fatalf("legacy calls=%q want=%q", got, want)
	}
	if got, want := strings.Join(interactive.calls, ","), "list,inventory,capabilities,history"; got != want {
		t.Fatalf("interactive calls=%q want=%q", got, want)
	}
}

func TestLegacyActionAndInteractiveSendShareIntentFields(t *testing.T) {
	legacy := &actionPathStub{}
	var legacyOut strings.Builder
	if err := action(context.Background(), legacy, &legacyOut, []string{"send", "ep", "session", `{"text":"hi"}`, "gen"}, true, false, 100, "", ""); err != nil {
		t.Fatal(err)
	}
	interactive := &actionPathStub{}
	var interactiveOut, interactiveErr strings.Builder
	input := "use ep session\nsend {\"text\":\"hi\"}\ny\nquit\n"
	if err := tui.RunInteractive(context.Background(), interactive, strings.NewReader(input), &interactiveOut, &interactiveErr, tui.InteractiveOptions{WaitTimeoutMS: 100}); err != nil {
		t.Fatal(err)
	}
	if len(legacy.intents) != 1 || len(interactive.intents) != 1 {
		t.Fatalf("intent counts legacy=%d interactive=%d", len(legacy.intents), len(interactive.intents))
	}
	left, right := legacy.intents[0], interactive.intents[0]
	if left.EndpointID != right.EndpointID || left.Operation != right.Operation || string(left.Payload) != string(right.Payload) || left.Target == nil || right.Target == nil || left.Target.ResourceID != right.Target.ResourceID || left.Target.Generation != right.Target.Generation {
		t.Fatalf("intent mismatch legacy=%+v interactive=%+v", left, right)
	}
}

type actionPathStub struct {
	intents []protocol.ImmutableIntent
}

func (s *actionPathStub) ListEndpoints(context.Context) ([]protocol.Endpoint, error) {
	return []protocol.Endpoint{{EndpointID: "ep"}}, nil
}
func (s *actionPathStub) GetInventory(context.Context, string) (protocol.InventoryReport, error) {
	return protocol.InventoryReport{ReportComplete: true, CollectionStatus: protocol.CollectionSucceeded, Sessions: []protocol.Session{{SessionID: "session", Generation: "gen", State: "running"}}}, nil
}
func (s *actionPathStub) GetCapabilities(context.Context, string) (protocol.CapabilityDescriptor, error) {
	return protocol.CapabilityDescriptor{Revision: "rev-1", Capabilities: []protocol.Capability{{Name: protocol.OperationMessageSend}}}, nil
}
func (s *actionPathStub) GetCommand(context.Context, string) (map[string]any, error) {
	return map[string]any{"status": "finished"}, nil
}
func (s *actionPathStub) ListCommands(context.Context, string, string, int) ([]map[string]any, error) {
	return nil, nil
}
func (s *actionPathStub) GetOutput(context.Context, string, string, string, int) (protocol.OutputSnapshotResponse, error) {
	return protocol.OutputSnapshotResponse{}, nil
}
func (s *actionPathStub) AdmitCommand(_ context.Context, intent protocol.ImmutableIntent) (map[string]any, error) {
	s.intents = append(s.intents, intent)
	return map[string]any{"command_id": "cmd-1"}, nil
}
