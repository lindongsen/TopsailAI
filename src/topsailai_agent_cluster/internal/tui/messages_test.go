package tui

import (
	"context"
	"encoding/json"
	"io"
	"strings"
	"testing"

	"topsailai_agent_cluster/internal/protocol"
)

// interactiveMessagesStub adds the optional MessagesQuerier seam to the shared
// history stub, so one scenario can render a history table, read a conversation
// and still reuse the same inventory, capability and admission recording as every
// other REPL test.
type interactiveMessagesStub struct {
	*interactiveHistoryStub
	messages      map[string]protocol.MessagesResult
	messagesEr    map[string]error
	messagesCalls []string
	// messagesSessions records the provider session ID of every interactive read,
	// so a test can prove a row number resolved to the row the operator saw rather
	// than to some other session on the same endpoint.
	messagesSessions []string
	// messagesMaxChars records the caller bound of every interactive read. The REPL
	// always passes zero, so a non-zero value would mean the surface narrowed a
	// conversation the operator did not ask to narrow.
	messagesMaxChars []int
	// messagesMaxTokens records the token bound of every interactive read, so a
	// test can prove the default reached the seam rather than being dropped.
	messagesMaxTokens []int
}

// GetMessages records the queried endpoint and session so a test can prove which
// target the interactive surface addressed.
func (s *interactiveMessagesStub) GetMessages(_ context.Context, endpointID, sessionID string, maxChars, maxTokens int) (protocol.MessagesResult, error) {
	s.messagesCalls = append(s.messagesCalls, endpointID)
	s.messagesSessions = append(s.messagesSessions, sessionID)
	s.messagesMaxChars = append(s.messagesMaxChars, maxChars)
	s.messagesMaxTokens = append(s.messagesMaxTokens, maxTokens)
	if err := s.messagesEr[endpointID]; err != nil {
		return protocol.MessagesResult{}, err
	}
	return s.messages[endpointID], nil
}

// messagesScenarioStub serves one endpoint whose inventory holds the given
// sessions, whose history table holds the given rows and whose conversation is the
// given result.
func messagesScenarioStub(rows []protocol.HistoryRow, report protocol.InventoryReport, result protocol.MessagesResult) *interactiveMessagesStub {
	return &interactiveMessagesStub{
		interactiveHistoryStub: historyScenarioStub(rows, report),
		messages:               map[string]protocol.MessagesResult{"endpoint-1": result},
	}
}

// TestInteractiveMessagesReadsStoppedRowByNumber proves a past row is readable.
//
// This is the whole reason the command exists: cd requires a live generation and
// resume requires a proven absence, so a stopped session had no read surface at
// all. The row here is resumable and not live, which is exactly the case that was
// previously unreadable.
func TestInteractiveMessagesReadsStoppedRowByNumber(t *testing.T) {
	stub := messagesScenarioStub(
		[]protocol.HistoryRow{
			{ProviderSessionID: "wa-live", ProviderDisplayName: "live work", Resumable: false, ResumeBlockedReason: protocol.ResumeBlockedProviderRunning},
			{ProviderSessionID: "wa-past", ProviderDisplayName: "past work", Resumable: true, ResourceID: "res-past"},
		},
		historyReport(historyLiveSession("res-live", "wa-live", "gen-1")),
		protocol.MessagesResult{
			ProviderSessionID: "wa-past",
			MessageCount:      2,
			Messages: []protocol.Message{
				{Role: "user", Content: "first question", CreatedAtMS: 1000},
				{Role: "assistant", Content: "first answer", CreatedAtMS: 2000},
			},
		},
	)

	output, diagnostics := runScope(t, stub, "history endpoint-1\nmessages 2\nexit\n", ColorPolicy{})
	if diagnostics != "" {
		t.Fatalf("unexpected diagnostics: %q", diagnostics)
	}
	for _, want := range []string{"#1 - Role: USER", "first question", "#2 - Role: ASSISTANT", "first answer"} {
		if !strings.Contains(output, want) {
			t.Fatalf("conversation missing %q: %q", want, output)
		}
	}
	if len(stub.messagesCalls) != 1 || stub.messagesCalls[0] != "endpoint-1" {
		t.Fatalf("messages calls = %v, want one read of endpoint-1", stub.messagesCalls)
	}
	// The REPL never narrows a conversation the operator did not ask to narrow.
	if stub.messagesMaxChars[0] != 0 {
		t.Fatalf("maxChars = %d, want 0", stub.messagesMaxChars[0])
	}
}

// TestInteractiveMessagesKeepsRowNumbers proves the read is non-destructive.
//
// history replaces the row-number namespace and resume invalidates it, so an
// operator inspecting several past sessions would otherwise have to re-render the
// table between every read. messages is read-only and must leave the numbers
// usable.
func TestInteractiveMessagesKeepsRowNumbers(t *testing.T) {
	stub := messagesScenarioStub(
		[]protocol.HistoryRow{
			{ProviderSessionID: "wa-one", ProviderDisplayName: "one", Resumable: true},
			{ProviderSessionID: "wa-two", ProviderDisplayName: "two", Resumable: true},
		},
		historyReport(),
		protocol.MessagesResult{
			ProviderSessionID: "wa-one",
			MessageCount:      1,
			Messages:          []protocol.Message{{Role: "user", Content: "hello"}},
		},
	)

	output, diagnostics := runScope(t, stub, "history endpoint-1\nmessages 1\nmessages 2\nexit\n", ColorPolicy{})
	if diagnostics != "" {
		t.Fatalf("unexpected diagnostics: %q", diagnostics)
	}
	if len(stub.messagesCalls) != 2 {
		t.Fatalf("messages calls = %d, want 2: the second read must not need a fresh history render", len(stub.messagesCalls))
	}
	if !strings.Contains(output, "hello") {
		t.Fatalf("conversation missing: %q", output)
	}
}

