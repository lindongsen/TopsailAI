package tui

import (
	"strings"
	"testing"

	"topsailai_agent_cluster/internal/protocol"
)

// showEmptyStub serves no endpoint at all, so the workspace table has no row to
// offer. It is the only way to reach the "nothing is available" branch, because a
// stub with one online endpoint always renders at least one row.
func showEmptyStub() *interactiveStub {
	return &interactiveStub{}
}

// TestShowWithoutASelectorRendersAndAsks proves a bare show in workspace scope
// renders the table and asks which row to show, instead of refusing with a usage
// line that sends the operator to a second command.
func TestShowWithoutASelectorRendersAndAsks(t *testing.T) {
	stub := scopeStub()
	output, diagnostics := runScope(t, stub, "show\n1\nexit\n", ColorPolicy{})
	if diagnostics != "" {
		t.Fatalf("unexpected diagnostics: %q", diagnostics)
	}
	if !strings.Contains(output, "select endpoint or session [1-2]") {
		t.Fatalf("the question does not name the rendered range: %q", output)
	}
	// The answer is echoed beside the row label, so the operator can see which row
	// the number named before the detail is printed.
	if !strings.Contains(output, "res-1") {
		t.Fatalf("the answer echo does not name the selected row: %q", output)
	}
	if !strings.Contains(output, "session: res-1 ") {
		t.Fatalf("show did not render the selected session: %q", output)
	}
}

// TestShowWithoutASelectorReusesTheRenderedTable proves the guided form does not
// re-read the inventory the REPL already rendered.
//
// The REPL renders the workspace inventory before the first prompt, so a second
// render would issue a duplicate inventory read for a table the operator is already
// looking at, and it would clear the row namespaces of any other table rendered
// since. The count is the evidence: one startup render plus the one read show
// performs for the detail, and nothing in between.
func TestShowWithoutASelectorReusesTheRenderedTable(t *testing.T) {
	stub := scopeStub()
	output, diagnostics := runScope(t, stub, "show\n1\nexit\n", ColorPolicy{})
	if diagnostics != "" {
		t.Fatalf("unexpected diagnostics: %q", diagnostics)
	}
	if !strings.Contains(output, "session: res-1 ") {
		t.Fatalf("show did not render the selected session: %q", output)
	}
	// One endpoint listing for the startup render and one for the detail read. A
	// third would mean the guided branch rendered the table a second time.
	if stub.listCalls != 2 {
		t.Fatalf("endpoint listings=%d, want 2 (startup render plus the detail read)", stub.listCalls)
	}
}

// TestShowWithoutASelectorCancelsOnAnEmptyAnswer proves an empty answer is a
// decision rather than a failure: the operator looked at the table and chose to
// show nothing.
func TestShowWithoutASelectorCancelsOnAnEmptyAnswer(t *testing.T) {
	stub := scopeStub()
	output, diagnostics := runScope(t, stub, "show\n\nexit\n", ColorPolicy{})
	if diagnostics != "" {
		t.Fatalf("unexpected diagnostics: %q", diagnostics)
	}
	if !strings.Contains(output, showCancelled) {
		t.Fatalf("missing cancellation report %q in %q", showCancelled, output)
	}
	if strings.Contains(output, "session: res-1 ") {
		t.Fatalf("a cancelled show still rendered a detail: %q", output)
	}
}

// TestShowWithoutASelectorRefusesAnUnprintedNumber proves a number that was never
// printed is refused instead of falling back to the first row. Falling back would
// show a machine the operator never selected.
func TestShowWithoutASelectorRefusesAnUnprintedNumber(t *testing.T) {
	stub := scopeStub()
	_, diagnostics := runScope(t, stub, "show\n99\nexit\n", ColorPolicy{})
	if !strings.Contains(diagnostics, "row 99 is out of range; valid rows are 1-2") {
		t.Fatalf("diagnostics=%q, want the out-of-range refusal", diagnostics)
	}
}

// TestShowWithoutASelectorShowsAnEndpointPlaceholderRow proves the guided form
// offers the row a list renders for an endpoint with no sessions. That row carries
// no session identity, so the endpoint identifier is the only identity it has, and
// show already renders endpoint detail for a literal endpoint identifier.
func TestShowWithoutASelectorShowsAnEndpointPlaceholderRow(t *testing.T) {
	stub := readRowsStub()
	output, diagnostics := runScope(t, stub, "show\n3\nexit\n", ColorPolicy{})
	if diagnostics != "" {
		t.Fatalf("unexpected diagnostics: %q", diagnostics)
	}
	if !strings.Contains(output, "endpoint: endpoint-empty (online)") {
		t.Fatalf("missing placeholder endpoint detail: %q", output)
	}
}

// TestShowWithoutASelectorStatesNothingAvailable proves an empty table is reported
// with its remedy instead of asking a question with no answer. The usual reason a
// workspace table is empty is that every endpoint is offline and the default filter
// skips them, so the message names the flag that includes them.
func TestShowWithoutASelectorStatesNothingAvailable(t *testing.T) {
	stub := showEmptyStub()
	// The answer is empty so the assertion cannot be satisfied by a detail render:
	// with no row to choose, the command must state the remedy instead of asking a
	// question whose every answer would be refused.
	output, diagnostics := runScope(t, stub, "show\n\nexit\n", ColorPolicy{})
	if diagnostics != "" {
		t.Fatalf("unexpected diagnostics: %q", diagnostics)
	}
	if !strings.Contains(output, showNothingAvailable) {
		t.Fatalf("missing %q in %q", showNothingAvailable, output)
	}
	if strings.Contains(output, "select endpoint or session") {
		t.Fatalf("an empty table still asked a question: %q", output)
	}
}

