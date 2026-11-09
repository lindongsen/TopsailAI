package tui

import (
	"context"
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
	// messagesMaxChars records the caller bound of every interactive read. The REPL
	// always passes zero, so a non-zero value would mean the surface narrowed a
	// conversation the operator did not ask to narrow.
	messagesMaxChars []int
}

// GetMessages records the queried endpoint so a test can prove which endpoint the
// interactive surface addressed.
func (s *interactiveMessagesStub) GetMessages(_ context.Context, endpointID, _ string, maxChars int) (protocol.MessagesResult, error) {
	s.messagesCalls = append(s.messagesCalls, endpointID)
	s.messagesMaxChars = append(s.messagesMaxChars, maxChars)
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
			{ProviderSessionID: "wa-live", DisplayName: "live work", Resumable: false, ResumeBlockedReason: protocol.ResumeBlockedProviderRunning},
			{ProviderSessionID: "wa-past", DisplayName: "past work", Resumable: true, ResourceID: "res-past"},
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
	for _, want := range []string{"[1] user", "first question", "[2] assistant", "first answer"} {
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
			{ProviderSessionID: "wa-one", DisplayName: "one", Resumable: true},
			{ProviderSessionID: "wa-two", DisplayName: "two", Resumable: true},
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
		[]protocol.HistoryRow{{ProviderSessionID: "wa-live", DisplayName: "live work", Resumable: false, ResumeBlockedReason: protocol.ResumeBlockedProviderRunning}},
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
		[]protocol.HistoryRow{{ProviderSessionID: "wa-live", DisplayName: "live work", Resumable: false, ResumeBlockedReason: protocol.ResumeBlockedProviderRunning}},
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

// TestInteractiveMessagesRequiresHistoryForRowNumber proves a row number without a
// rendered table is refused rather than guessed, because the number has no meaning
// on its own.
func TestInteractiveMessagesRequiresHistoryForRowNumber(t *testing.T) {
	stub := messagesScenarioStub(nil, historyReport(), protocol.MessagesResult{})

	_, diagnostics := runScope(t, stub, "messages 1\nexit\n", ColorPolicy{})
	if !strings.Contains(diagnostics, "run history first") {
		t.Fatalf("diagnostics = %q, want the missing-table rejection", diagnostics)
	}
	if len(stub.messagesCalls) != 0 {
		t.Fatalf("messages calls = %v, want none", stub.messagesCalls)
	}
}

// TestInteractiveMessagesRejectsOutOfRangeRow proves an out-of-range number is
// refused with the valid range instead of reading an arbitrary row.
func TestInteractiveMessagesRejectsOutOfRangeRow(t *testing.T) {
	stub := messagesScenarioStub(
		[]protocol.HistoryRow{{ProviderSessionID: "wa-one", DisplayName: "one", Resumable: true}},
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
		[]protocol.HistoryRow{{ProviderSessionID: "wa-one", DisplayName: "one", Resumable: true}},
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
	if !strings.Contains(out.String(), "[1] -") {
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
	})
	if len(view.Rows) != 2 || view.Rows[0].No != 1 || view.Rows[1].No != 2 {
		t.Fatalf("rows = %+v", view.Rows)
	}
	if view.EndpointID != "ep-1" || view.ProviderSessionID != "wa-1" || view.MessageCount != 2 {
		t.Fatalf("view = %+v", view)
	}
}
