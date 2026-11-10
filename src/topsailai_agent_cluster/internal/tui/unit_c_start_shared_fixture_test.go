package tui

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"io"
	"sync"

	"topsailai_agent_cluster/internal/protocol"
)

// unitCAPICounts records every shared API method invocation.
type unitCAPICounts struct {
	List, Inventory, Capability, Command, ListCommands, Output, Admit int
}

// unitCAPI is a locked provider-neutral fake for Unit C lifecycle assertions.
type unitCAPI struct {
	mu          sync.Mutex
	counts      unitCAPICounts
	endpoints   []protocol.Endpoint
	reports     map[string]protocol.InventoryReport
	descriptor  protocol.CapabilityDescriptor
	intents     []protocol.ImmutableIntent
	admitResult map[string]any
	listErr     error
	capErr      error
	admitErr    error
	commandErr  error
}

// newUnitCAPI returns a deterministic endpoint and inventory fixture.
func newUnitCAPI() *unitCAPI {
	return &unitCAPI{
		endpoints: []protocol.Endpoint{{EndpointID: "endpoint-1", Hostname: "host-1"}},
		reports: map[string]protocol.InventoryReport{
			"endpoint-1": startupInventory(),
		},
		descriptor: protocol.CapabilityDescriptor{
			Revision:     "cap-live-2",
			Capabilities: []protocol.Capability{{Name: protocol.OperationAgentStart}},
		},
		admitResult: map[string]any{"command_id": "unit-c-command"},
	}
}

// ListEndpoints returns detached endpoint fixtures and records the call.
func (a *unitCAPI) ListEndpoints(context.Context) ([]protocol.Endpoint, error) {
	a.mu.Lock()
	defer a.mu.Unlock()
	a.counts.List++
	if a.listErr != nil {
		return nil, a.listErr
	}
	return append([]protocol.Endpoint(nil), a.endpoints...), nil
}

// GetInventory returns a detached inventory fixture and records the call.
func (a *unitCAPI) GetInventory(_ context.Context, id string) (protocol.InventoryReport, error) {
	a.mu.Lock()
	defer a.mu.Unlock()
	a.counts.Inventory++
	report, ok := a.reports[id]
	if !ok {
		return protocol.InventoryReport{}, errors.New("missing inventory")
	}
	return report, nil
}

// GetCapabilities returns the configured capability descriptor and records the call.
func (a *unitCAPI) GetCapabilities(context.Context, string) (protocol.CapabilityDescriptor, error) {
	a.mu.Lock()
	defer a.mu.Unlock()
	a.counts.Capability++
	if a.capErr != nil {
		return protocol.CapabilityDescriptor{}, a.capErr
	}
	return a.descriptor, nil
}

// GetCommand returns an immediate terminal command result and records the call.
func (a *unitCAPI) GetCommand(context.Context, string) (map[string]any, error) {
	a.mu.Lock()
	defer a.mu.Unlock()
	a.counts.Command++
	if a.commandErr != nil {
		return nil, a.commandErr
	}
	return map[string]any{"status": string(protocol.StatusFinished)}, nil
}

// ListCommands returns no history and records the call.
func (a *unitCAPI) ListCommands(context.Context, string, string, int) ([]map[string]any, error) {
	a.mu.Lock()
	defer a.mu.Unlock()
	a.counts.ListCommands++
	return nil, nil
}

// GetOutput returns an empty bounded output snapshot and records the call.
func (a *unitCAPI) GetOutput(context.Context, string, string, string, int, int) (protocol.OutputSnapshotResponse, error) {
	a.mu.Lock()
	defer a.mu.Unlock()
	a.counts.Output++
	return protocol.OutputSnapshotResponse{}, nil
}

// AdmitCommand stores a detached immutable intent and records the call.
func (a *unitCAPI) AdmitCommand(_ context.Context, intent protocol.ImmutableIntent) (map[string]any, error) {
	a.mu.Lock()
	defer a.mu.Unlock()
	a.counts.Admit++
	copyIntent := intent
	copyIntent.Payload = append(json.RawMessage(nil), intent.Payload...)
	if intent.Target != nil {
		target := *intent.Target
		copyIntent.Target = &target
	}
	a.intents = append(a.intents, copyIntent)
	if a.admitErr != nil {
		return nil, a.admitErr
	}
	return a.admitResult, nil
}

