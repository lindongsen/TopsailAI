package tui

import (
	"strings"
	"testing"

	"topsailai_agent_cluster/internal/protocol"
)

// readRowsStub serves one endpoint whose report holds an unverified session
// followed by a live session, so a row number can address either kind. The
// unverified row is the case the operator most needs to read: the provider listed
// the record but could not prove a process holds it.
func readRowsStub() *interactiveStub {
	report := protocol.InventoryReport{
		ReportComplete:   true,
		CollectionStatus: protocol.CollectionSucceeded,
		Adapters:         []protocol.AdapterSummary{{AdapterID: "adapter-1", DataKnown: true, CollectionStatus: protocol.CollectionSucceeded}},
		Sessions: []protocol.Session{
			{
				ClusterSessionID:   "res-unverified",
				ProviderSessionID:  "20261111094237",
				AdapterID:          "adapter-1",
				ProviderGeneration: "",
				State:              protocol.SessionStateUnknown,
				StateReason:        protocol.StateReasonLivenessUnverified,
				CollectionStatus:   protocol.CollectionSucceeded,
			},
			{
				ClusterSessionID:   "res-live",
				ProviderSessionID:  "20261111094238",
				AdapterID:          "adapter-1",
				ProviderGeneration: "generation-live",
				State:              "running",
				CollectionStatus:   protocol.CollectionSucceeded,
			},
		},
	}
	return &interactiveStub{
		endpoints: []protocol.Endpoint{
			{EndpointID: "endpoint-1", Hostname: "host-one", ConnectionState: "online"},
			{EndpointID: "endpoint-empty", Hostname: "host-empty", ConnectionState: "online"},
		},
		reports: map[string]protocol.InventoryReport{
			"endpoint-1": report,
			"endpoint-empty": {
				ReportComplete:   true,
				CollectionStatus: protocol.CollectionSucceeded,
				Adapters:         []protocol.AdapterSummary{{AdapterID: "adapter-1", DataKnown: true, CollectionStatus: protocol.CollectionSucceeded}},
			},
		},
	}
}

// TestInfoReadsUnverifiedRow proves a row the provider listed without a live
// process is still readable through info. The row is visible in the list, so a
// refusal would leave the operator with a row that cannot be inspected at all.
func TestInfoReadsUnverifiedRow(t *testing.T) {
	stub := readRowsStub()
	output, diagnostics := runScope(t, stub, "list\ninfo 1\nquit\n", ColorPolicy{})
	if diagnostics != "" {
		t.Fatalf("unexpected diagnostics: %q", diagnostics)
	}
	segment := segmentBeforePrompt(output, "workspace> ")
	for _, want := range []string{
		"session_id: res-unverified",
		"provider_session_id: 20261111094237",
		"state: unknown",
		"state_reason: liveness_unverified",
	} {
		if !strings.Contains(segment, want) {
			t.Fatalf("missing %q in info output: %q", want, segment)
		}
	}
}

// TestShowReadsUnverifiedRow proves show renders the same unverified row, so the
// two read surfaces agree about which rows are readable.
func TestShowReadsUnverifiedRow(t *testing.T) {
	stub := readRowsStub()
	output, diagnostics := runScope(t, stub, "list\nshow 1\nquit\n", ColorPolicy{})
	if diagnostics != "" {
		t.Fatalf("unexpected diagnostics: %q", diagnostics)
	}
	segment := segmentBeforePrompt(output, "workspace> ")
	if !strings.Contains(segment, "endpoint: endpoint-1 (online)") {
		t.Fatalf("missing endpoint detail: %q", segment)
	}
	if !strings.Contains(segment, "session: res-unverified") {
		t.Fatalf("missing unverified session detail: %q", segment)
	}
}

// TestShowReadsEndpointPlaceholderRow proves the row a list renders for an
// endpoint with no sessions is readable through show. That row carries no session
// identity, so the endpoint identifier is the only identity it has, and show
// already renders endpoint detail for a literal endpoint identifier.
func TestShowReadsEndpointPlaceholderRow(t *testing.T) {
	stub := readRowsStub()
	output, diagnostics := runScope(t, stub, "list\nshow 3\nquit\n", ColorPolicy{})
	if diagnostics != "" {
		t.Fatalf("unexpected diagnostics: %q", diagnostics)
	}
	segment := segmentBeforePrompt(output, "workspace> ")
	if !strings.Contains(segment, "endpoint: endpoint-empty (online)") {
		t.Fatalf("missing placeholder endpoint detail: %q", segment)
	}
}

// TestInfoNamesShowForEndpointPlaceholderRow proves info refuses a placeholder row
// with the command that does read it. info is a session command, so it cannot
// render endpoint detail, but reporting that the row identifies nothing would hide
// the remedy for a row the operator can see.
func TestInfoNamesShowForEndpointPlaceholderRow(t *testing.T) {
	stub := readRowsStub()
	_, diagnostics := runScope(t, stub, "list\ninfo 3\nquit\n", ColorPolicy{})
	want := `error: row 3 is endpoint "endpoint-empty", not a session; use show endpoint-empty for endpoint detail`
	if !strings.Contains(diagnostics, want) {
		t.Fatalf("diagnostics=%q, want %q", diagnostics, want)
	}
	if strings.Contains(diagnostics, "does not identify a session") {
		t.Fatalf("diagnostics=%q still reports the row identifies nothing", diagnostics)
	}
}

// TestLiveCommandsStillRefuseUnverifiedRow proves the read widening did not weaken
// the live-process guard. cd and stop address a live process, and an empty
// generation cannot prove which process they would reach, so both must keep
// refusing the same row that info and show now read.
func TestLiveCommandsStillRefuseUnverifiedRow(t *testing.T) {
	cases := []struct {
		name  string
		input string
		want  string
	}{
		{
			name:  "cd",
			input: "list\ncd 1\nquit\n",
			want:  "row 1 has no generation; run list again",
		},
		{
			name:  "stop",
			input: "list\nstop 1\nquit\n",
			want:  "row 1 is unverified: the session record exists but no process holds it, so it cannot be addressed; use resume to resume it",
		},
	}
	for _, testCase := range cases {
		t.Run(testCase.name, func(t *testing.T) {
			stub := readRowsStub()
			_, diagnostics := runScope(t, stub, testCase.input, ColorPolicy{})
			if !strings.Contains(diagnostics, testCase.want) {
				t.Fatalf("diagnostics=%q, want %q", diagnostics, testCase.want)
			}
			if stub.admit != 0 {
				t.Fatalf("refused command admitted %d commands", stub.admit)
			}
		})
	}
}

// TestInfoReadsLiveRowStill proves the widening did not change the ordinary case:
// a live row keeps rendering its own detail.
func TestInfoReadsLiveRowStill(t *testing.T) {
	stub := readRowsStub()
	output, diagnostics := runScope(t, stub, "list\ninfo 2\nquit\n", ColorPolicy{})
	if diagnostics != "" {
		t.Fatalf("unexpected diagnostics: %q", diagnostics)
	}
	segment := segmentBeforePrompt(output, "workspace> ")
	for _, want := range []string{"session_id: res-live", "generation: generation-live", "state: running"} {
		if !strings.Contains(segment, want) {
			t.Fatalf("missing %q in info output: %q", want, segment)
		}
	}
}