// TestInteractiveMessagesSessionScopeRejectsArgument proves session scope does not
// silently retarget. The operator named a target already, so an argument is a
// mistake rather than a request to read a different session.
func TestInteractiveMessagesSessionScopeRejectsArgument(t *testing.T) {
	stub := messagesScenarioStub(
		[]protocol.HistoryRow{{ProviderSessionID: "wa-live", ProviderDisplayName: "live work", Resumable: false, ResumeBlockedReason: protocol.ResumeBlockedProviderRunning}},
		historyReport(historyLiveSession("res-live", "wa-live", "gen-1")),
		protocol.MessagesResult{ProviderSessionID: "wa-live", MessageCount: 1, Messages: []protocol.Message{{Role: "user", Content: "scoped"}}},
	)

	output, diagnostics := runScope(t, stub, "history endpoint-1\ncd 1\nmessages 2\nexit\n", ColorPolicy{})
	if !strings.Contains(diagnostics, "takes no argument in session scope") {
		t.Fatalf("diagnostics = %q, want the session-scope rejection", diagnostics)
	}
	if len(stub.messagesCalls) != 0 {
		t.Fatalf("messages calls = %v, want none", stub.messagesCalls)
	}
	if strings.Contains(output, "scoped") {
		t.Fatalf("a rejected read still rendered a conversation: %q", output)
	}
}

// TestInteractiveMessagesSessionScopeReadsSelected proves session scope reads the
// selected session without an argument.
func TestInteractiveMessagesSessionScopeReadsSelected(t *testing.T) {
	stub := messagesScenarioStub(
		[]protocol.HistoryRow{{ProviderSessionID: "wa-live", ProviderDisplayName: "live work", Resumable: false, ResumeBlockedReason: protocol.ResumeBlockedProviderRunning}},
		historyReport(historyLiveSession("res-live", "wa-live", "gen-1")),
		protocol.MessagesResult{ProviderSessionID: "wa-live", MessageCount: 1, Messages: []protocol.Message{{Role: "user", Content: "scoped"}}},
	)

	output, diagnostics := runScope(t, stub, "history endpoint-1\ncd 1\nmessages\nexit\n", ColorPolicy{})
	if diagnostics != "" {
		t.Fatalf("unexpected diagnostics: %q", diagnostics)
	}
	if !strings.Contains(output, "scoped") {
		t.Fatalf("conversation missing: %q", output)
	}
	if len(stub.messagesCalls) != 1 || stub.messagesCalls[0] != "endpoint-1" {
		t.Fatalf("messages calls = %v, want one read of endpoint-1", stub.messagesCalls)
	}
}

// TestInteractiveMessagesRejectsAmbiguousSessionID proves a provider session ID
// reported by several endpoints is refused instead of resolved by a silent choice.
// Reading the wrong machine's conversation is worse than refusing.
func TestInteractiveMessagesRejectsAmbiguousSessionID(t *testing.T) {
	stub := &interactiveMessagesStub{
		interactiveHistoryStub: &interactiveHistoryStub{
			interactiveStub: &interactiveStub{
				endpoints: []protocol.Endpoint{{EndpointID: "endpoint-1", Hostname: "host-one"}, {EndpointID: "endpoint-2", Hostname: "host-two"}},
				reports: map[string]protocol.InventoryReport{
					"endpoint-1": historyReport(historyLiveSession("res-1", "wa-shared", "gen-1")),
					"endpoint-2": historyReport(historyLiveSession("res-2", "wa-shared", "gen-2")),
				},
			},
		},
		messages: map[string]protocol.MessagesResult{},
	}

	_, diagnostics := runScope(t, stub, "messages wa-shared\nexit\n", ColorPolicy{})
	if !strings.Contains(diagnostics, "reported by several endpoints") {
		t.Fatalf("diagnostics = %q, want the ambiguity rejection", diagnostics)
	}
	if len(stub.messagesCalls) != 0 {
		t.Fatalf("messages calls = %v, want none", stub.messagesCalls)
	}
}

// TestInteractiveMessagesReadsListRowByNumber proves a list row number is a valid
// conversation target in workspace scope.
//
// This is the behaviour the command was missing: the ordinary "list" then
// "messages <n>" sequence failed with "run history first", even though row n was
// on screen and every other session-addressing command accepted it. The list row
// here has no generation and is unverified, which is exactly the case that must
// stay readable: a conversation read addresses persisted provider data, so it must
// not inherit the addressability rules of cd and stop.
func TestInteractiveMessagesReadsListRowByNumber(t *testing.T) {
	stub := messagesScenarioStub(
		nil,
		historyReport(
			historyLiveSession("res-live", "wa-live", "gen-1"),
			protocol.Session{ClusterSessionID: "res-past", ProviderSessionID: "wa-past", State: protocol.SessionStateUnknown, StateReason: protocol.StateReasonLivenessUnverified},
		),
		protocol.MessagesResult{
			ProviderSessionID: "wa-past",
			MessageCount:      1,
			Messages:          []protocol.Message{{Role: "user", Content: "list row conversation"}},
		},
	)

	output, diagnostics := runScope(t, stub, "messages 2\nexit\n", ColorPolicy{})
	if diagnostics != "" {
		t.Fatalf("unexpected diagnostics: %q", diagnostics)
	}
	if !strings.Contains(output, "list row conversation") {
		t.Fatalf("conversation missing: %q", output)
	}
	if len(stub.messagesSessions) != 1 || stub.messagesSessions[0] != "wa-past" {
		t.Fatalf("messages sessions = %v, want one read of wa-past", stub.messagesSessions)
	}
	if len(stub.messagesCalls) != 1 || stub.messagesCalls[0] != "endpoint-1" {
		t.Fatalf("messages calls = %v, want one read of endpoint-1", stub.messagesCalls)
	}
}

// TestInteractiveMessagesReadsListRowInEndpointScope proves the same list row
// number works inside endpoint scope, where the current endpoint is already known.
func TestInteractiveMessagesReadsListRowInEndpointScope(t *testing.T) {
	stub := messagesScenarioStub(
		nil,
		historyReport(historyLiveSession("res-live", "wa-live", "gen-1")),
		protocol.MessagesResult{
			ProviderSessionID: "wa-live",
			MessageCount:      1,
			Messages:          []protocol.Message{{Role: "assistant", Content: "endpoint scoped conversation"}},
		},
	)

	output, diagnostics := runScope(t, stub, "cd endpoint-1\nmessages 1\nexit\n", ColorPolicy{})
	if diagnostics != "" {
		t.Fatalf("unexpected diagnostics: %q", diagnostics)
	}
	if !strings.Contains(output, "endpoint scoped conversation") {
		t.Fatalf("conversation missing: %q", output)
	}
	if len(stub.messagesSessions) != 1 || stub.messagesSessions[0] != "wa-live" {
		t.Fatalf("messages sessions = %v, want one read of wa-live", stub.messagesSessions)
	}
}

