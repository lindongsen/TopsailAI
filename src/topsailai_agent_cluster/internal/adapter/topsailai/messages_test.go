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

// TestMessagesNeverForwardsMaxChars proves the display bound is never forwarded to
// the provider.
//
// The provider truncates the raw stored document, which cuts a structured body into
// invalid JSON. The adapter would then be unable to unwrap exactly the long messages
// an operator most wants to read, so the bound must never reach the provider.
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

// TestMessagesReturnsTheWholeBodyRegardlessOfBounds proves the adapter never
// shortens a body.
//
// A display bound is a presentation decision, so it belongs to the renderer that
// presents the body. Cutting the stored text here would cut a structured body into
// invalid JSON, and the renderer would then have to print the fragment verbatim
// because it could no longer parse it. The adapter therefore returns every body
// whole and reports only what the provider itself reported.
func TestMessagesReturnsTheWholeBodyRegardlessOfBounds(t *testing.T) {
	body := `{"raw_text":"` + strings.Repeat("x", 100) + `","step_name":"task"}`
	document := `{"ok":true,"session_id":"s1","message_count":1,"messages":[{"role":"user","content":` + strconv.Quote(body) + `}]}`
	for _, tc := range []struct {
		name  string
		query protocol.MessagesQuery
	}{
		{"character bound", protocol.MessagesQuery{ProviderSessionID: "s1", MaxChars: 40}},
		{"token bound", protocol.MessagesQuery{ProviderSessionID: "s1", MaxTokens: 3}},
		{"both bounds", protocol.MessagesQuery{ProviderSessionID: "s1", MaxChars: 40, MaxTokens: 3}},
	} {
		t.Run(tc.name, func(t *testing.T) {
			runner := &perCallRunner{answers: [][]byte{[]byte(`{"session_id":"s1"}`), []byte(document)}}
			adapter := messagesAdapter(t, runner)
			result, err := adapter.Messages(context.Background(), tc.query)
			if err != nil {
				t.Fatalf("Messages: %v", err)
			}
			if len(result.Messages) != 1 {
				t.Fatalf("messages = %d, want 1", len(result.Messages))
			}
			content := result.Messages[0].Content
			if strings.Contains(content, "raw_text") || strings.Contains(content, "step_name") {
				t.Fatalf("the body was not unwrapped: %q", content)
			}
			if !strings.HasPrefix(content, "topsailai.task") {
				t.Fatalf("the unwrapped body lost its provider label: %q", content)
			}
			if strings.HasSuffix(content, "...") {
				t.Fatalf("the adapter shortened the body: %q", content)
			}
			if !strings.Contains(content, strings.Repeat("x", 100)) {
				t.Fatalf("the adapter dropped part of the body: %q", content)
			}
			if result.Truncated {
				t.Fatalf("a display bound was reported as a provider truncation")
			}
		})
	}
}

