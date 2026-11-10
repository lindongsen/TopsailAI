package tui

import (
	"context"
	"errors"
	"testing"
	"time"

	"topsailai_agent_cluster/internal/protocol"
)

func TestListRowsMarksStaleAndUnknown(t *testing.T) {
	last := int64(42)
	rows := ListRows([]protocol.Endpoint{{EndpointID: "e1"}}, map[string]protocol.InventoryReport{"e1": {Adapters: []protocol.AdapterSummary{{AdapterID: "a1", DataKnown: false, Stale: true, LastSuccessAtMS: &last}}, Sessions: []protocol.Session{{ClusterSessionID: "s1", AdapterID: "a1", ProviderGeneration: "g1", State: "idle"}}}}, "")
	if len(rows) != 1 || !rows[0].Stale || !rows[0].Unknown || rows[0].LastSuccessAtMS == nil {
		t.Fatalf("unexpected rows: %#v", rows)
	}
}

func TestStatusLabelDoesNotOverstateEvidence(t *testing.T) {
	if got := StatusLabel(protocol.StatusAdmitted, protocol.ExecutionReceipt{}); got != "server received" {
		t.Fatalf("admitted label = %q", got)
	}
	if got := StatusLabel(protocol.StatusFinished, protocol.ExecutionReceipt{DeliveryBoundary: protocol.DeliverySignalSent}); got != "stop request sent" {
		t.Fatalf("signal label = %q", got)
	}
}

func TestActionValidation(t *testing.T) {
	if err := ValidateStopTarget(protocol.CommandTarget{ResourceID: "s1"}); err == nil {
		t.Fatal("expected missing generation error")
	}
	if err := ValidateCapability(protocol.CapabilityDescriptor{}, "agent.stop"); err == nil {
		t.Fatal("expected unsupported capability error")
	}
	if err := RequireConfirmation(false, "agent.stop", "s1", "{}"); err == nil {
		t.Fatal("expected confirmation error")
	}
}

// capabilityStub provides deterministic capability query results for preflight tests.
type capabilityStub struct {
	descriptor protocol.CapabilityDescriptor
	err        error
	queries    int
}

func (s *capabilityStub) GetCapabilities(_ context.Context, _ string) (protocol.CapabilityDescriptor, error) {
	s.queries++
	return s.descriptor, s.err
}

func TestActionRejectedWhenCapabilityUnsupported(t *testing.T) {
	stub := &capabilityStub{descriptor: protocol.CapabilityDescriptor{Revision: "r1"}}
	if _, err := PreflightCapability(context.Background(), stub, "endpoint-1", "agent.stop"); err == nil {
		t.Fatal("expected unsupported capability rejection")
	}
	if stub.queries != 1 {
		t.Fatalf("capability queries = %d, want 1", stub.queries)
	}
}

func TestActionRejectedWhenCapabilityQueryFails(t *testing.T) {
	stub := &capabilityStub{err: errors.New("unavailable")}
	if _, err := PreflightCapability(context.Background(), stub, "endpoint-1", "message.send"); err == nil {
		t.Fatal("expected capability query failure")
	}
}

func TestStopRejectedWithoutGeneration(t *testing.T) {
	if err := ValidateStopTarget(protocol.CommandTarget{ResourceID: "session-1"}); err == nil {
		t.Fatal("expected missing generation rejection")
	}
}

func TestSupportedActionProceedsToSubmit(t *testing.T) {
	stub := &capabilityStub{descriptor: protocol.CapabilityDescriptor{Revision: "r1", Capabilities: []protocol.Capability{{Name: "message.send"}}}}
	descriptor, err := PreflightCapability(context.Background(), stub, "endpoint-1", "message.send")
	if err != nil {
		t.Fatal(err)
	}
	if descriptor.Revision != "r1" {
		t.Fatalf("revision = %q, want r1", descriptor.Revision)
	}
}

func TestWaitTimeoutUsesBudgetValue(t *testing.T) {
	if got := WaitTimeout(protocol.Budget{WaitTimeoutMS: 100}); got != 100*time.Millisecond {
		t.Fatalf("wait timeout = %s, want 100ms", got)
	}
}

func TestWaitTimeoutDoesNotChangeExecutionFact(t *testing.T) {
	ctx, cancel := WaitContext(context.Background(), protocol.Budget{WaitTimeoutMS: 1})
	defer cancel()
	<-ctx.Done()
	if ctx.Err() != context.DeadlineExceeded {
		t.Fatalf("wait context error = %v, want deadline exceeded", ctx.Err())
	}
	status := protocol.StatusDispatched
	if status == protocol.StatusRejected || status == protocol.StatusFailed {
		t.Fatalf("local wait changed durable status to %s", status)
	}
}

type waitStateReader struct {
	states []map[string]any
	calls  int
}

func (r *waitStateReader) GetCommand(context.Context, string) (map[string]any, error) {
	index := r.calls
	r.calls++
	if index >= len(r.states) {
		index = len(r.states) - 1
	}
	return r.states[index], nil
}

func TestWaitPollsUntilTerminalState(t *testing.T) {
	reader := &waitStateReader{states: []map[string]any{
		{"status": string(protocol.StatusExecuting)},
		{"status": string(protocol.StatusFinished)},
	}}
	ctx, cancel := context.WithTimeout(context.Background(), time.Second)
	defer cancel()
	state, err := WaitForTerminal(ctx, reader, "command-1", time.Millisecond)
	if err != nil {
		t.Fatal(err)
	}
	if !IsTerminalState(state) || reader.calls != 2 {
		t.Fatalf("state=%#v calls=%d", state, reader.calls)
	}
}

func TestWaitReturnsPersistentStateOnTimeout(t *testing.T) {
	reader := &waitStateReader{states: []map[string]any{{"status": string(protocol.StatusExecuting)}}}
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Millisecond)
	defer cancel()
	state, err := WaitForTerminal(ctx, reader, "command-2", time.Millisecond)
	if err != nil {
		t.Fatal(err)
	}
	if got, _ := state["status"].(string); got != string(protocol.StatusExecuting) {
		t.Fatalf("state=%#v", state)
	}
}

func TestListRowsPrefersHostnameAndFallsBackToDisplayNameAndID(t *testing.T) {
	cases := []struct {
		name string
		item protocol.Endpoint
		want string
	}{
		{name: "hostname", item: protocol.Endpoint{EndpointID: "e1", DisplayName: "display", Hostname: "host.example"}, want: "host.example"},
		{name: "display name", item: protocol.Endpoint{EndpointID: "e1", DisplayName: "display"}, want: "display"},
		{name: "endpoint id", item: protocol.Endpoint{EndpointID: "e1"}, want: "e1"},
	}
	for _, testCase := range cases {
		t.Run(testCase.name, func(t *testing.T) {
			rows := ListRows([]protocol.Endpoint{testCase.item}, map[string]protocol.InventoryReport{"e1": {CollectionStatus: protocol.CollectionSucceeded}}, "")
			if len(rows) != 1 || rows[0].EndpointLabel != testCase.want {
				t.Fatalf("rows = %#v, want endpoint label %q", rows, testCase.want)
			}
		})
	}
}
