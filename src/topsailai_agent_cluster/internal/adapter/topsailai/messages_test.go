package topsailai

import (
	"context"
	"errors"
	"strings"
	"testing"

	"topsailai_agent_cluster/internal/protocol"
)

// perCallRunner answers each provider call with its own document, so a test can
// distinguish the existence pre-check from the history read.
type perCallRunner struct {
	calls   [][]string
	answers [][]byte
	errs    []error
}

func (r *perCallRunner) Run(_ context.Context, _ string, args []string, _ []byte) ([]byte, error) {
	r.calls = append(r.calls, append([]string(nil), args...))
	index := len(r.calls) - 1
	var output []byte
	if index < len(r.answers) {
		output = r.answers[index]
	}
	var err error
	if index < len(r.errs) {
		err = r.errs[index]
	}
	return output, err
}

// messagesAdapter builds an adapter backed by one sequenced runner.
func messagesAdapter(t *testing.T, runner commandRunner) *Adapter {
	t.Helper()
	result, err := newWithRunner(Config{AdapterID: "a1", Executable: "/provider", MaxOutput: 1 << 20, ResourceMapper: newFakeMapper(), PlatformProbe: func() (PlatformCapabilities, error) {
		return PlatformCapabilities{}, nil
	}}, runner)
	if err != nil {
		t.Fatalf("newWithRunner: %v", err)
	}
	return result
}

// TestMessagesChecksExistenceBeforeReadingHistory pins the two-call order. The
// provider reports a missing session as a successful empty history, so skipping
// the pre-check would present "no messages" for a session that never existed.
func TestMessagesChecksExistenceBeforeReadingHistory(t *testing.T) {
	runner := &perCallRunner{answers: [][]byte{
		[]byte(`{"session_id":"s1","status":"Idle"}`),
		[]byte(`{"ok":true,"session_id":"s1","message_count":1,"messages":[{"role":"user","content":"hi","create_time":"2026-10-13 13:18:48.450"}]}`),
	}}
	adapter := messagesAdapter(t, runner)
	result, err := adapter.Messages(context.Background(), protocol.MessagesQuery{ProviderSessionID: "s1"})
	if err != nil {
		t.Fatalf("Messages: %v", err)
	}
	if len(runner.calls) != 2 {
		t.Fatalf("calls = %d, want 2", len(runner.calls))
	}
	wantFirst := []string{"session", "info", "s1", "--json"}
	for i := range wantFirst {
		if runner.calls[0][i] != wantFirst[i] {
			t.Fatalf("first call = %v, want %v", runner.calls[0], wantFirst)
		}
	}
	wantSecond := []string{"session", "history", "s1", "--json"}
	for i := range wantSecond {
		if runner.calls[1][i] != wantSecond[i] {
			t.Fatalf("second call = %v, want %v", runner.calls[1], wantSecond)
		}
	}
	if len(result.Messages) != 1 || result.Messages[0].Content != "hi" || result.Messages[0].Role != "user" {
		t.Fatalf("unexpected messages: %+v", result.Messages)
	}
	if result.Messages[0].CreatedAtMS == 0 {
		t.Fatalf("created_at_ms was not converted")
	}
}

// TestMessagesReportsMissingSessionDistinctly proves a missing session is not
// reported as an empty conversation. The two claims need different remedies, so
// they must not share one code.
func TestMessagesReportsMissingSessionDistinctly(t *testing.T) {
	runner := &perCallRunner{
		answers: [][]byte{[]byte(`{"session_id":"gone","error_code":"session_not_found","message":"Session not found: gone"}`)},
		errs:    []error{errors.New("exit status 1")},
	}
	adapter := messagesAdapter(t, runner)
	result, err := adapter.Messages(context.Background(), protocol.MessagesQuery{ProviderSessionID: "gone"})
	if err == nil {
		t.Fatalf("expected an error for a missing session")
	}
	if result.ErrorCode != protocol.MessagesSessionNotFound {
		t.Fatalf("error code = %q, want %q", result.ErrorCode, protocol.MessagesSessionNotFound)
	}
	if len(runner.calls) != 1 {
		t.Fatalf("calls = %d, want 1: history must not be read for a missing session", len(runner.calls))
	}
}

// TestMessagesReportsStorageFailureAsProviderError proves a provider fault is not
// reported as a deleted session, because that would stop the operator looking for
// data that still exists.
func TestMessagesReportsStorageFailureAsProviderError(t *testing.T) {
	runner := &perCallRunner{
		answers: [][]byte{[]byte(`{"session_id":"s1","error_code":"lookup_failed","message":"storage unavailable"}`)},
		errs:    []error{errors.New("exit status 1")},
	}
	adapter := messagesAdapter(t, runner)
	result, err := adapter.Messages(context.Background(), protocol.MessagesQuery{ProviderSessionID: "s1"})
	if err == nil {
		t.Fatalf("expected an error for a storage failure")
	}
	if result.ErrorCode != protocol.MessagesProviderError {
		t.Fatalf("error code = %q; a storage failure must not be reported as a missing session", result.ErrorCode)
	}
	if len(runner.calls) != 1 {
		t.Fatalf("calls = %d, want 1: history must not be read after a failed lookup", len(runner.calls))
	}
}

