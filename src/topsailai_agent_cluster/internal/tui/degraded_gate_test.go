package tui

import (
	"context"
	"io"
	"strings"
	"testing"

	"topsailai_agent_cluster/internal/protocol"
)

// degradedGateStub adds the three optional machine-contacting seams to the shared
// stub, so one fixture can prove every gated command refuses before it reaches any
// of them.
//
// The seams are counted rather than merely implemented, because the gate's whole
// purpose is that the request is never issued. A test that only asserted the error
// message would still pass if the gate ran after the request.
type degradedGateStub struct {
	*interactiveStub
	followCalls   int
	messagesCalls int
	launchCalls   int
}

// FollowOutput records that a stream was requested.
func (s *degradedGateStub) FollowOutput(context.Context, string, string, string, int, int) (<-chan protocol.OutputFollowRecord, error) {
	s.followCalls++
	channel := make(chan protocol.OutputFollowRecord)
	close(channel)
	return channel, nil
}

// GetMessages records that a conversation was requested.
func (s *degradedGateStub) GetMessages(context.Context, string, string, int, int) (protocol.MessagesResult, error) {
	s.messagesCalls++
	return protocol.MessagesResult{}, nil
}

// GetLaunchOptions records that the launch catalogue was requested.
func (s *degradedGateStub) GetLaunchOptions(context.Context, string, string) (protocol.LaunchOptions, error) {
	s.launchCalls++
	return protocol.LaunchOptions{
		Handlers: []protocol.LaunchHandler{{AdapterID: "a", Revision: "v"}},
		Projects: []protocol.Project{{Name: "project", Path: "/work/project"}},
	}, nil
}

// degradedExpiresAtMS is the deletion deadline the fixture reports. It is a fixed
// value so the assertion can compare against the same formatter the message uses.
const degradedExpiresAtMS int64 = 1800000000000

// degradedGateFixture serves one endpoint in the given connection state.
//
// Only a degraded endpoint carries a deadline, because a live endpoint has no
// scheduled deletion. Reporting one for an online endpoint would let a test pass
// while the renderer claimed an expiry that does not exist.
func degradedGateFixture(state string) *degradedGateStub {
	endpoint := protocol.Endpoint{EndpointID: "endpoint-1", Hostname: "host-one", ConnectionState: state}
	if state == "degraded" {
		endpoint.ExpiresAtMS = degradedExpiresAtMS
	}
	return &degradedGateStub{interactiveStub: &interactiveStub{
		endpoints: []protocol.Endpoint{endpoint},
		reports:   map[string]protocol.InventoryReport{"endpoint-1": scopeInventory("res-1", "generation-1")},
	}}
}

// degradedScopeState enters the fixture endpoint so a command addresses it.
func degradedScopeState() *interactiveState {
	state := &interactiveState{}
	state.enterEndpoint(protocol.Endpoint{EndpointID: "endpoint-1", Hostname: "host-one"})
	return state
}

// degradedSessionState enters a session on the fixture endpoint.
//
// The logs command addresses a session, so endpoint scope alone has no resource to
// read and would fail on the missing selection before reaching the gate. Entering
// the session is what makes the gate the first refusal.
func degradedSessionState() *interactiveState {
	state := &interactiveState{}
	state.enterSessionDetails(protocol.Endpoint{EndpointID: "endpoint-1", Hostname: "host-one"}, "res-1", "provider-res-1", "session one", "adapter-1", "generation-1")
	return state
}

// requireDegradedDiagnostic asserts the error names the state, the deletion date
// and the fact that nothing was sent.
func requireDegradedDiagnostic(t *testing.T, err error) {
	t.Helper()
	if err == nil {
		t.Fatal("command on a degraded endpoint unexpectedly succeeded")
	}
	message := err.Error()
	if !strings.Contains(message, "degraded") {
		t.Fatalf("error=%q, want the degraded state named", message)
	}
	if !strings.Contains(message, "no request was sent") {
		t.Fatalf("error=%q, want the refusal to state that nothing was sent", message)
	}
	if want := formatDateTime(degradedExpiresAtMS, nil); !strings.Contains(message, want) {
		t.Fatalf("error=%q, want the deletion date %q", message, want)
	}
}

// TestLogsRefusesDegradedEndpointBeforeSnapshot proves the snapshot read is never
// issued for a degraded endpoint.
func TestLogsRefusesDegradedEndpointBeforeSnapshot(t *testing.T) {
	stub := degradedGateFixture("degraded")
	err := interactiveLogs(context.Background(), stub, degradedSessionState(), "", 4096, 4096, &strings.Builder{}, ColorPolicy{})
	requireDegradedDiagnostic(t, err)
	if len(stub.outputRequests) != 0 {
		t.Fatalf("degraded endpoint still received an output request: %+v", stub.outputRequests)
	}
}

