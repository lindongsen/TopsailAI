package tui

import (
	"context"
	"errors"
	"io"
	"strings"
	"testing"

	"topsailai_agent_cluster/internal/protocol"
)

type interactiveStub struct {
	endpoints          []protocol.Endpoint
	reports            map[string]protocol.InventoryReport
	admit              int
	failList           bool
	changeAfter        int
	generationSequence []string
	inventoryCalls     int
}

func (s *interactiveStub) ListEndpoints(context.Context) ([]protocol.Endpoint, error) {
	if s.failList {
		s.failList = false
		return nil, errors.New("temporary list failure")
	}
	return s.endpoints, nil
}
func (s *interactiveStub) GetInventory(_ context.Context, id string) (protocol.InventoryReport, error) {
	s.inventoryCalls++
	report, ok := s.reports[id]
	if !ok {
		return protocol.InventoryReport{}, errors.New("missing inventory")
	}
	if len(s.generationSequence) > 0 {
		index := s.inventoryCalls - 1
		if index >= len(s.generationSequence) {
			index = len(s.generationSequence) - 1
		}
		report.Sessions = append([]protocol.Session(nil), report.Sessions...)
		report.Sessions[0].Generation = s.generationSequence[index]
	} else if s.changeAfter > 0 && s.inventoryCalls >= s.changeAfter {
		report.Sessions = append([]protocol.Session(nil), report.Sessions...)
		report.Sessions[0].Generation = "generation-2"
	}
	return report, nil
}
func (s *interactiveStub) GetCapabilities(context.Context, string) (protocol.CapabilityDescriptor, error) {
	return protocol.CapabilityDescriptor{Revision: "r1", Capabilities: []protocol.Capability{{Name: protocol.OperationMessageSend}}}, nil
}
func (s *interactiveStub) GetCommand(context.Context, string) (map[string]any, error) {
	return map[string]any{"status": string(protocol.StatusFinished)}, nil
}
func (s *interactiveStub) ListCommands(context.Context, string, string, int) ([]map[string]any, error) {
	return nil, nil
}
func (s *interactiveStub) GetOutput(context.Context, string, string, string, int) (protocol.OutputSnapshotResponse, error) {
	return protocol.OutputSnapshotResponse{Data: "log\x1b[31m"}, nil
}
func (s *interactiveStub) AdmitCommand(context.Context, protocol.ImmutableIntent) (map[string]any, error) {
	s.admit++
	return map[string]any{"command_id": "cmd-1"}, nil
}

func testInventory() protocol.InventoryReport {
	return protocol.InventoryReport{ReportComplete: true, CollectionStatus: protocol.CollectionSucceeded, Adapters: []protocol.AdapterSummary{{AdapterID: "adapter-1", DataKnown: true, CollectionStatus: protocol.CollectionSucceeded}}, Sessions: []protocol.Session{{SessionID: "session-1", AdapterID: "adapter-1", Generation: "generation-1", State: "running", CollectionStatus: protocol.CollectionSucceeded}}}
}

func TestInteractiveListUsesTableHeaders(t *testing.T) {
	stub := &interactiveStub{endpoints: []protocol.Endpoint{{EndpointID: "endpoint-1"}}, reports: map[string]protocol.InventoryReport{"endpoint-1": testInventory()}}
	var output, diagnostics strings.Builder
	if err := RunInteractive(context.Background(), stub, strings.NewReader("list\nquit\n"), &output, &diagnostics, InteractiveOptions{}); err != nil {
		t.Fatal(err)
	}
	for _, header := range tableHeaders {
		if !strings.Contains(output.String(), header) {
			t.Fatalf("interactive list missing header %q: %q", header, output.String())
		}
	}
}

func TestInteractiveLoopContinuesAfterErrorAndQuit(t *testing.T) {
	stub := &interactiveStub{endpoints: []protocol.Endpoint{{EndpointID: "endpoint-1"}}, reports: map[string]protocol.InventoryReport{"endpoint-1": testInventory()}, failList: true}
	var output, errorsOut strings.Builder
	err := RunInteractive(context.Background(), stub, strings.NewReader("bad\nhelp\nquit\n"), &output, &errorsOut, InteractiveOptions{LineLimit: 128})
	if err != nil {
		t.Fatalf("RunInteractive: %v", err)
	}
	if !strings.Contains(errorsOut.String(), `unknown command "bad"`) || !strings.Contains(output.String(), "commands:") {
		t.Fatalf("recovery output missing: out=%q err=%q", output.String(), errorsOut.String())
	}
	if !strings.Contains(output.String(), "cluster> ") {
		t.Fatalf("prompt missing: %q", output.String())
	}
}