// TestMessagesCountsComeFromTheStoredBody proves the counts describe the message as
// the provider stored it, not the unwrapped text.
//
// A count taken after unwrapping would describe a different string than the one the
// provider measured, so the header would disagree with the provider's own surface
// for the same record.
func TestMessagesCountsComeFromTheStoredBody(t *testing.T) {
	body := `{"raw_text":"` + strings.Repeat("x", 100) + `","step_name":"task"}`
	document := `{"ok":true,"session_id":"s1","message_count":1,"messages":[{"role":"user","content":` + strconv.Quote(body) + `}]}`
	runner := &perCallRunner{answers: [][]byte{[]byte(`{"session_id":"s1"}`), []byte(document)}}
	adapter := messagesAdapter(t, runner)
	result, err := adapter.Messages(context.Background(), protocol.MessagesQuery{ProviderSessionID: "s1"})
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
		t.Fatalf("the count was taken after unwrapping: count=%d shown=%d", message.WordCount, utf8.RuneCountInString(message.Content))
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

// TestMessagesUnwrapsBeforeAnyBoundary proves the adapter unwraps the provider
// record even when the caller asked for a display bound.
//
// The bound is a presentation decision and is applied by the renderer, so the
// adapter must still hand over readable text. If the adapter cut the wrapper
// instead, the renderer would receive an unparsable fragment and would have to
// print it verbatim, which is exactly the unreadable output this guards against.
func TestMessagesUnwrapsBeforeAnyBoundary(t *testing.T) {
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
	if !strings.Contains(got, body) {
		t.Fatalf("content = %q, want the whole body kept for the renderer to bound", got)
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

// TestMessagesIgnoresTheTokenBound proves the adapter does not shorten a body for
// a token bound.
//
// A token bound exists to keep a rendered conversation readable, so it belongs to
// the renderer. Applying it here would cut a structured body into invalid JSON
// before the renderer could parse it, and the operator would see a fragment
// instead of the fields they asked to read.
func TestMessagesIgnoresTheTokenBound(t *testing.T) {
	body := strings.Repeat("word ", 400)
	document := `{"ok":true,"session_id":"s1","message_count":1,"messages":[{"role":"user","content":` + strconv.Quote(body) + `}]}`
	runner := &perCallRunner{answers: [][]byte{[]byte(`{"session_id":"s1"}`), []byte(document)}}
	adapter := messagesAdapter(t, runner)
	result, err := adapter.Messages(context.Background(), protocol.MessagesQuery{ProviderSessionID: "s1", MaxTokens: 10})
	if err != nil {
		t.Fatalf("Messages: %v", err)
	}
	if len(result.Messages) != 1 {
		t.Fatalf("messages = %d, want 1", len(result.Messages))
	}
	content := result.Messages[0].Content
	if content != body {
		t.Fatalf("the adapter shortened the body for a display bound: %d bytes, want %d", len(content), len(body))
	}
	if strings.HasSuffix(content, "...") {
		t.Fatalf("the adapter marked a display bound as a provider truncation: %q", content)
	}
	if result.Truncated {
		t.Fatalf("a display bound was reported as a provider truncation")
	}
}

// TestMessagesKeepsStructuredBodyParsableUnderABound proves a bounded request still
// yields a body the renderer can parse.
//
// This is the regression guard for the defect where a small bound turned a
// structured body into an unreadable fragment. The assertion is that the returned
// content is valid JSON, because that is the property the renderer depends on.
func TestMessagesKeepsStructuredBodyParsableUnderABound(t *testing.T) {
	for _, tc := range []struct {
		name  string
		body  string
		query protocol.MessagesQuery
	}{
		{"dict body with a token bound", `{"alpha":"first value","beta":{"nested":"inner value"}}`, protocol.MessagesQuery{ProviderSessionID: "s1", MaxTokens: 3}},
		{"dict body with a character bound", `{"alpha":"first value","beta":{"nested":"inner value"}}`, protocol.MessagesQuery{ProviderSessionID: "s1", MaxChars: 20}},
		{"list body with a token bound", `[{"name":"first item","state":"ready"},{"name":"second item","state":"waiting"}]`, protocol.MessagesQuery{ProviderSessionID: "s1", MaxTokens: 5}},
		{"list body with a character bound", `[{"name":"first item","state":"ready"},{"name":"second item","state":"waiting"}]`, protocol.MessagesQuery{ProviderSessionID: "s1", MaxChars: 20}},
	} {
		t.Run(tc.name, func(t *testing.T) {
			document := `{"ok":true,"session_id":"s1","message_count":1,"messages":[{"role":"user","content":` + strconv.Quote(tc.body) + `}]}`
			runner := &perCallRunner{answers: [][]byte{[]byte(`{"session_id":"s1"}`), []byte(document)}}
			adapter := messagesAdapter(t, runner)
			result, err := adapter.Messages(context.Background(), tc.query)
			if err != nil {
				t.Fatalf("Messages: %v", err)
			}
			content := result.Messages[0].Content
			if content != tc.body {
				t.Fatalf("the adapter changed a structured body: %q", content)
			}
			var parsed any
			if err := json.Unmarshal([]byte(content), &parsed); err != nil {
				t.Fatalf("the returned body is not parsable JSON, so the renderer cannot render it: %v", err)
			}
		})
	}
}

// TestMessagesKeepsUTF8UnderABound proves a bounded request never returns invalid
// UTF-8, because the adapter does not cut the body at all.
func TestMessagesKeepsUTF8UnderABound(t *testing.T) {
	body := strings.Repeat("中文内容", 200)
	document := `{"ok":true,"session_id":"s1","message_count":1,"messages":[{"role":"user","content":` + strconv.Quote(body) + `}]}`
	runner := &perCallRunner{answers: [][]byte{[]byte(`{"session_id":"s1"}`), []byte(document)}}
	adapter := messagesAdapter(t, runner)
	result, err := adapter.Messages(context.Background(), protocol.MessagesQuery{ProviderSessionID: "s1", MaxTokens: 7})
	if err != nil {
		t.Fatalf("Messages: %v", err)
	}
	content := result.Messages[0].Content
	if !utf8.ValidString(content) {
		t.Fatalf("a bounded request produced invalid UTF-8: %q", content)
	}
	if content != body {
		t.Fatalf("the adapter shortened a multi-byte body: %d bytes, want %d", len(content), len(body))
	}
}

// TestMessagesLeavesShortBodyAlone proves a body inside any bound is returned
// unchanged, so a bound cannot add noise to a short conversation.
func TestMessagesLeavesShortBodyAlone(t *testing.T) {
	document := `{"ok":true,"session_id":"s1","message_count":1,"messages":[{"role":"user","content":"short body"}]}`
	runner := &perCallRunner{answers: [][]byte{[]byte(`{"session_id":"s1"}`), []byte(document)}}
	adapter := messagesAdapter(t, runner)
	result, err := adapter.Messages(context.Background(), protocol.MessagesQuery{ProviderSessionID: "s1", MaxTokens: 5000})
	if err != nil {
		t.Fatalf("Messages: %v", err)
	}
	if got := result.Messages[0].Content; got != "short body" {
		t.Fatalf("content = %q, want the body unchanged", got)
	}
	if result.Truncated {
		t.Fatalf("a body inside the bound was labelled truncated")
	}
}

// TestMessagesZeroBoundMeansNoBound proves an explicit zero is accepted and leaves
// the body whole, so a caller can disable the display bound rather than only
// narrow it.
func TestMessagesZeroBoundMeansNoBound(t *testing.T) {
	body := strings.Repeat("word ", 400)
	document := `{"ok":true,"session_id":"s1","message_count":1,"messages":[{"role":"user","content":` + strconv.Quote(body) + `}]}`
	runner := &perCallRunner{answers: [][]byte{[]byte(`{"session_id":"s1"}`), []byte(document)}}
	adapter := messagesAdapter(t, runner)
	result, err := adapter.Messages(context.Background(), protocol.MessagesQuery{ProviderSessionID: "s1", MaxTokens: 0})
	if err != nil {
		t.Fatalf("Messages: %v", err)
	}
	if got := result.Messages[0].Content; got != body {
		t.Fatalf("a zero token bound shortened the body: %d bytes, want %d", len(got), len(body))
	}
}

// TestMessagesBoundsNeverChangeTheBody proves neither bound can alter the body, so
// the two bounds cannot disagree about the same message.
//
// The bounds compose in the renderer, where truncation never lengthens text, so
// applying the looser one first cannot hide the tighter one. The adapter's only
// obligation is to hand over the whole body for either bound to act on.
func TestMessagesBoundsNeverChangeTheBody(t *testing.T) {
	for _, tc := range []struct {
		name      string
		body      string
		maxChars  int
		maxTokens int
	}{
		{"character bound tighter", strings.Repeat("word ", 400), 20, 5000},
		{"token bound tighter", strings.Repeat("word ", 400), 100000, 10},
	} {
		t.Run(tc.name, func(t *testing.T) {
			document := `{"ok":true,"session_id":"s1","message_count":1,"messages":[{"role":"user","content":` + strconv.Quote(tc.body) + `}]}`
			runner := &perCallRunner{answers: [][]byte{[]byte(`{"session_id":"s1"}`), []byte(document)}}
			adapter := messagesAdapter(t, runner)
			result, err := adapter.Messages(context.Background(), protocol.MessagesQuery{ProviderSessionID: "s1", MaxChars: tc.maxChars, MaxTokens: tc.maxTokens})
			if err != nil {
				t.Fatalf("Messages: %v", err)
			}
			if got := result.Messages[0].Content; got != tc.body {
				t.Fatalf("a bound changed the body: %d bytes, want %d", len(got), len(tc.body))
			}
		})
	}
}