// TestMessagesListRowRejectsForeignEndpoint proves endpoint scope does not
// silently retarget a row rendered for another endpoint.
//
// This is a direct unit test rather than a REPL scenario, because the REPL cannot
// reach the guard: entering an endpoint re-renders the list scoped to that
// endpoint, so every row in state.Rows already belongs to it. The guard therefore
// protects a state the REPL does not currently produce, and a REPL test would pass
// for the wrong reason by never exercising it.
func TestMessagesListRowRejectsForeignEndpoint(t *testing.T) {
	state := &interactiveState{
		Scope: ScopeState{Kind: ScopeEndpoint, EndpointID: "endpoint-1"},
	}
	state.setRows([]SessionRow{{No: 1, EndpointID: "endpoint-2", ClusterSessionID: "res-2", ProviderSessionID: "wa-two", ProviderGeneration: "gen-2"}})

	_, _, err := messagesListRow(state, 1)
	if err == nil || !strings.Contains(err.Error(), "belongs to endpoint") {
		t.Fatalf("err = %v, want the foreign-endpoint rejection", err)
	}
}

// TestMessagesListRowReadsUnverifiedRow proves a list row without a generation is
// still readable.
//
// This is the distinction that keeps the command useful: cd and stop refuse an
// unverified row because they address a live process, while a conversation read
// addresses persisted provider data. Reusing resolveRowSelection here would have
// made the new row-number support refuse exactly the rows the command exists for.
func TestMessagesListRowReadsUnverifiedRow(t *testing.T) {
	state := &interactiveState{}
	state.setRows([]SessionRow{{No: 1, EndpointID: "endpoint-1", ClusterSessionID: "res-past", ProviderSessionID: "wa-past", State: protocol.SessionStateUnknown, Unverified: true}})

	endpointID, sessionID, err := messagesListRow(state, 1)
	if err != nil {
		t.Fatalf("messagesListRow: %v", err)
	}
	if endpointID != "endpoint-1" || sessionID != "wa-past" {
		t.Fatalf("target = %q/%q, want endpoint-1/wa-past", endpointID, sessionID)
	}
}

// TestMessagesListRowRejectsOutOfRange proves an out-of-range number names the
// valid range instead of reading an arbitrary row.
func TestMessagesListRowRejectsOutOfRange(t *testing.T) {
	state := &interactiveState{}
	state.setRows([]SessionRow{{No: 1, EndpointID: "endpoint-1", ClusterSessionID: "res-1", ProviderSessionID: "wa-one"}})

	_, _, err := messagesListRow(state, 2)
	if err == nil || !strings.Contains(err.Error(), "out of range") {
		t.Fatalf("err = %v, want the out-of-range rejection", err)
	}
}

// TestInteractiveMessagesRequiresRenderedTableForRowNumber proves a row number
// without a rendered table is refused rather than guessed, because the number has
// no meaning on its own. Both remedies are named, because either table can supply
// the number.
//
// The stub reports no endpoints, which is the only way the REPL reaches this
// branch: a startup list always renders, and every endpoint contributes at least
// one row, so a populated fleet never leaves state.Rows empty.
func TestInteractiveMessagesRequiresRenderedTableForRowNumber(t *testing.T) {
	stub := &interactiveMessagesStub{
		interactiveHistoryStub: &interactiveHistoryStub{
			interactiveStub: &interactiveStub{reports: map[string]protocol.InventoryReport{}},
		},
		messages: map[string]protocol.MessagesResult{},
	}

	_, diagnostics := runScope(t, stub, "messages 1\nexit\n", ColorPolicy{})
	if !strings.Contains(diagnostics, "run list or history first") {
		t.Fatalf("diagnostics = %q, want the missing-table rejection", diagnostics)
	}
	if len(stub.messagesCalls) != 0 {
		t.Fatalf("messages calls = %v, want none", stub.messagesCalls)
	}
}

// TestInteractiveMessagesHistoryRowWinsOverListRow proves the history namespace
// keeps its meaning after a history render.
//
// A history render clears the list rows, so the two namespaces can never both be
// live. This test pins the precedence anyway, because a future change that keeps
// both would otherwise silently reinterpret a history number as a list number.
func TestInteractiveMessagesHistoryRowWinsOverListRow(t *testing.T) {
	stub := messagesScenarioStub(
		[]protocol.HistoryRow{{ProviderSessionID: "wa-history", ProviderDisplayName: "history work", Resumable: true}},
		historyReport(historyLiveSession("res-live", "wa-list", "gen-1")),
		protocol.MessagesResult{
			ProviderSessionID: "wa-history",
			MessageCount:      1,
			Messages:          []protocol.Message{{Role: "user", Content: "history row conversation"}},
		},
	)

	output, diagnostics := runScope(t, stub, "history endpoint-1\nmessages 1\nexit\n", ColorPolicy{})
	if diagnostics != "" {
		t.Fatalf("unexpected diagnostics: %q", diagnostics)
	}
	if !strings.Contains(output, "history row conversation") {
		t.Fatalf("conversation missing: %q", output)
	}
	if len(stub.messagesSessions) != 1 || stub.messagesSessions[0] != "wa-history" {
		t.Fatalf("messages sessions = %v, want one read of wa-history", stub.messagesSessions)
	}
}