func TestInteractiveUseChangesPromptAndEOFIsSuccessful(t *testing.T) {
	stub := &interactiveStub{endpoints: []protocol.Endpoint{{EndpointID: "endpoint-1"}}, reports: map[string]protocol.InventoryReport{"endpoint-1": testInventory()}}
	var output, errorsOut strings.Builder
	err := RunInteractive(context.Background(), stub, strings.NewReader("use endpoint-1 session-1\nstatus\n"), &output, &errorsOut, InteractiveOptions{})
	if err != nil {
		t.Fatalf("RunInteractive: %v", err)
	}
	if !strings.Contains(output.String(), "cluster[endpoint-1/session-1]> ") || !strings.Contains(output.String(), "running") {
		t.Fatalf("state output missing: %q", output.String())
	}
}

func TestInteractiveSendDeclineDoesNotAdmitAndEscapeIsFiltered(t *testing.T) {
	stub := &interactiveStub{endpoints: []protocol.Endpoint{{EndpointID: "endpoint-1"}}, reports: map[string]protocol.InventoryReport{"endpoint-1": testInventory()}}
	var output, errorsOut strings.Builder
	err := RunInteractive(context.Background(), stub, strings.NewReader("use endpoint-1 session-1\nsend {\"text\":\"hi\"}\nn\nlogs\nquit\n"), &output, &errorsOut, InteractiveOptions{})
	if err != nil {
		t.Fatalf("RunInteractive: %v", err)
	}
	if stub.admit != 0 {
		t.Fatalf("declined send admitted %d commands", stub.admit)
	}
	if strings.Contains(output.String(), "\x1b") {
		t.Fatalf("terminal escape leaked: %q", output.String())
	}
}

func TestInteractiveRejectsNilStreams(t *testing.T) {
	if err := RunInteractive(context.Background(), &interactiveStub{}, nil, io.Discard, io.Discard, InteractiveOptions{}); err == nil {
		t.Fatal("expected nil reader error")
	}
}

func TestInteractiveCommandsCoverShowLogsRefreshAndSend(t *testing.T) {
	stub := &interactiveStub{endpoints: []protocol.Endpoint{{EndpointID: "endpoint-1"}}, reports: map[string]protocol.InventoryReport{"endpoint-1": testInventory()}}
	var output, errorsOut strings.Builder
	input := "use endpoint-1 session-1\nshow\nlogs\nrefresh\nsend {\"text\":\"hi\"}\ny\nstatus cmd-1\nquit\n"
	if err := RunInteractive(context.Background(), stub, strings.NewReader(input), &output, &errorsOut, InteractiveOptions{}); err != nil {
		t.Fatal(err)
	}
	if stub.admit != 1 || !strings.Contains(output.String(), "command submitted") || !strings.Contains(output.String(), "running") {
		t.Fatalf("unexpected output=%q errors=%q admits=%d", output.String(), errorsOut.String(), stub.admit)
	}
}

func TestInteractiveLineLimitAndClear(t *testing.T) {
	stub := &interactiveStub{endpoints: []protocol.Endpoint{{EndpointID: "endpoint-1"}}, reports: map[string]protocol.InventoryReport{"endpoint-1": testInventory()}}
	var output, errorsOut strings.Builder
	input := "xxxxxxxxxxxx\nuse endpoint-1 session-1\nuse clear\nquit\n"
	if err := RunInteractive(context.Background(), stub, strings.NewReader(input), &output, &errorsOut, InteractiveOptions{LineLimit: 4}); err != nil {
		t.Fatal(err)
	}
	if !strings.Contains(errorsOut.String(), "exceeds") || !strings.Contains(output.String(), "cluster>") {
		t.Fatalf("limit/clear not covered: %q %q", output.String(), errorsOut.String())
	}
}

func TestSanitizeTerminalControls(t *testing.T) {
	clean := sanitizeTerminal([]byte("a\x1b[31mb\r\x00\u202e c\n"))
	if strings.ContainsAny(clean, "\x1b\r\x00") || strings.Contains(clean, "\u202e") {
		t.Fatalf("unsafe output: %q", clean)
	}
}

type shortWriter struct{ target strings.Builder }

func (w *shortWriter) Write(data []byte) (int, error) {
	n := 1
	if len(data) < n {
		n = len(data)
	}
	w.target.Write(data[:n])
	return n, nil
}
func TestSafeWriterHandlesShortWrites(t *testing.T) {
	var target shortWriter
	writer := newSafeWriter(&target)
	if _, err := writer.Write([]byte("hello\n")); err != nil {
		t.Fatal(err)
	}
	if target.target.String() != "hello\n" {
		t.Fatalf("short write lost data: %q", target.target.String())
	}
}