// TestShowWithoutASelectorKeepsEndpointScopeDefault proves the guided branch is
// workspace-only. Endpoint scope already names one machine, so a bare show there
// renders that machine's detail without asking anything.
func TestShowWithoutASelectorKeepsEndpointScopeDefault(t *testing.T) {
	stub := scopeStub()
	output, diagnostics := runScope(t, stub, "cd host-one/endpoint-1\nshow\nexit\n", ColorPolicy{})
	if diagnostics != "" {
		t.Fatalf("unexpected diagnostics: %q", diagnostics)
	}
	if strings.Contains(output, "select endpoint or session") {
		t.Fatalf("endpoint scope asked a workspace question: %q", output)
	}
	if !strings.Contains(output, "endpoint: endpoint-1 (") {
		t.Fatalf("missing endpoint detail: %q", output)
	}
}

// TestShowWithoutASelectorKeepsSessionScopeDefault proves session scope still
// renders the pinned session without asking, because the operator already named it
// by navigating there.
func TestShowWithoutASelectorKeepsSessionScopeDefault(t *testing.T) {
	stub := scopeStub()
	output, diagnostics := runScope(t, stub, "cd host-one/endpoint-1/res-1\nshow\nexit\n", ColorPolicy{})
	if diagnostics != "" {
		t.Fatalf("unexpected diagnostics: %q", diagnostics)
	}
	if strings.Contains(output, "select endpoint or session") {
		t.Fatalf("session scope asked a workspace question: %q", output)
	}
	if !strings.Contains(output, "session: res-1 ") {
		t.Fatalf("missing session detail: %q", output)
	}
}

// TestShowWithoutASelectorAcceptsAProviderSessionID proves the guided answer is not
// limited to row numbers. A provider session identifier is what the standalone show
// command accepts, so an operator who copied one can paste it at the question.
func TestShowWithoutASelectorAcceptsAProviderSessionID(t *testing.T) {
	stub := scopeStub()
	output, diagnostics := runScope(t, stub, "show\nprovider-res-1\nexit\n", ColorPolicy{})
	if diagnostics != "" {
		t.Fatalf("unexpected diagnostics: %q", diagnostics)
	}
	if !strings.Contains(output, "session: res-1 ") {
		t.Fatalf("a provider session identifier did not resolve: %q", output)
	}
}

// TestShowGuidedPromptNamesTheRenderedRange pins the question text, so the accepted
// answers stay visible instead of being remembered.
func TestShowGuidedPromptNamesTheRenderedRange(t *testing.T) {
	if got := showGuidedPrompt; !strings.Contains(got, "[1-%d]") || !strings.Contains(got, "press Enter to cancel") {
		t.Fatalf("guided prompt %q does not name the range and the cancel answer", got)
	}
}

// TestShowRowLabelFallsBackToIdentity proves the echo never prints an empty pair of
// parentheses for a row whose provider reported no display name.
func TestShowRowLabelFallsBackToIdentity(t *testing.T) {
	cases := []struct {
		name string
		row  SessionRow
		want string
	}{
		{name: "display name and session", row: SessionRow{ClusterSessionID: "res-1", ProviderDisplayName: "work"}, want: "work (res-1)"},
		{name: "identity only", row: SessionRow{ClusterSessionID: "res-1"}, want: "res-1"},
		{name: "endpoint placeholder", row: SessionRow{EndpointID: "endpoint-1"}, want: "endpoint-1"},
		{name: "placeholder with display name", row: SessionRow{EndpointID: "endpoint-1", ProviderDisplayName: "one"}, want: "one (endpoint-1)"},
	}
	for _, testCase := range cases {
		t.Run(testCase.name, func(t *testing.T) {
			if got := showRowLabel(testCase.row); got != testCase.want {
				t.Fatalf("label=%q, want %q", got, testCase.want)
			}
		})
	}
}

// TestShowResolvedRowPrefersTheSessionIdentity proves the resolved row addresses the
// session when it has one, so an endpoint placeholder fallback cannot silently
// retarget a real session to its machine.
func TestShowResolvedRowPrefersTheSessionIdentity(t *testing.T) {
	row := SessionRow{EndpointID: "endpoint-1", ClusterSessionID: "res-1"}
	if got := showRowLabel(row); got != "res-1" {
		t.Fatalf("label=%q, want the session identity", got)
	}
	// The fallback is only reached when the session identity is absent, which is the
	// endpoint placeholder row the list renders for a machine with no sessions.
	placeholder := SessionRow{EndpointID: "endpoint-1", State: protocol.SessionStateUnknown}
	if got := showRowLabel(placeholder); got != "endpoint-1" {
		t.Fatalf("placeholder label=%q, want the endpoint identity", got)
	}
}