// TestInteractiveMessagesRejectsOutOfRangeRow proves an out-of-range number is
// refused with the valid range instead of reading an arbitrary row.
func TestInteractiveMessagesRejectsOutOfRangeRow(t *testing.T) {
	stub := messagesScenarioStub(
		[]protocol.HistoryRow{{ProviderSessionID: "wa-one", ProviderDisplayName: "one", Resumable: true}},
		historyReport(),
		protocol.MessagesResult{},
	)

	_, diagnostics := runScope(t, stub, "history endpoint-1\nmessages 9\nexit\n", ColorPolicy{})
	if !strings.Contains(diagnostics, "out of range") {
		t.Fatalf("diagnostics = %q, want the range rejection", diagnostics)
	}
	if len(stub.messagesCalls) != 0 {
		t.Fatalf("messages calls = %v, want none", stub.messagesCalls)
	}
}

// TestInteractiveMessagesReportsProviderFailure proves a provider failure is
// reported as a failure rather than as an empty conversation.
func TestInteractiveMessagesReportsProviderFailure(t *testing.T) {
	stub := messagesScenarioStub(
		[]protocol.HistoryRow{{ProviderSessionID: "wa-one", ProviderDisplayName: "one", Resumable: true}},
		historyReport(),
		protocol.MessagesResult{ProviderSessionID: "wa-one", ErrorCode: protocol.MessagesSessionNotFound},
	)

	_, diagnostics := runScope(t, stub, "history endpoint-1\nmessages 1\nexit\n", ColorPolicy{})
	if !strings.Contains(diagnostics, protocol.MessagesSessionNotFound) {
		t.Fatalf("diagnostics = %q, want the provider failure code", diagnostics)
	}
}

// TestRenderMessagesLabelsTruncation proves a bounded window is never presented as
// a complete conversation.
func TestRenderMessagesLabelsTruncation(t *testing.T) {
	view := MessagesView{
		EndpointID:        "ep-1",
		ProviderSessionID: "wa-1",
		Rows:              []MessagesViewRow{{No: 1, Role: "user", Content: "only one"}},
		MessageCount:      40,
		Truncated:         true,
	}
	var out strings.Builder
	if err := RenderMessages(&out, view, ColorPolicy{}); err != nil {
		t.Fatalf("RenderMessages: %v", err)
	}
	if !strings.Contains(out.String(), "bounded window") || !strings.Contains(out.String(), "1 of 40") {
		t.Fatalf("truncation was not labelled: %q", out.String())
	}
}

// TestRenderMessagesLabelsShortenedBodySeparately proves a shortened body is not
// reported as a bounded window, and that a bounded window is not reported as a
// shortened body.
//
// The two facts are different: a window means messages are missing, while a
// shortened body means every message is present and only one is cut. Reporting the
// window label when nothing was omitted claims messages were dropped, which is the
// same class of error as presenting a shortened body as complete.
//
// The label is derived from the rows rather than from view.Truncated, because
// Truncated now means only that the provider reported more messages than were
// returned or that the transport byte guard stopped the read. Reading it for the
// body label would claim bodies were shortened when none were, so the second case
// below is the guard for that distinction.
//
// The bound is set on the view rather than pre-applied to the content, because the
// renderer recomputes the per-row outcome from the bound it actually applied. A
// hand-set Shortened flag would be overwritten, so a fixture that set it would
// prove nothing about the renderer.
func TestRenderMessagesLabelsShortenedBodySeparately(t *testing.T) {
	shortened := MessagesView{
		EndpointID:        "ep-1",
		ProviderSessionID: "wa-1",
		Rows:              []MessagesViewRow{{No: 1, Role: "user", Content: "cutting"}},
		MessageCount:      1,
		MaxChars:          3,
	}
	var out strings.Builder
	if err := RenderMessages(&out, shortened, ColorPolicy{}); err != nil {
		t.Fatalf("RenderMessages: %v", err)
	}
	rendered := out.String()
	if strings.Contains(rendered, "bounded window") {
		t.Fatalf("a shortened body was reported as a bounded window: %q", rendered)
	}
	if !strings.Contains(rendered, "shortened") {
		t.Fatalf("a shortened body was not labelled: %q", rendered)
	}

	window := MessagesView{
		EndpointID:        "ep-1",
		ProviderSessionID: "wa-1",
		Rows:              []MessagesViewRow{{No: 1, Role: "user", Content: "whole"}},
		MessageCount:      40,
		Truncated:         true,
	}
	out.Reset()
	if err := RenderMessages(&out, window, ColorPolicy{}); err != nil {
		t.Fatalf("RenderMessages: %v", err)
	}
	rendered = out.String()
	if strings.Contains(rendered, "shortened") {
		t.Fatalf("a bounded window was reported as a shortened body: %q", rendered)
	}
	if !strings.Contains(rendered, "bounded window") {
		t.Fatalf("a bounded window was not labelled: %q", rendered)
	}
}

// TestRenderMessagesKeepsStructuredBodiesReadableUnderABound proves the display
// bound is applied to rendered text rather than to the stored body. Bounding the
// stored body first would cut a structured body into invalid JSON, and the
// renderer's documented unchanged-on-invalid-JSON fallback would then print the
// fragment verbatim, which is the defect this test guards.
func TestRenderMessagesKeepsStructuredBodiesReadableUnderABound(t *testing.T) {
	dictBody := `{"alpha":"first value","beta":{"nested":"inner value"},"gamma":["one","two"]}`
	listBody := `[{"name":"first item","state":"ready"},{"name":"second item","state":"waiting"}]`
	for _, tc := range []struct {
		name    string
		content string
		want    []string
	}{
		{"dict under a character bound", dictBody, []string{"alpha: first value", "nested: inner value", "- one"}},
		{"dict under a token bound", dictBody, []string{"alpha: first value", "beta:"}},
		{"list under a character bound", listBody, []string{"[1]", "name: first item", "[2]", "name: second item"}},
		{"list under a token bound", listBody, []string{"[1]", "name: first item"}},
	} {
		t.Run(tc.name, func(t *testing.T) {
			view := MessagesView{
				EndpointID:        "ep-1",
				ProviderSessionID: "wa-1",
				Rows:              []MessagesViewRow{{No: 1, Role: "user", Content: tc.content}},
				MessageCount:      1,
			}
			if strings.Contains(tc.name, "character") {
				view.MaxChars = 62
			} else {
				view.MaxTokens = 12
			}
			var out strings.Builder
			if err := RenderMessages(&out, view, ColorPolicy{}); err != nil {
				t.Fatalf("RenderMessages: %v", err)
			}
			rendered := out.String()
			for _, want := range tc.want {
				if !strings.Contains(rendered, want) {
					t.Fatalf("rendered output lost %q: %q", want, rendered)
				}
			}
			for _, fragment := range []string{`{"`, `[{`, `"alpha"`, `"name"`} {
				if strings.Contains(rendered, fragment) {
					t.Fatalf("rendered output contains raw JSON fragment %q: %q", fragment, rendered)
				}
			}
			if !strings.Contains(rendered, "shortened") {
				t.Fatalf("the bound did not shorten anything, so this case proves nothing: %q", rendered)
			}
		})
	}
}

