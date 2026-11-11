package tui

import (
	"context"
	"fmt"
	"io"
	"strings"
	"time"

	"topsailai_agent_cluster/internal/protocol"
	"topsailai_agent_cluster/internal/tokenizer"
)

// MessagesQuerier reads one session's bounded conversation for one Endpoint.
//
// Messages are persisted provider data, so this seam answers for a session that is
// no longer running. It is still a live provider read: the result is returned
// verbatim and never cached, because a cached conversation would be presented as
// current evidence.
type MessagesQuerier interface {
	GetMessages(context.Context, string, string, int, int) (protocol.MessagesResult, error)
}

// MessagesViewRow is one rendered conversation record.
//
// Role is the provider's own speaker word, kept verbatim. The cluster never
// interprets it, because a second provider may use a different vocabulary.
//
// WordCount and TokenCount are measurements the adapter took from the body as the
// provider stored it, before any display bound. They are carried through rather
// than computed here, because the counting rule belongs to the adapter: a renderer
// that counted for itself would impose this provider's rule on every other one.
type MessagesViewRow struct {
	No          int    `json:"no"`
	Role        string `json:"role,omitempty"`
	Content     string `json:"content"`
	CreatedAtMS int64  `json:"created_at_ms,omitempty"`
	WordCount   int    `json:"word_count,omitempty"`
	TokenCount  int    `json:"token_count,omitempty"`
	// Shortened reports that a display bound removed text from this body.
	//
	// It is per row rather than per conversation because a bound can shorten one
	// long body while leaving every other body intact. A conversation-wide flag
	// would make the label claim that bodies were shortened when only one was, and
	// an operator reading the label would not know which row to look at.
	Shortened bool `json:"shortened,omitempty"`
}

// MessagesView is one rendered conversation.
//
// MessageCount is the provider's own count, which may exceed len(Rows) when a
// bound was reached. It is reported separately so a bounded window is never
// presented as the complete conversation.
//
// MaxChars and MaxTokens are the display bounds this view was built with. They
// live on the view rather than being applied by the caller because the bound is a
// presentation decision: it must act on the rendered text, not on the provider's
// stored body. Applying it earlier would cut a structured body into invalid JSON,
// and the renderer would then have no choice but to print the fragment verbatim.
type MessagesView struct {
	EndpointID        string            `json:"endpoint_id"`
	ProviderSessionID string            `json:"provider_session_id"`
	Rows              []MessagesViewRow `json:"messages"`
	MessageCount      int               `json:"message_count"`
	ObservedAtMS      int64             `json:"observed_at_ms,omitempty"`
	Truncated         bool              `json:"truncated,omitempty"`
	MaxChars          int               `json:"max_chars,omitempty"`
	MaxTokens         int               `json:"max_tokens,omitempty"`
}

// BuildMessagesView converts one adapter result into a rendered conversation.
//
// Row numbers are assigned here rather than by the caller, so the numbering is a
// pure function of the result and cannot drift between the text and JSON forms.
// The numbering is presentation only: it is never a routing identity, because a
// conversation record has no addressable identity of its own.
//
// The bounds are recorded on the view and applied later, by whichever surface
// renders it. They are deliberately not applied here: the text surface must bound
// the rendered text, while the JSON surface must bound the stored body. Applying
// one bound to the stored body would cut a structured body into invalid JSON, and
// the renderer would then have no choice but to print the fragment verbatim.
func BuildMessagesView(endpointID string, result protocol.MessagesResult, maxChars, maxTokens int) MessagesView {
	view := MessagesView{
		EndpointID:        endpointID,
		ProviderSessionID: result.ProviderSessionID,
		Rows:              make([]MessagesViewRow, 0, len(result.Messages)),
		MessageCount:      result.MessageCount,
		ObservedAtMS:      result.ObservedAtMS,
		Truncated:         result.Truncated,
		MaxChars:          maxChars,
		MaxTokens:         maxTokens,
	}
	for index, message := range result.Messages {
		view.Rows = append(view.Rows, MessagesViewRow{
			No:          index + 1,
			Role:        message.Role,
			Content:     message.Content,
			CreatedAtMS: message.CreatedAtMS,
			WordCount:   message.WordCount,
			TokenCount:  message.TokenCount,
		})
	}
	return view
}

// messagesBoundEllipsis marks text that a display bound removed.
//
// It is the same marker the shared tokenizer appends, so an operator sees one
// signal for "text is missing" regardless of which bound shortened the body.
const messagesBoundEllipsis = "..."

