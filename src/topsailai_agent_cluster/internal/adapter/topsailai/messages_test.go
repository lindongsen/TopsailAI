package topsailai

import (
	"context"
	"encoding/json"
	"errors"
	"strconv"
	"strings"
	"testing"
	"unicode/utf8"

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

// TestMessagesNeverForwardsMaxChars proves the display bound is applied by the
// adapter and never forwarded to the provider.
//
// The provider truncates the raw stored document, which cuts a structured body
// into invalid JSON. The adapter would then be unable to unwrap exactly the long
// messages an operator most wants to read, so the bound must be applied after
// unwrapping. Forwarding it would also make the bound act on the wrapper instead
// of on the text the operator reads.
func TestMessagesNeverForwardsMaxChars(t *testing.T) {
	runner := &perCallRunner{answers: [][]byte{
		[]byte(`{"session_id":"s1"}`),
		[]byte(`{"ok":true,"session_id":"s1","message_count":0,"messages":[]}`),
		[]byte(`{"session_id":"s1"}`),
		[]byte(`{"ok":true,"session_id":"s1","message_count":0,"messages":[]}`),
		[]byte(`{"session_id":"s1"}`),
		[]byte(`{"ok":true,"session_id":"s1","message_count":0,"messages":[]}`),
	}}
	adapter := messagesAdapter(t, runner)
	for _, bound := range []int{0, 10, protocol.MaxMessagesMaxChars * 10} {
		if _, err := adapter.Messages(context.Background(), protocol.MessagesQuery{ProviderSessionID: "s1", MaxChars: bound}); err != nil {
			t.Fatalf("bound %d: Messages: %v", bound, err)
		}
	}
	for _, call := range runner.calls {
		for _, arg := range call {
			if arg == "--max-chars" || arg == "-c" {
				t.Fatalf("argv %v forwards the display bound to the provider", call)
			}
		}
	}
}

// TestMessagesAppliesBoundAfterUnwrapping proves the bound shortens the readable
// text rather than the provider's wrapper.
//
// The fixture body is a step record whose raw_text is longer than the bound. If
// the bound were applied to the wrapper, the result would be a cut JSON fragment;
// if it were applied after unwrapping, the result is the readable prefix plus the
// provider's own ellipsis.
func TestMessagesAppliesBoundAfterUnwrapping(t *testing.T) {
	body := `{"raw_text":"` + strings.Repeat("x", 100) + `","step_name":"task"}`
	document := `{"ok":true,"session_id":"s1","message_count":1,"messages":[{"role":"user","content":` + strconv.Quote(body) + `}]}`
	runner := &perCallRunner{answers: [][]byte{[]byte(`{"session_id":"s1"}`), []byte(document)}}
	adapter := messagesAdapter(t, runner)
	result, err := adapter.Messages(context.Background(), protocol.MessagesQuery{ProviderSessionID: "s1", MaxChars: 40})
	if err != nil {
		t.Fatalf("Messages: %v", err)
	}
	if len(result.Messages) != 1 {
		t.Fatalf("messages = %d, want 1", len(result.Messages))
	}
	content := result.Messages[0].Content
	if strings.Contains(content, "raw_text") || strings.Contains(content, "step_name") {
		t.Fatalf("the bound was applied to the wrapper, not the readable text: %q", content)
	}
	if !strings.HasPrefix(content, "topsailai.task") {
		t.Fatalf("the unwrapped body lost its provider label: %q", content)
	}
	if !strings.HasSuffix(content, "...") {
		t.Fatalf("a shortened body was not marked with the provider's ellipsis: %q", content)
	}
	if !result.Truncated {
		t.Fatalf("a shortened body was not labelled truncated")
	}
}

// TestMessagesCountsComeFromTheStoredBody proves the counts describe the message
// as the provider stored it, not the shortened text.
//
// A count taken after truncation would make the same message report a different
// size depending on how much of it was displayed, so the header would disagree
// with the provider's own surface for the same record.
func TestMessagesCountsComeFromTheStoredBody(t *testing.T) {
	body := `{"raw_text":"` + strings.Repeat("x", 100) + `","step_name":"task"}`
	document := `{"ok":true,"session_id":"s1","message_count":1,"messages":[{"role":"user","content":` + strconv.Quote(body) + `}]}`
	runner := &perCallRunner{answers: [][]byte{[]byte(`{"session_id":"s1"}`), []byte(document)}}
	adapter := messagesAdapter(t, runner)
	result, err := adapter.Messages(context.Background(), protocol.MessagesQuery{ProviderSessionID: "s1", MaxChars: 10})
	if err != nil {
		t.Fatalf("Messages: %v", err)
	}
	if len(result.Messages) != 1 {
		t.Fatalf("messages = %d, want 1", len(result.Messages))
	}
	message := result.Messages[0]
	if message.WordCount != utf8.RuneCountInString(body) {
		t.Fatalf("word count = %d, want the stored body's %d", message.WordCount, utf8.RuneCountInString(body))
	}
	if message.TokenCount == 0 {
		t.Fatalf("token count was not measured")
	}
	if message.WordCount <= utf8.RuneCountInString(message.Content) {
		t.Fatalf("the count was taken after truncation: count=%d shown=%d", message.WordCount, utf8.RuneCountInString(message.Content))
	}
}

// TestMessagesLabelsTruncation proves a shortened body is labelled, and that the
// label is the display bound rather than a byte ceiling.
//
// The only bound applied to a body is the caller's character bound, so this test
// drives that bound. A byte ceiling would cut the body without an ellipsis, which
// is exactly the silent loss this test exists to prevent.
func TestMessagesLabelsTruncation(t *testing.T) {
	const bound = 50
	long := strings.Repeat("a", bound+10)
	document := `{"ok":true,"session_id":"s1","message_count":1,"messages":[{"role":"user","content":"` + long + `"}]}`
	runner := &perCallRunner{answers: [][]byte{[]byte(`{"session_id":"s1"}`), []byte(document)}}
	adapter := messagesAdapter(t, runner)
	result, err := adapter.Messages(context.Background(), protocol.MessagesQuery{ProviderSessionID: "s1", MaxChars: bound})
	if err != nil {
		t.Fatalf("Messages: %v", err)
	}
	if !result.Truncated {
		t.Fatalf("a shortened body was not labelled truncated")
	}
	if len(result.Messages) != 1 {
		t.Fatalf("messages = %d, want 1", len(result.Messages))
	}
	content := result.Messages[0].Content
	if !strings.HasSuffix(content, "...") {
		t.Fatalf("a shortened body was not marked with the provider's ellipsis: %q", content)
	}
	if got := utf8.RuneCountInString(strings.TrimSuffix(content, "...")); got != bound {
		t.Fatalf("kept %d characters, want the requested %d", got, bound)
	}
}

// TestMessagesKeepsUTF8Boundary proves a cut never splits a multi-byte character,
// because a byte slice would produce invalid text.
//
// The bound is counted in characters, so a body of three-byte runes must be cut
// after exactly the requested number of runes rather than at a byte offset.
func TestMessagesKeepsUTF8Boundary(t *testing.T) {
	const bound = 40
	content := strings.Repeat("中", bound+10)
	document := `{"ok":true,"session_id":"s1","message_count":1,"messages":[{"role":"user","content":"` + content + `"}]}`
	runner := &perCallRunner{answers: [][]byte{[]byte(`{"session_id":"s1"}`), []byte(document)}}
	adapter := messagesAdapter(t, runner)
	result, err := adapter.Messages(context.Background(), protocol.MessagesQuery{ProviderSessionID: "s1", MaxChars: bound})
	if err != nil {
		t.Fatalf("Messages: %v", err)
	}
	if len(result.Messages) != 1 {
		t.Fatalf("messages = %d, want 1", len(result.Messages))
	}
	got := result.Messages[0].Content
	// The kept text is the body minus the provider's ellipsis, so the prefix check
	// is made against that rather than against the marked form.
	kept := strings.TrimSuffix(got, "...")
	if kept == got {
		t.Fatalf("a shortened body was not marked with the provider's ellipsis: %q", got)
	}
	if !strings.HasPrefix(content, kept) {
		t.Fatalf("the cut did not land on a rune boundary")
	}
	if !utf8.ValidString(kept) {
		t.Fatalf("the cut produced invalid UTF-8")
	}
	for _, r := range kept {
		if r == '\uFFFD' {
			t.Fatalf("the cut produced a replacement rune")
		}
	}
	if n := utf8.RuneCountInString(kept); n != bound {
		t.Fatalf("kept %d runes, want the requested %d", n, bound)
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

// TestMessagesUnwrapsSingleStepRecord proves one wrapped body is shown as the
// provider's own human-facing surface shows it, instead of as JSON.
func TestMessagesUnwrapsSingleStepRecord(t *testing.T) {
	content := `{"raw_text":"重新全部编译打包一遍","step_name":"task"}`
	document := `{"ok":true,"session_id":"s1","message_count":1,"messages":[{"role":"user","content":` + quoteJSON(content) + `}]}`
	runner := &perCallRunner{answers: [][]byte{[]byte(`{"session_id":"s1"}`), []byte(document)}}
	adapter := messagesAdapter(t, runner)
	result, err := adapter.Messages(context.Background(), protocol.MessagesQuery{ProviderSessionID: "s1"})
	if err != nil {
		t.Fatalf("Messages: %v", err)
	}
	want := "topsailai.task\n重新全部编译打包一遍"
	if got := result.Messages[0].Content; got != want {
		t.Fatalf("content = %q, want %q", got, want)
	}
}

// TestMessagesUnwrapsStepRecordArray proves an array of step records is unwrapped
// entry by entry, which is the shape most assistant replies use.
func TestMessagesUnwrapsStepRecordArray(t *testing.T) {
	content := `[{"raw_text":"first","step_name":"think"},{"raw_text":"second","step_name":"answer"}]`
	document := `{"ok":true,"session_id":"s1","message_count":1,"messages":[{"role":"assistant","content":` + quoteJSON(content) + `}]}`
	runner := &perCallRunner{answers: [][]byte{[]byte(`{"session_id":"s1"}`), []byte(document)}}
	adapter := messagesAdapter(t, runner)
	result, err := adapter.Messages(context.Background(), protocol.MessagesQuery{ProviderSessionID: "s1"})
	if err != nil {
		t.Fatalf("Messages: %v", err)
	}
	want := "topsailai.think\nfirst\n\ntopsailai.answer\nsecond"
	if got := result.Messages[0].Content; got != want {
		t.Fatalf("content = %q, want %q", got, want)
	}
}

// TestMessagesKeepsPlainProseVerbatim proves a body that is not a step record is
// never rewritten, because the cluster must not invent structure that is absent.
func TestMessagesKeepsPlainProseVerbatim(t *testing.T) {
	content := "just a plain sentence with no wrapper"
	document := `{"ok":true,"session_id":"s1","message_count":1,"messages":[{"role":"user","content":` + quoteJSON(content) + `}]}`
	runner := &perCallRunner{answers: [][]byte{[]byte(`{"session_id":"s1"}`), []byte(document)}}
	adapter := messagesAdapter(t, runner)
	result, err := adapter.Messages(context.Background(), protocol.MessagesQuery{ProviderSessionID: "s1"})
	if err != nil {
		t.Fatalf("Messages: %v", err)
	}
	if got := result.Messages[0].Content; got != content {
		t.Fatalf("content = %q, want %q", got, content)
	}
}

// TestMessagesKeepsTruncatedWrapperVerbatim proves a body the provider cut into
// invalid JSON is still shown. Losing the surviving text would be worse than
// showing it in its raw form, and a truncated body is exactly the case where the
// remaining text still matters.
func TestMessagesKeepsTruncatedWrapperVerbatim(t *testing.T) {
	content := `{"raw_text":"---\n> File: /tmp/x.md > START\n# Learn`
	document := `{"ok":true,"session_id":"s1","message_count":1,"messages":[{"role":"user","content":` + quoteJSON(content) + `}]}`
	runner := &perCallRunner{answers: [][]byte{[]byte(`{"session_id":"s1"}`), []byte(document)}}
	adapter := messagesAdapter(t, runner)
	result, err := adapter.Messages(context.Background(), protocol.MessagesQuery{ProviderSessionID: "s1"})
	if err != nil {
		t.Fatalf("Messages: %v", err)
	}
	if got := result.Messages[0].Content; got != content {
		t.Fatalf("content = %q, want the original text %q", got, content)
	}
}

// TestMessagesKeepsMixedBodyVerbatim proves the unwrapper is all-or-nothing. A body
// whose elements are not all step records is shown verbatim, because half-unwrapping
// it would read like a complete conversation while silently dropping entries.
func TestMessagesKeepsMixedBodyVerbatim(t *testing.T) {
	content := `[{"raw_text":"kept","step_name":"think"},"not a record"]`
	document := `{"ok":true,"session_id":"s1","message_count":1,"messages":[{"role":"assistant","content":` + quoteJSON(content) + `}]}`
	runner := &perCallRunner{answers: [][]byte{[]byte(`{"session_id":"s1"}`), []byte(document)}}
	adapter := messagesAdapter(t, runner)
	result, err := adapter.Messages(context.Background(), protocol.MessagesQuery{ProviderSessionID: "s1"})
	if err != nil {
		t.Fatalf("Messages: %v", err)
	}
	if got := result.Messages[0].Content; got != content {
		t.Fatalf("content = %q, want the original text %q", got, content)
	}
}

// TestMessagesPreservesUnmodelledStepFields proves a field the cluster does not
// model survives the unwrapping, because a step record can carry evidence the
// operator still needs.
func TestMessagesPreservesUnmodelledStepFields(t *testing.T) {
	content := `{"raw_text":"body","step_name":"tool_call","tool_name":"bash"}`
	document := `{"ok":true,"session_id":"s1","message_count":1,"messages":[{"role":"assistant","content":` + quoteJSON(content) + `}]}`
	runner := &perCallRunner{answers: [][]byte{[]byte(`{"session_id":"s1"}`), []byte(document)}}
	adapter := messagesAdapter(t, runner)
	result, err := adapter.Messages(context.Background(), protocol.MessagesQuery{ProviderSessionID: "s1"})
	if err != nil {
		t.Fatalf("Messages: %v", err)
	}
	got := result.Messages[0].Content
	if !strings.HasPrefix(got, "topsailai.tool_call\nbody\n") {
		t.Fatalf("content = %q, want the step header and body first", got)
	}
	if !strings.Contains(got, `"tool_name": "bash"`) {
		t.Fatalf("content = %q, want the unmodelled field preserved", got)
	}
}

// TestMessagesUnwrapsBeforeBounding proves the unwrapping happens before the
// display bound is applied. Bounding first would cut the wrapper into invalid JSON,
// so the unwrapper would give up on exactly the long messages an operator most
// wants.
func TestMessagesUnwrapsBeforeBounding(t *testing.T) {
	// The wrapper alone pushes the body past the bound, so a bound-first order
	// would leave an unparsable fragment instead of the readable text.
	const bound = 200
	body := strings.Repeat("a", bound+50)
	content := `{"raw_text":"` + body + `","step_name":"task"}`
	document := `{"ok":true,"session_id":"s1","message_count":1,"messages":[{"role":"user","content":` + quoteJSON(content) + `}]}`
	runner := &perCallRunner{answers: [][]byte{[]byte(`{"session_id":"s1"}`), []byte(document)}}
	adapter := messagesAdapter(t, runner)
	result, err := adapter.Messages(context.Background(), protocol.MessagesQuery{ProviderSessionID: "s1", MaxChars: bound})
	if err != nil {
		t.Fatalf("Messages: %v", err)
	}
	got := result.Messages[0].Content
	if strings.HasPrefix(got, `{"raw_text"`) {
		t.Fatalf("content = %q, want the unwrapped text rather than a JSON fragment", got)
	}
	if !strings.HasPrefix(got, "topsailai.task\n") {
		t.Fatalf("content = %q, want the step header first", got)
	}
	if !strings.HasSuffix(got, "...") {
		t.Fatalf("content = %q, want the shortened body marked", got)
	}
}

// quoteJSON renders one string as a JSON literal, so a fixture can carry a body
// that is itself JSON without hand-escaping every quote.
func quoteJSON(value string) string {
	encoded, err := json.Marshal(value)
	if err != nil {
		panic(err)
	}
	return string(encoded)
}