// TestRenderMessagesBoundsRenderedTextNotStoredBody proves a bound small enough
// to cut the stored body still yields readable text, because the bound acts on
// the rendered form. A stored-body bound would produce `{"alpha":"...` here.
func TestRenderMessagesBoundsRenderedTextNotStoredBody(t *testing.T) {
	view := MessagesView{
		EndpointID:        "ep-1",
		ProviderSessionID: "wa-1",
		Rows:              []MessagesViewRow{{No: 1, Role: "user", Content: `{"alpha":"first value","beta":"second value"}`}},
		MessageCount:      1,
		MaxChars:          12,
	}
	var out strings.Builder
	if err := RenderMessages(&out, view, ColorPolicy{}); err != nil {
		t.Fatalf("RenderMessages: %v", err)
	}
	rendered := out.String()
	if strings.Contains(rendered, `{"`) {
		t.Fatalf("a tight bound printed raw JSON: %q", rendered)
	}
	if !strings.Contains(rendered, "alpha: first") {
		t.Fatalf("a tight bound did not keep the rendered key: %q", rendered)
	}
	if !strings.Contains(rendered, "shortened") {
		t.Fatalf("a tight bound was not labelled: %q", rendered)
	}
}

// TestRenderMessagesOmitsLabelWhenComplete proves a complete conversation carries
// no trailer, so a clean read is not decorated with a truncation notice.
func TestRenderMessagesOmitsLabelWhenComplete(t *testing.T) {
	view := MessagesView{
		EndpointID:        "ep-1",
		ProviderSessionID: "wa-1",
		Rows:              []MessagesViewRow{{No: 1, Role: "user", Content: "whole"}},
		MessageCount:      1,
	}
	var out strings.Builder
	if err := RenderMessages(&out, view, ColorPolicy{}); err != nil {
		t.Fatalf("RenderMessages: %v", err)
	}
	rendered := out.String()
	if strings.Contains(rendered, "bounded window") || strings.Contains(rendered, "shortened") {
		t.Fatalf("a complete conversation carried a truncation label: %q", rendered)
	}
}

// TestRenderMessagesStripsControlSequences proves provider prose cannot reach the
// terminal as a trusted instruction. A conversation is untrusted data, so an
// escape sequence in it must be neutralized exactly like followed output.
func TestRenderMessagesStripsControlSequences(t *testing.T) {
	view := MessagesView{
		EndpointID:        "ep-1",
		ProviderSessionID: "wa-1",
		Rows:              []MessagesViewRow{{No: 1, Role: "user", Content: "before \x1b[31mred\x1b[0m after"}},
		MessageCount:      1,
	}
	var out strings.Builder
	if err := RenderMessages(&out, view, ColorPolicy{}); err != nil {
		t.Fatalf("RenderMessages: %v", err)
	}
	if strings.Contains(out.String(), "\x1b[31m") {
		t.Fatalf("a control sequence survived rendering: %q", out.String())
	}
	if !strings.Contains(out.String(), "before") || !strings.Contains(out.String(), "after") {
		t.Fatalf("the message body was lost: %q", out.String())
	}
}

// TestRenderMessagesMarksAbsentRole proves a record whose speaker was not reported
// is visibly unknown instead of looking like a formatting gap.
func TestRenderMessagesMarksAbsentRole(t *testing.T) {
	view := MessagesView{
		EndpointID:        "ep-1",
		ProviderSessionID: "wa-1",
		Rows:              []MessagesViewRow{{No: 1, Role: "", Content: "body"}},
		MessageCount:      1,
	}
	var out strings.Builder
	if err := RenderMessages(&out, view, ColorPolicy{}); err != nil {
		t.Fatalf("RenderMessages: %v", err)
	}
	if !strings.Contains(out.String(), "Role: -") {
		t.Fatalf("an absent role was not marked: %q", out.String())
	}
}

// TestRenderMessagesEmptyIsNotAnError proves a session with no recorded messages
// renders a clear statement rather than nothing, so an empty result is not
// mistaken for a failed read.
func TestRenderMessagesEmptyIsNotAnError(t *testing.T) {
	var out strings.Builder
	if err := RenderMessages(&out, MessagesView{EndpointID: "ep-1", ProviderSessionID: "wa-1"}, ColorPolicy{}); err != nil {
		t.Fatalf("RenderMessages: %v", err)
	}
	if !strings.Contains(out.String(), "no messages recorded") {
		t.Fatalf("an empty conversation was not stated: %q", out.String())
	}
}

// TestBuildMessagesViewNumbersRows proves numbering is a pure function of the
// result, so the text and JSON forms cannot disagree.
func TestBuildMessagesViewNumbersRows(t *testing.T) {
	view := BuildMessagesView("ep-1", protocol.MessagesResult{
		ProviderSessionID: "wa-1",
		MessageCount:      2,
		Messages: []protocol.Message{
			{Role: "user", Content: "a"},
			{Role: "assistant", Content: "b"},
		},
	}, 0, 0)
	if len(view.Rows) != 2 || view.Rows[0].No != 1 || view.Rows[1].No != 2 {
		t.Fatalf("rows = %+v", view.Rows)
	}
	if view.EndpointID != "ep-1" || view.ProviderSessionID != "wa-1" || view.MessageCount != 2 {
		t.Fatalf("view = %+v", view)
	}
}