// boundMessagesBody shortens one already-rendered body to the display bounds.
//
// It runs on rendered text, never on the provider's stored body. That order is
// load-bearing: a structured body is only readable after rendering, so bounding it
// first would produce a JSON fragment that no longer parses and that the renderer
// would have to print verbatim.
//
// The character bound is applied first and the token bound second. Truncation only
// ever shortens text, so applying the looser bound first cannot hide the stricter
// one; applying only one of them would silently ignore the other.
//
// A zero bound means no bound, matching the cluster's own convention on every
// surface. The token bound is skipped when the shared encoder is unavailable,
// because a count that could not be measured must never erase readable text.
func boundMessagesBody(text string, maxChars, maxTokens int) (string, bool) {
	if text == "" {
		return text, false
	}
	shortened := false
	if maxChars > 0 {
		if runes := []rune(text); len(runes) > maxChars {
			text = string(runes[:maxChars]) + messagesBoundEllipsis
			shortened = true
		}
	}
	if maxTokens > 0 {
		// The marker this function may have just appended is removed before the
		// token bound runs, so a body shortened by both bounds ends with one
		// marker rather than two.
		candidate := strings.TrimSuffix(text, messagesBoundEllipsis)
		if bounded := tokenizer.Truncate(candidate, maxTokens); bounded != candidate {
			text = bounded
			shortened = true
		}
	}
	return text, shortened
}

// messagesRuleWidth is the width of the separator rule.
//
// It is a fixed 80 rather than the terminal width, so one block does not reflow when
// the window is resized and the header stays aligned with the rule above and below it.
// The layout is this cluster's own presentation, so the width is a presentation
// decision rather than a copy of any provider's output.
const messagesRuleWidth = 80

// messagesRule is the separator drawn above and below every header.
var messagesRule = strings.Repeat("=", messagesRuleWidth)

// messagesEmptyBody is the placeholder printed for a record that carried no text.
//
// The two leading spaces are this cluster's own indentation, so the placeholder
// lines up with the body text above it. An empty body is stated rather than left
// blank, so a record that carried no text is not mistaken for a rendering failure.
const messagesEmptyBody = "  [No content]"

// RenderMessages writes one bounded conversation.
//
// The layout is this cluster's own presentation, not a copy of any provider's
// human-readable format. Each message is introduced by a blank line, a rule, a
// header and a second rule, so the boundary between two messages is visible even
// when both bodies are long and neither ends with a blank line.
//
// Every body passes through the same provider output boundary the follow stream
// uses, so a control sequence in provider data can never reach the terminal as a
// trusted instruction. That holds with colour enabled as well: the boundary keeps
// only colour-only SGR sequences and still strips cursor movement, title changes
// and hyperlinks, so provider prose cannot reposition the cursor or rewrite a
// trusted row.
//
// Colour is applied only to structural labels, never to the body. The body is
// provider data, so colouring it would claim a meaning the cluster does not own,
// and it would also make the coloured and plain forms differ by more than the
// escape sequences. With colour disabled the output carries no escape sequence at
// all, so a redirected stream stays plain text.
//
// Truncation is always labelled, and the label states which bound was reached. A
// shortened conversation must never be presented as complete, because the operator
// would otherwise conclude that the session ended where the bound was reached.
//
// The two bounds are reported separately because they mean different things. A
// bounded window means messages are missing, so the operator knows to narrow the
// request or read further. A shortened body means every message is present but one
// of them is cut, so the operator knows the conversation is complete and only the
// text is not. Reporting the window label for a shortened body would claim messages
// were omitted when none were, which is the same class of error as presenting a
// shortened body as complete.
//
// The distinction is derived from the result rather than carried as a second flag:
// a message count above the rendered row count is exactly the case where messages
// were omitted, so one fact keeps one source of truth and no protocol change is
// needed.
func RenderMessages(out io.Writer, view MessagesView, color ColorPolicy) error {
	if len(view.Rows) == 0 {
		if _, err := fmt.Fprintln(out, "no messages recorded for this session"); err != nil {
			return err
		}
		return nil
	}
	for index := range view.Rows {
		shortened, err := writeMessagesBlock(out, view.Rows[index], view.MaxChars, view.MaxTokens, color)
		if err != nil {
			return err
		}
		// The per-row outcome is recorded on the view so the label below reports
		// what actually happened rather than what was requested. A bound that was
		// requested but never reached must not produce a label claiming text was
		// removed.
		view.Rows[index].Shortened = shortened
	}
	// The block layout ends with a blank line after the last block, so the next
	// shell prompt does not sit against the final body.
	if _, err := io.WriteString(out, "\n"); err != nil {
		return err
	}
	if label := messagesTruncationLabel(view); label != "" {
		if err := writeStyled(out, ansiDim, label+"\n", color); err != nil {
			return err
		}
	}
	return nil
}