// TestMessagesNeverForwardsDatabaseSelection pins that the adapter never passes
// --db-conn. Forwarding it would let a remote payload choose which store is read.
func TestMessagesNeverForwardsDatabaseSelection(t *testing.T) {
	runner := &perCallRunner{answers: [][]byte{
		[]byte(`{"session_id":"s1"}`),
		[]byte(`{"ok":true,"session_id":"s1","message_count":0,"messages":[]}`),
	}}
	adapter := messagesAdapter(t, runner)
	if _, err := adapter.Messages(context.Background(), protocol.MessagesQuery{ProviderSessionID: "s1"}); err != nil {
		t.Fatalf("Messages: %v", err)
	}
	for _, call := range runner.calls {
		for _, arg := range call {
			if strings.Contains(arg, "db-conn") || strings.Contains(arg, "--db") {
				t.Fatalf("argv %v forwards a database selector", call)
			}
		}
	}
}

// TestMessagesClampsMaxChars proves a caller cannot request a bound the provider
// would silently reduce, and that zero keeps the provider default.
func TestMessagesClampsMaxChars(t *testing.T) {
	runner := &perCallRunner{answers: [][]byte{
		[]byte(`{"session_id":"s1"}`),
		[]byte(`{"ok":true,"session_id":"s1","message_count":0,"messages":[]}`),
		[]byte(`{"session_id":"s1"}`),
		[]byte(`{"ok":true,"session_id":"s1","message_count":0,"messages":[]}`),
	}}
	adapter := messagesAdapter(t, runner)
	if _, err := adapter.Messages(context.Background(), protocol.MessagesQuery{ProviderSessionID: "s1", MaxChars: protocol.MaxMessagesMaxChars * 10}); err != nil {
		t.Fatalf("Messages: %v", err)
	}
	historyArgs := runner.calls[1]
	found := false
	for i, arg := range historyArgs {
		if arg == "--max-chars" {
			found = true
			if historyArgs[i+1] != "100000" {
				t.Fatalf("max-chars = %q, want the clamped 100000", historyArgs[i+1])
			}
		}
	}
	if !found {
		t.Fatalf("argv %v omits --max-chars", historyArgs)
	}
	if _, err := adapter.Messages(context.Background(), protocol.MessagesQuery{ProviderSessionID: "s1"}); err != nil {
		t.Fatalf("Messages: %v", err)
	}
	for _, arg := range runner.calls[3] {
		if arg == "--max-chars" {
			t.Fatalf("argv %v passes --max-chars for an unset bound", runner.calls[3])
		}
	}
}

// TestMessagesLabelsTruncation proves a bounded window is never presented as a
// complete conversation.
func TestMessagesLabelsTruncation(t *testing.T) {
	long := strings.Repeat("a", protocol.MaxMessageContentBytes+10)
	document := `{"ok":true,"session_id":"s1","message_count":1,"messages":[{"role":"user","content":"` + long + `"}]}`
	runner := &perCallRunner{answers: [][]byte{[]byte(`{"session_id":"s1"}`), []byte(document)}}
	adapter := messagesAdapter(t, runner)
	result, err := adapter.Messages(context.Background(), protocol.MessagesQuery{ProviderSessionID: "s1"})
	if err != nil {
		t.Fatalf("Messages: %v", err)
	}
	if !result.Truncated {
		t.Fatalf("an oversized message was not labelled truncated")
	}
	if len(result.Messages) != 1 || len(result.Messages[0].Content) != protocol.MaxMessageContentBytes {
		t.Fatalf("content length = %d, want %d", len(result.Messages[0].Content), protocol.MaxMessageContentBytes)
	}
}

// TestMessagesKeepsUTF8Boundary proves a cut never splits a multi-byte character,
// because a raw byte slice would produce invalid text.
func TestMessagesKeepsUTF8Boundary(t *testing.T) {
	// Three-byte runes fill the bound exactly, so the cut lands mid-rune unless it
	// is moved back to a rune start.
	content := strings.Repeat("中", protocol.MaxMessageContentBytes/3+1)
	document := `{"ok":true,"session_id":"s1","message_count":1,"messages":[{"role":"user","content":"` + content + `"}]}`
	runner := &perCallRunner{answers: [][]byte{[]byte(`{"session_id":"s1"}`), []byte(document)}}
	adapter := messagesAdapter(t, runner)
	result, err := adapter.Messages(context.Background(), protocol.MessagesQuery{ProviderSessionID: "s1"})
	if err != nil {
		t.Fatalf("Messages: %v", err)
	}
	if len(result.Messages) != 1 {
		t.Fatalf("messages = %d, want 1", len(result.Messages))
	}
	if !strings.HasPrefix(content, result.Messages[0].Content) {
		t.Fatalf("the cut did not land on a rune boundary")
	}
	for _, r := range result.Messages[0].Content {
		if r == '\uFFFD' {
			t.Fatalf("the cut produced a replacement rune")
		}
	}
}

// TestMessagesRejectsEmptySessionID proves an empty selector fails closed instead
// of reading an arbitrary session.
func TestMessagesRejectsEmptySessionID(t *testing.T) {
	runner := &perCallRunner{}
	adapter := messagesAdapter(t, runner)
	result, err := adapter.Messages(context.Background(), protocol.MessagesQuery{ProviderSessionID: "   "})
	if err == nil {
		t.Fatalf("expected an error for an empty session ID")
	}
	if result.ErrorCode != protocol.MessagesProviderError {
		t.Fatalf("error code = %q, want %q", result.ErrorCode, protocol.MessagesProviderError)
	}
	if len(runner.calls) != 0 {
		t.Fatalf("calls = %d, want 0", len(runner.calls))
	}
}