// messagesRunnerStub adds the optional MessagesQuerier seam to the shared history
// stub, so the standalone runner can be exercised with the same endpoint and
// inventory fixtures every other runner test uses.
type messagesRunnerStub struct {
	*historyStubAPI
	messages      map[string]protocol.MessagesResult
	messagesEr    map[string]error
	messagesCalls []string
	// maxChars records the caller bound of every read, so a test can prove the
	// standalone flag reached the seam instead of being dropped on the way.
	maxChars []int
	// maxTokens records the token bound of every read, so a test can prove the
	// default and the flag both reached the seam.
	maxTokens []int
}

// GetMessages records the queried endpoint and bound.
func (s *messagesRunnerStub) GetMessages(_ context.Context, endpointID, _ string, maxChars, maxTokens int) (protocol.MessagesResult, error) {
	s.messagesCalls = append(s.messagesCalls, endpointID)
	s.maxChars = append(s.maxChars, maxChars)
	s.maxTokens = append(s.maxTokens, maxTokens)
	if err := s.messagesEr[endpointID]; err != nil {
		return protocol.MessagesResult{}, err
	}
	return s.messages[endpointID], nil
}

// messagesRunnerScenario builds one online endpoint whose conversation is the
// given result.
func messagesRunnerScenario(result protocol.MessagesResult) *messagesRunnerStub {
	return &messagesRunnerStub{
		historyStubAPI: &historyStubAPI{endpoints: []protocol.Endpoint{{EndpointID: "ep-1", Hostname: "host-one"}}},
		messages:       map[string]protocol.MessagesResult{"ep-1": result},
	}
}

// TestCommandRunnerMessagesRequiresEndpointArgument proves a blank endpoint is a
// usage error rather than a fleet-wide read.
//
// A conversation read is endpoint-scoped, so an empty target must never fan out:
// provider session IDs may collide across endpoints, and a merged read could not
// identify the session the operator asked for.
func TestCommandRunnerMessagesRequiresEndpointArgument(t *testing.T) {
	stub := messagesRunnerScenario(protocol.MessagesResult{})
	err := (CommandRunner{API: stub, Policy: LegacyPolicy}).Messages(context.Background(), io.Discard, io.Discard, "  ", "wa-1", 0, 0, false, ColorPolicy{})
	if err == nil || !strings.Contains(err.Error(), "usage: messages") {
		t.Fatalf("err=%v", err)
	}
	if len(stub.messagesCalls) != 0 {
		t.Fatalf("usage error must not query: %v", stub.messagesCalls)
	}
}

// TestCommandRunnerMessagesRequiresSessionArgument proves a blank session is a
// usage error rather than a read of whatever session happens to be first.
func TestCommandRunnerMessagesRequiresSessionArgument(t *testing.T) {
	stub := messagesRunnerScenario(protocol.MessagesResult{})
	err := (CommandRunner{API: stub, Policy: LegacyPolicy}).Messages(context.Background(), io.Discard, io.Discard, "ep-1", "   ", 0, 0, false, ColorPolicy{})
	if err == nil || !strings.Contains(err.Error(), "usage: messages") {
		t.Fatalf("err=%v", err)
	}
	if len(stub.messagesCalls) != 0 {
		t.Fatalf("usage error must not query: %v", stub.messagesCalls)
	}
}

// TestCommandRunnerMessagesReportsMissingSeam proves a client without the seam
// reports the missing capability instead of rendering an empty conversation.
//
// An empty conversation is a successful answer for a session that recorded
// nothing, so silently degrading to it would present a missing capability as a
// real observation.
func TestCommandRunnerMessagesReportsMissingSeam(t *testing.T) {
	api := &historyStubAPI{endpoints: []protocol.Endpoint{{EndpointID: "ep-1"}}}
	err := (CommandRunner{API: api, Policy: LegacyPolicy}).Messages(context.Background(), io.Discard, io.Discard, "ep-1", "wa-1", 0, 0, false, ColorPolicy{})
	if err == nil || !strings.Contains(err.Error(), "messages is unavailable") {
		t.Fatalf("err=%v", err)
	}
}

// TestCommandRunnerMessagesRejectsUnknownEndpoint proves an unknown endpoint is
// reported before any provider read is attempted.
func TestCommandRunnerMessagesRejectsUnknownEndpoint(t *testing.T) {
	stub := messagesRunnerScenario(protocol.MessagesResult{})
	err := (CommandRunner{API: stub, Policy: LegacyPolicy}).Messages(context.Background(), io.Discard, io.Discard, "ep-missing", "wa-1", 0, 0, false, ColorPolicy{})
	if err == nil || !strings.Contains(err.Error(), "was not found") {
		t.Fatalf("err=%v", err)
	}
	if len(stub.messagesCalls) != 0 {
		t.Fatalf("unknown endpoint must not query: %v", stub.messagesCalls)
	}
}

// TestCommandRunnerMessagesForwardsMaxChars proves the standalone bound reaches
// the seam, so --max-chars is not silently dropped on the way to the provider.
func TestCommandRunnerMessagesForwardsMaxChars(t *testing.T) {
	stub := messagesRunnerScenario(protocol.MessagesResult{ProviderSessionID: "wa-1"})
	err := (CommandRunner{API: stub, Policy: LegacyPolicy}).Messages(context.Background(), io.Discard, io.Discard, "ep-1", "wa-1", 1234, 0, false, ColorPolicy{})
	if err != nil {
		t.Fatalf("err=%v", err)
	}
	if len(stub.maxChars) != 1 || stub.maxChars[0] != 1234 {
		t.Fatalf("maxChars=%v", stub.maxChars)
	}
}

// TestCommandRunnerMessagesReportsResultErrorCode proves a result carrying an
// error code is a failure, not an empty conversation.
//
// The adapter reports a provider failure in the result rather than as a transport
// error, so a runner that ignored the code would print "no messages recorded" for
// a session it never read.
func TestCommandRunnerMessagesReportsResultErrorCode(t *testing.T) {
	stub := messagesRunnerScenario(protocol.MessagesResult{ProviderSessionID: "wa-1", ErrorCode: protocol.MessagesProviderError})
	var out strings.Builder
	err := (CommandRunner{API: stub, Policy: LegacyPolicy}).Messages(context.Background(), &out, io.Discard, "ep-1", "wa-1", 0, 0, false, ColorPolicy{})
	if err == nil || !strings.Contains(err.Error(), protocol.MessagesProviderError) {
		t.Fatalf("err=%v", err)
	}
	if out.Len() != 0 {
		t.Fatalf("failed read wrote to stdout: %q", out.String())
	}
}