// messagesTruncationLabel states which bound was reached, or returns empty when
// none was.
//
// The window case is judged first, because a report that omitted messages may also
// have shortened the ones it kept, and the missing messages are the more important
// fact: an operator who reads only "a body was shortened" would not know to ask for
// the rest of the conversation.
//
// The body case is derived from the per-row outcome, not from the result's own
// Truncated flag. That flag now means only "the provider reported more messages
// than were returned, or the transport byte guard stopped the read", so reading it
// here would print the body label for a transport guard trip and claim that bodies
// were shortened when none were.
func messagesTruncationLabel(view MessagesView) string {
	if view.MessageCount > len(view.Rows) {
		return fmt.Sprintf("conversation is a bounded window: %d of %d messages shown", len(view.Rows), view.MessageCount)
	}
	for _, row := range view.Rows {
		if row.Shortened {
			return "one or more message bodies were shortened to the requested bound"
		}
	}
	return ""
}

// writeMessagesBlock writes one message in the provider's block layout.
//
// The leading blank line, the two rules and the trailing line break are all part
// of this cluster's block layout, so they are written here rather than by the
// caller.
//
// It reports whether a display bound removed text from this body, so the caller can
// label the conversation from what actually happened instead of from what was
// requested.
func writeMessagesBlock(out io.Writer, row MessagesViewRow, maxChars, maxTokens int, color ColorPolicy) (bool, error) {
	if _, err := io.WriteString(out, "\n"); err != nil {
		return false, err
	}
	if err := writeStyled(out, ansiDim, messagesRule+"\n", color); err != nil {
		return false, err
	}
	if err := writeMessagesHeader(out, row, color); err != nil {
		return false, err
	}
	if err := writeStyled(out, ansiDim, messagesRule+"\n", color); err != nil {
		return false, err
	}
	// A body that is still a JSON object or array is rendered as readable text
	// before it reaches the terminal. The cluster is the abstraction layer, so a
	// structured body is presented for a human instead of being forwarded as
	// braces and quotes. The rendering is generic and names no provider field,
	// because provider vocabulary belongs to the adapter.
	//
	// The display bound is applied after rendering and before sanitizing. Bounding
	// the stored body first would cut a structured body into invalid JSON, and the
	// renderer would then have no choice but to print the fragment verbatim, which
	// is exactly the unreadable output this order exists to prevent. Sanitizing
	// last is safe because it only removes bytes, so the displayed text can never
	// grow past the bound.
	rendered, shortened := boundMessagesBody(renderStructuredBody(strings.TrimSpace(row.Content)), maxChars, maxTokens)
	body := filterProviderOutput(rendered, color)
	if body == "" {
		if err := writeStyled(out, ansiDim, messagesEmptyBody+"\n", color); err != nil {
			return false, err
		}
		return false, nil
	}
	if _, err := io.WriteString(out, body); err != nil {
		return false, err
	}
	// The body was trimmed, so it never ends with a line break; the break that
	// separates it from the next block is written here.
	if _, err := io.WriteString(out, "\n"); err != nil {
		return false, err
	}
	return shortened, nil
}

// writeMessagesHeader writes one message header in this cluster's own shape:
//
//	#1 - Role: USER - Words: 99535 - Tokens: 20004 - 2026-11-09 02:12:30.285
//
// The number and the role are structural labels, so they carry bold cyan. The
// counts and the time are supporting detail, so they are dim. Every interpolated
// value is sanitized first, because the role is provider data while this line
// carries trusted styling.
func writeMessagesHeader(out io.Writer, row MessagesViewRow, color ColorPolicy) error {
	if err := writeStyled(out, ansiBoldCyan, fmt.Sprintf("#%d", row.No), color); err != nil {
		return err
	}
	if _, err := io.WriteString(out, " - "); err != nil {
		return err
	}
	if err := writeStyled(out, ansiBoldCyan, "Role: "+messagesRoleCell(row.Role), color); err != nil {
		return err
	}
	counts := fmt.Sprintf(" - Words: %d - Tokens: %d", row.WordCount, row.TokenCount)
	if err := writeStyled(out, ansiDim, counts, color); err != nil {
		return err
	}
	if row.CreatedAtMS > 0 {
		if err := writeStyled(out, ansiDim, " - "+formatMessagesTime(row.CreatedAtMS), color); err != nil {
			return err
		}
	}
	_, err := io.WriteString(out, "\n")
	return err
}