// snapshot returns a point-in-time copy of all API counters and intents.
func (a *unitCAPI) snapshot() (unitCAPICounts, []protocol.ImmutableIntent) {
	a.mu.Lock()
	defer a.mu.Unlock()
	return a.counts, append([]protocol.ImmutableIntent(nil), a.intents...)
}

// admitCount returns the number of submitted intents.
func (a *unitCAPI) admitCount() int {
	a.mu.Lock()
	defer a.mu.Unlock()
	return a.counts.Admit
}

func unitCAPIAdd(before, after unitCAPICounts) unitCAPICounts {
	return unitCAPICounts{List: after.List - before.List, Inventory: after.Inventory - before.Inventory, Capability: after.Capability - before.Capability, Command: after.Command - before.Command, ListCommands: after.ListCommands - before.ListCommands, Output: after.Output - before.Output, Admit: after.Admit - before.Admit}
}

func seedUnitCState() interactiveState {
	last := int64(123)
	return interactiveState{
		interactiveSelection: interactiveSelection{EndpointID: "endpoint-1", ClusterSessionID: "session-1", ProviderGeneration: "generation-1", Rows: map[int]SessionRow{1: {No: 1, EndpointID: "endpoint-1", ClusterSessionID: "session-1", ProviderGeneration: "generation-1", LastSuccessAtMS: &last}}},
		Scope:                ScopeState{Kind: ScopeEndpoint, EndpointID: "endpoint-1", Hostname: "host-1", ProviderGeneration: "generation-1"},
		commandID:            "existing-command",
	}
}

func cloneUnitCState(state interactiveState) interactiveState {
	copyState := state
	if state.Rows != nil {
		copyState.Rows = make(map[int]SessionRow, len(state.Rows))
		for key, row := range state.Rows {
			copyRow := row
			if row.LastSuccessAtMS != nil {
				value := *row.LastSuccessAtMS
				copyRow.LastSuccessAtMS = &value
			}
			copyState.Rows[key] = copyRow
		}
	}
	return copyState
}

func unitCStartCancelLines(field startDraftField) <-chan lineReadResult {
	lines := make(chan lineReadResult, int(field)+1)
	for _, answer := range []string{"endpoint-1", "resource-1", "profile-1"}[:int(field)] {
		lines <- lineReadResult{line: answer}
	}
	lines <- lineReadResult{line: "cancel"}
	return lines
}

type unitCClosableReader struct {
	reader     io.Reader
	closeCalls int
}

func (r *unitCClosableReader) Read(p []byte) (int, error) { return r.reader.Read(p) }
func (r *unitCClosableReader) Close() error               { r.closeCalls++; return nil }

type unitCCountingReader struct {
	reader io.Reader
	reads  int
}

func (r *unitCCountingReader) Read(p []byte) (int, error) { r.reads++; return r.reader.Read(p) }

type unitCFailingReader struct {
	first bool
	err   error
}

type unitCSynchronizedBuffer struct {
	mu sync.Mutex
	bytes.Buffer
}

func (b *unitCSynchronizedBuffer) Write(p []byte) (int, error) {
	b.mu.Lock()
	defer b.mu.Unlock()
	return b.Buffer.Write(p)
}

func (b *unitCSynchronizedBuffer) WriteString(value string) (int, error) {
	b.mu.Lock()
	defer b.mu.Unlock()
	return b.Buffer.WriteString(value)
}

func (b *unitCSynchronizedBuffer) Text() string {
	b.mu.Lock()
	defer b.mu.Unlock()
	return b.Buffer.String()
}

func (r *unitCFailingReader) Read(buffer []byte) (int, error) {
	if !r.first {
		r.first = true
		copy(buffer, "start\n")
		return len("start\n"), nil
	}
	return 0, r.err
}

type unitCWriterFailure struct {
	err       error
	writes    int
	failAfter int
	short     bool
}

func (w *unitCWriterFailure) Write(data []byte) (int, error) {
	w.writes++
	if w.failAfter > 0 && w.writes >= w.failAfter {
		return 0, w.err
	}
	if w.short && len(data) > 0 {
		return len(data) - 1, nil
	}
	return len(data), nil
}