// TestCommandRunnerMessagesRendersConversation proves the text form prints one
// block per message with its role.
func TestCommandRunnerMessagesRendersConversation(t *testing.T) {
	stub := messagesRunnerScenario(protocol.MessagesResult{
		ProviderSessionID: "wa-1",
		MessageCount:      2,
		Messages: []protocol.Message{
			{Role: "user", Content: "first question"},
			{Role: "assistant", Content: "second answer"},
		},
	})
	var out strings.Builder
	err := (CommandRunner{API: stub, Policy: LegacyPolicy}).Messages(context.Background(), &out, io.Discard, "ep-1", "wa-1", 0, 0, false, ColorPolicy{})
	if err != nil {
		t.Fatalf("err=%v", err)
	}
	rendered := out.String()
	for _, fragment := range []string{"#1 - Role: USER", "#2 - Role: ASSISTANT", "first question", "second answer"} {
		if !strings.Contains(rendered, fragment) {
			t.Fatalf("rendered output missing %q: %s", fragment, rendered)
		}
	}
}

// TestCommandRunnerMessagesJSONMode proves --json emits the machine document
// instead of the rendered text, so a script never parses prose.
func TestCommandRunnerMessagesJSONMode(t *testing.T) {
	stub := messagesRunnerScenario(protocol.MessagesResult{
		ProviderSessionID: "wa-1",
		MessageCount:      1,
		Messages:          []protocol.Message{{Role: "user", Content: "only message"}},
	})
	var out strings.Builder
	err := (CommandRunner{API: stub, Policy: LegacyPolicy}).Messages(context.Background(), &out, io.Discard, "ep-1", "wa-1", 0, 0, true, ColorPolicy{})
	if err != nil {
		t.Fatalf("err=%v", err)
	}
	var decoded MessagesView
	if err := json.Unmarshal([]byte(out.String()), &decoded); err != nil {
		t.Fatalf("json mode must emit one document: %v output=%s", err, out.String())
	}
	if decoded.EndpointID != "ep-1" || decoded.ProviderSessionID != "wa-1" || len(decoded.Rows) != 1 {
		t.Fatalf("decoded=%+v", decoded)
	}
	// The prose form is identified by its rule and header, not by a row label
	// that no longer exists. Asserting a token the renderer never emits would
	// pass even if prose were emitted.
	if strings.Contains(out.String(), messagesRule) || strings.Contains(out.String(), "Role: ") {
		t.Fatalf("json mode must not render prose: %s", out.String())
	}
}

// TestRenderMessagesMatchesDocumentedLayout proves the rendered conversation is
// byte-identical to the layout this cluster documents.
//
// The layout is this cluster's own presentation, so the expected value is the
// documented form rather than any provider's output. It is written out literally
// rather than assembled from the renderer's own constants, because a test that
// reuses the constants proves only that the code agrees with itself.
func TestRenderMessagesMatchesDocumentedLayout(t *testing.T) {
	view := MessagesView{
		EndpointID:        "ep-1",
		ProviderSessionID: "wa-1",
		Rows: []MessagesViewRow{
			{No: 1, Role: "user", Content: "first question", WordCount: 14, TokenCount: 3, CreatedAtMS: 1762647150285},
			{No: 2, Role: "assistant", Content: "second answer", WordCount: 13, TokenCount: 3},
		},
		MessageCount: 2,
	}
	var out strings.Builder
	if err := RenderMessages(&out, view, ColorPolicy{}); err != nil {
		t.Fatalf("RenderMessages: %v", err)
	}
	rule := strings.Repeat("=", 80)
	want := "\n" + rule + "\n" +
		"#1 - Role: USER - Words: 14 - Tokens: 3 - " + formatMessagesTime(1762647150285) + "\n" +
		rule + "\n" +
		"first question\n" +
		"\n" + rule + "\n" +
		"#2 - Role: ASSISTANT - Words: 13 - Tokens: 3\n" +
		rule + "\n" +
		"second answer\n" +
		"\n"
	if got := out.String(); got != want {
		t.Fatalf("rendered layout does not match the documented layout:\ngot  %q\nwant %q", got, want)
	}
}

// TestRenderMessagesRuleIsFixedWidth proves the rule is a fixed 80 columns and
// does not follow the terminal width.
//
// A rule that followed the terminal would make the same conversation look
// different on two terminals, and the header would no longer align with the rule
// above and below it.
func TestRenderMessagesRuleIsFixedWidth(t *testing.T) {
	view := MessagesView{
		EndpointID:        "ep-1",
		ProviderSessionID: "wa-1",
		Rows:              []MessagesViewRow{{No: 1, Role: "user", Content: "body"}},
		MessageCount:      1,
	}
	for _, width := range []int{40, 5, 200} {
		out := &layoutBuffer{layout: TableLayout{Width: width}}
		if err := RenderMessages(out, view, ColorPolicy{}); err != nil {
			t.Fatalf("RenderMessages: %v", err)
		}
		// Compare whole lines rather than substrings: a 40-character rule is a
		// substring of an 80-character rule, so a substring check would report a
		// width-following rule that does not exist.
		for _, line := range strings.Split(out.String(), "\n") {
			if line == "" || strings.Trim(line, "=") != "" {
				continue
			}
			if len(line) != messagesRuleWidth {
				t.Fatalf("width %d: a rule of %d columns was drawn, want %d: %q", width, len(line), messagesRuleWidth, line)
			}
		}
	}
}