// messagesRoleCell renders the provider's speaker word as one safe inline token.
//
// The role is upper-cased because a speaker word is a label rather than prose, and
// an upper-case label reads as structure instead of as part of the body. The role
// is provider data, so it is sanitized like any other untrusted value. An absent
// role is
// rendered as a dash rather than an empty label, so a record whose speaker was not
// reported is visibly unknown instead of looking like a formatting gap.
func messagesRoleCell(role string) string {
	clean := strings.TrimSpace(sanitizeInlineText(role))
	if clean == "" {
		return "-"
	}
	return strings.ToUpper(clean)
}

// formatMessagesTime renders one UTC epoch millisecond value in local time.
//
// The layout includes milliseconds, because two records can be written inside the
// same second and a coarser format would make them look simultaneous. A
// conversation spans days,
// so the date is printed as well as the clock: a bare clock time would make two
// records from different days look adjacent.
func formatMessagesTime(value int64) string {
	return time.UnixMilli(value).In(time.Local).Format("2006-01-02 15:04:05.000")
}

// Messages renders one session's bounded conversation.
//
// The endpoint argument is mandatory on the standalone surface, because a
// conversation read is endpoint-scoped: fanning out across endpoints would
// multiply provider calls and would mix sessions whose provider IDs may collide.
//
// The session argument is the provider's own session key, not a cluster resource
// ID. A stopped session is absent from the inventory and therefore has no resource
// ID, so the provider key is the only address that exists for it. This is why the
// read needs no generation and no liveness check.
func (r CommandRunner) Messages(ctx context.Context, out, errors io.Writer, target, sessionID string, maxChars, maxTokens int, jsonMode bool, color ColorPolicy) error {
	querier, ok := r.API.(MessagesQuerier)
	if !ok {
		return fmt.Errorf("messages is unavailable: this client cannot read provider conversations")
	}
	// The blank-target check runs before endpoint resolution, because the shared
	// resolver reports its own command name. Delegating first would tell the
	// operator to run "history" when they typed "messages".
	if strings.TrimSpace(target) == "" {
		return fmt.Errorf("usage: messages <endpoint-id-or-hostname> <session-id> [-c N|--max-chars N] [-t N|--max-tokens N]")
	}
	if strings.TrimSpace(sessionID) == "" {
		return fmt.Errorf("usage: messages <endpoint-id-or-hostname> <session-id> [-c N|--max-chars N] [-t N|--max-tokens N]")
	}
	endpoint, err := resolveHistoryEndpoint(ctx, r.API, target)
	if err != nil {
		return err
	}
	result, err := querier.GetMessages(ctx, endpoint.EndpointID, sessionID, maxChars, maxTokens)
	if err != nil {
		return err
	}
	if result.ErrorCode != "" {
		return fmt.Errorf("messages for session %s on endpoint %q failed: %s", sessionIdentityLabel("", sessionID, ""), endpoint.EndpointID, result.ErrorCode)
	}
	view := BuildMessagesView(endpoint.EndpointID, result, maxChars, maxTokens)
	if jsonMode {
		// The JSON surface carries the stored body rather than a rendering of it, so
		// the bound is applied to the body itself. A JSON consumer parses the
		// envelope and reads the content field as data; it never renders the body,
		// so there is no rendered text to bound and no readability to preserve.
		return RenderJSON(out, boundMessagesViewContent(view))
	}
	return RenderMessages(out, view, color)
}

// boundMessagesViewContent applies the display bounds to the stored bodies of a
// view, for the JSON surface.
//
// It exists because the two surfaces bound different things. The text surface
// bounds rendered text, so a structured body stays readable. The JSON surface
// carries the stored body, so bounding it is the only way to honour the same
// request. Sharing one code path would force one surface to bound the wrong thing.
func boundMessagesViewContent(view MessagesView) MessagesView {
	if view.MaxChars <= 0 && view.MaxTokens <= 0 {
		return view
	}
	for index := range view.Rows {
		bounded, shortened := boundMessagesBody(view.Rows[index].Content, view.MaxChars, view.MaxTokens)
		view.Rows[index].Content = bounded
		view.Rows[index].Shortened = shortened
	}
	return view
}