// TestLogsFollowRefusesDegradedEndpointBeforeArming proves the stream is never
// armed for a degraded endpoint.
//
// Arming is the only observable effect at this point, because the stream starts on
// the next prompt. A nil follow intent therefore proves the gate ran before the
// arming call rather than after it.
func TestLogsFollowRefusesDegradedEndpointBeforeArming(t *testing.T) {
	stub := degradedGateFixture("degraded")
	state := degradedSessionState()
	err := interactiveLogs(context.Background(), stub, state, "-f", 4096, 4096, &strings.Builder{}, ColorPolicy{})
	requireDegradedDiagnostic(t, err)
	if state.follow != nil {
		t.Fatalf("degraded endpoint still armed a follow stream: %+v", state.follow)
	}
	if stub.followCalls != 0 {
		t.Fatalf("degraded endpoint still opened a stream: calls=%d", stub.followCalls)
	}
}

// TestMessagesRowNumberRefusesDegradedEndpoint proves a row number cannot reach a
// degraded endpoint's conversation.
func TestMessagesRowNumberRefusesDegradedEndpoint(t *testing.T) {
	stub := degradedGateFixture("degraded")
	state := &interactiveState{}
	rows := ListRows(stub.endpoints, stub.reports, "")
	assignRowNumbers(rows)
	state.setRows(rows)
	err := interactiveMessages(context.Background(), stub, state, "1", &strings.Builder{}, &strings.Builder{}, ColorPolicy{})
	requireDegradedDiagnostic(t, err)
	if stub.messagesCalls != 0 {
		t.Fatalf("degraded endpoint still received a conversation read: calls=%d", stub.messagesCalls)
	}
}

// TestMessagesSessionIDRefusesDegradedEndpoint proves a literal provider session
// ID cannot reach a degraded endpoint's conversation.
//
// Endpoint scope resolves the identifier without reading the inventory, so this
// path reaches the gate with no prior store read. It is covered separately because
// a gate placed inside the resolver would miss it.
func TestMessagesSessionIDRefusesDegradedEndpoint(t *testing.T) {
	stub := degradedGateFixture("degraded")
	err := interactiveMessages(context.Background(), stub, degradedScopeState(), "provider-res-1", &strings.Builder{}, &strings.Builder{}, ColorPolicy{})
	requireDegradedDiagnostic(t, err)
	if stub.messagesCalls != 0 {
		t.Fatalf("degraded endpoint still received a conversation read: calls=%d", stub.messagesCalls)
	}
}

// TestStartRefusesDegradedEndpointBeforeLaunchQuery proves the launch catalogue is
// never requested from a degraded endpoint.
func TestStartRefusesDegradedEndpointBeforeLaunchQuery(t *testing.T) {
	stub := degradedGateFixture("degraded")
	lines, done, stop := startInputReader(strings.NewReader(""), 8192)
	defer func() { stop(); done.Wait() }()
	err := projectLaunch(context.Background(), stub, stub, degradedScopeState(), "", lines, io.Discard, io.Discard, InteractiveOptions{})
	requireDegradedDiagnostic(t, err)
	if stub.launchCalls != 0 {
		t.Fatalf("degraded endpoint still received a launch query: calls=%d", stub.launchCalls)
	}
	if stub.admit != 0 {
		t.Fatalf("degraded endpoint still admitted a command: admit=%d", stub.admit)
	}
}

// TestGateAllowsOnlineEndpoint proves the gate does not over-block a healthy
// endpoint, so the refusal is specific to the degraded state rather than to every
// machine-contacting command.
func TestGateAllowsOnlineEndpoint(t *testing.T) {
	t.Run("logs", func(t *testing.T) {
		stub := degradedGateFixture("online")
		if err := interactiveLogs(context.Background(), stub, degradedSessionState(), "", 4096, 4096, &strings.Builder{}, ColorPolicy{}); err != nil {
			t.Fatalf("online endpoint refused: %v", err)
		}
		if len(stub.outputRequests) != 1 {
			t.Fatalf("online endpoint received %d output requests, want 1", len(stub.outputRequests))
		}
	})
	t.Run("messages", func(t *testing.T) {
		stub := degradedGateFixture("online")
		if err := interactiveMessages(context.Background(), stub, degradedScopeState(), "provider-res-1", &strings.Builder{}, &strings.Builder{}, ColorPolicy{}); err != nil {
			t.Fatalf("online endpoint refused: %v", err)
		}
		if stub.messagesCalls != 1 {
			t.Fatalf("online endpoint received %d conversation reads, want 1", stub.messagesCalls)
		}
	})
	t.Run("start", func(t *testing.T) {
		stub := degradedGateFixture("online")
		lines, done, stop := startInputReader(strings.NewReader("1\ndo work\n"), 8192)
		defer func() { stop(); done.Wait() }()
		if err := projectLaunch(context.Background(), stub, stub, degradedScopeState(), "", lines, io.Discard, io.Discard, InteractiveOptions{}); err != nil {
			t.Fatalf("online endpoint refused: %v", err)
		}
		// The wizard queries the catalogue twice: once to render the choices and
		// once to confirm the selection. The count is pinned so a gate that
		// silently skipped the second query would be visible here.
		if stub.launchCalls != 2 {
			t.Fatalf("online endpoint received %d launch queries, want 2", stub.launchCalls)
		}
		if stub.admit != 1 {
			t.Fatalf("online endpoint admitted %d commands, want 1", stub.admit)
		}
	})
}