// TestRenderMessagesHeaderCarriesCounts proves the header reports the word and
// token counts the adapter measured.
//
// The counts are carried through from the adapter rather than computed here,
// because the counting rule belongs to the adapter. A renderer that computed them
// itself would impose this provider's rule on every other provider.
func TestRenderMessagesHeaderCarriesCounts(t *testing.T) {
	view := MessagesView{
		EndpointID:        "ep-1",
		ProviderSessionID: "wa-1",
		Rows:              []MessagesViewRow{{No: 7, Role: "assistant", Content: "body", WordCount: 99535, TokenCount: 20004}},
		MessageCount:      1,
	}
	var out strings.Builder
	if err := RenderMessages(&out, view, ColorPolicy{}); err != nil {
		t.Fatalf("RenderMessages: %v", err)
	}
	if !strings.Contains(out.String(), "#7 - Role: ASSISTANT - Words: 99535 - Tokens: 20004") {
		t.Fatalf("the header did not carry the adapter's counts: %q", out.String())
	}
}

// TestRenderMessagesCountsSurviveTruncation proves a shortened body still reports
// the counts of the whole message.
//
// The counts describe the message, not the window, so truncating the body must not
// change them. A count taken after truncation would make the same message report a
// different size depending on how much of it was displayed.
func TestRenderMessagesCountsSurviveTruncation(t *testing.T) {
	view := MessagesView{
		EndpointID:        "ep-1",
		ProviderSessionID: "wa-1",
		Rows:              []MessagesViewRow{{No: 1, Role: "user", Content: "short...", WordCount: 5000, TokenCount: 1200}},
		MessageCount:      1,
		Truncated:         true,
	}
	var out strings.Builder
	if err := RenderMessages(&out, view, ColorPolicy{}); err != nil {
		t.Fatalf("RenderMessages: %v", err)
	}
	rendered := out.String()
	if !strings.Contains(rendered, "Words: 5000 - Tokens: 1200") {
		t.Fatalf("the counts were lost when the body was shortened: %q", rendered)
	}
	if !strings.Contains(rendered, "short...") {
		t.Fatalf("the shortened body was not rendered: %q", rendered)
	}
}

// TestRenderMessagesStylesHeaderWhenColorEnabled proves the header carries the
// trusted styling and the body does not. The header is application structure, so
// it is styled; the body is provider prose, so it stays plain.
func TestRenderMessagesStylesHeaderWhenColorEnabled(t *testing.T) {
	view := MessagesView{
		EndpointID:        "ep-1",
		ProviderSessionID: "wa-1",
		Rows:              []MessagesViewRow{{No: 1, Role: "user", Content: "plain body", CreatedAtMS: 1700000000000}},
		MessageCount:      1,
	}
	var out strings.Builder
	if err := RenderMessages(&out, view, ColorPolicy{Enabled: true}); err != nil {
		t.Fatalf("RenderMessages: %v", err)
	}
	rendered := out.String()
	if !strings.Contains(rendered, ansiBoldCyan+"#1"+ansiReset) {
		t.Fatalf("the row number was not styled: %q", rendered)
	}
	if !strings.Contains(rendered, ansiBoldCyan+"Role: USER"+ansiReset) {
		t.Fatalf("the role was not styled: %q", rendered)
	}
	if !strings.Contains(rendered, ansiDim) {
		t.Fatalf("the rule or time was not dimmed: %q", rendered)
	}
	// The body must not be wrapped in styling, because it is provider data.
	if strings.Contains(rendered, ansiBoldCyan+"plain body") {
		t.Fatalf("the provider body inherited trusted styling: %q", rendered)
	}
}

// TestRenderMessagesStripsControlSequencesWithColorEnabled proves the provider
// boundary still removes non-SGR sequences when colour is on. Colour being
// enabled must not widen the allow list to cursor movement, because provider prose
// could then reposition the cursor and overwrite a trusted row.
func TestRenderMessagesStripsControlSequencesWithColorEnabled(t *testing.T) {
	view := MessagesView{
		EndpointID:        "ep-1",
		ProviderSessionID: "wa-1",
		Rows:              []MessagesViewRow{{No: 1, Role: "user", Content: "before \x1b[2J\x1b[1;1Hafter"}},
		MessageCount:      1,
	}
	var out strings.Builder
	if err := RenderMessages(&out, view, ColorPolicy{Enabled: true}); err != nil {
		t.Fatalf("RenderMessages: %v", err)
	}
	rendered := out.String()
	if strings.Contains(rendered, "\x1b[2J") || strings.Contains(rendered, "\x1b[1;1H") {
		t.Fatalf("a cursor-control sequence survived with colour enabled: %q", rendered)
	}
	if !strings.Contains(rendered, "before") || !strings.Contains(rendered, "after") {
		t.Fatalf("the message body was lost: %q", rendered)
	}
}

// TestRenderMessagesMarksEmptyBody proves a record that carried no text is stated
// rather than left blank, so an empty body is not mistaken for a render failure.
func TestRenderMessagesMarksEmptyBody(t *testing.T) {
	view := MessagesView{
		EndpointID:        "ep-1",
		ProviderSessionID: "wa-1",
		Rows:              []MessagesViewRow{{No: 1, Role: "assistant", Content: "   \n\t"}},
		MessageCount:      1,
	}
	var out strings.Builder
	if err := RenderMessages(&out, view, ColorPolicy{}); err != nil {
		t.Fatalf("RenderMessages: %v", err)
	}
	if !strings.Contains(out.String(), "[No content]") {
		t.Fatalf("an empty body was not stated: %q", out.String())
	}
}

// TestRenderMessagesNoColorStaysPlain proves a disabled colour policy emits no
// escape sequence at all, so a redirected stream stays byte-identical to plain
// text.
func TestRenderMessagesNoColorStaysPlain(t *testing.T) {
	view := MessagesView{
		EndpointID:        "ep-1",
		ProviderSessionID: "wa-1",
		Rows:              []MessagesViewRow{{No: 1, Role: "user", Content: "body", CreatedAtMS: 1700000000000}},
		MessageCount:      1,
	}
	var out strings.Builder
	if err := RenderMessages(&out, view, ColorPolicy{}); err != nil {
		t.Fatalf("RenderMessages: %v", err)
	}
	if strings.Contains(out.String(), "\x1b") {
		t.Fatalf("a disabled colour policy emitted an escape sequence: %q", out.String())
	}
}