func TestInteractiveGenerationChangePreventsAdmission(t *testing.T) {
	stub := &interactiveStub{endpoints: []protocol.Endpoint{{EndpointID: "endpoint-1"}}, reports: map[string]protocol.InventoryReport{"endpoint-1": testInventory()}, changeAfter: 2}
	var output, errorsOut strings.Builder
	if err := RunInteractive(context.Background(), stub, strings.NewReader("use endpoint-1 session-1\nsend {\"text\":\"hi\"}\ny\nquit\n"), &output, &errorsOut, InteractiveOptions{}); err != nil {
		t.Fatal(err)
	}
	if stub.admit != 0 {
		t.Fatalf("generation change admitted %d commands", stub.admit)
	}
	if !strings.Contains(errorsOut.String(), "generation changed") {
		t.Fatalf("missing generation error: %q", errorsOut.String())
	}
}
func TestInteractiveShowRejectsSelectedGenerationChange(t *testing.T) {
	stub := &interactiveStub{
		endpoints:   []protocol.Endpoint{{EndpointID: "endpoint-1"}},
		reports:     map[string]protocol.InventoryReport{"endpoint-1": testInventory()},
		changeAfter: 2,
	}
	var output, errorsOut strings.Builder
	input := "use endpoint-1 session-1\nshow\nquit\n"
	if err := RunInteractive(context.Background(), stub, strings.NewReader(input), &output, &errorsOut, InteractiveOptions{}); err != nil {
		t.Fatal(err)
	}
	if !strings.Contains(errorsOut.String(), "selected session generation changed; use the session again") {
		t.Fatalf("missing generation fencing error: %q", errorsOut.String())
	}
	if strings.Contains(output.String(), "session: session-1 adapter=") {
		t.Fatalf("show returned details after generation change: %q", output.String())
	}
	if stub.inventoryCalls != 2 {
		t.Fatalf("inventory calls=%d want=2", stub.inventoryCalls)
	}
}

func TestReplacementInvalidationIsStickyAndRequiresUse(t *testing.T) {
	stub := &interactiveStub{
		endpoints:          []protocol.Endpoint{{EndpointID: "endpoint-1"}},
		reports:            map[string]protocol.InventoryReport{"endpoint-1": testInventory()},
		generationSequence: []string{"generation-1", "generation-2", "generation-1", "generation-1", "generation-1"},
	}
	var output, errorsOut strings.Builder
	input := "use endpoint-1 session-1\nrefresh\nrefresh\nuse endpoint-1 session-1\nstatus\nquit\n"
	if err := RunInteractive(context.Background(), stub, strings.NewReader(input), &output, &errorsOut, InteractiveOptions{}); err != nil {
		t.Fatal(err)
	}
	if !strings.Contains(output.String(), "cluster[endpoint-1/session-1!]> ") {
		t.Fatalf("missing invalidated prompt: %q", output.String())
	}
	if strings.Count(errorsOut.String(), "selected session generation changed; use the session again") != 1 {
		t.Fatalf("unexpected generation errors: %q", errorsOut.String())
	}
	if !strings.Contains(errorsOut.String(), "selected session invalidated; use the session again") {
		t.Fatalf("missing sticky invalidation error: %q", errorsOut.String())
	}
	if !strings.Contains(output.String(), "running") {
		t.Fatalf("explicit use did not restore operation: %q", output.String())
	}
}

func TestInvalidatedSelectionRejectsTargetOperationsWithoutAdmission(t *testing.T) {
	stub := &interactiveStub{
		endpoints:          []protocol.Endpoint{{EndpointID: "endpoint-1"}},
		reports:            map[string]protocol.InventoryReport{"endpoint-1": testInventory()},
		generationSequence: []string{"generation-1", "generation-2"},
	}
	var output, errorsOut strings.Builder
	input := "use endpoint-1 session-1\nrefresh\nshow\nlogs\nstatus\nsend {\"text\":\"blocked\"}\ny\nquit\n"
	if err := RunInteractive(context.Background(), stub, strings.NewReader(input), &output, &errorsOut, InteractiveOptions{}); err != nil {
		t.Fatal(err)
	}
	if stub.admit != 0 {
		t.Fatalf("invalidated send admitted %d commands", stub.admit)
	}
	if strings.Count(errorsOut.String(), "selected session invalidated; use the session again") != 4 {
		t.Fatalf("unexpected invalidation errors: %q", errorsOut.String())
	}
}
