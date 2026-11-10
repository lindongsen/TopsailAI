package tui

import (
	"context"
	"fmt"
	"io"
	"strings"
	"time"

	"topsailai_agent_cluster/internal/protocol"
)

// MessagesQuerier reads one session's bounded conversation for one Endpoint.
//
// Messages are persisted provider data, so this seam answers for a session that is
// no longer running. It is still a live provider read: the result is returned
// verbatim and never cached, because a cached conversation would be presented as
// current evidence.
type MessagesQuerier interface {
	GetMessages(context.Context, string, string, int) (protocol.MessagesResult, error)
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
}

// MessagesView is one rendered conversation.
//
// MessageCount is the provider's own count, which may exceed len(Rows) when a
// bound was reached. It is reported separately so a bounded window is never
// presented as the complete conversation.
type MessagesView struct {
	EndpointID        string            `json:"endpoint_id"`
	ProviderSessionID string            `json:"provider_session_id"`
	Rows              []MessagesViewRow `json:"messages"`
	MessageCount      int               `json:"message_count"`
	ObservedAtMS      int64             `json:"observed_at_ms,omitempty"`
	Truncated         bool              `json:"truncated,omitempty"`
}

// BuildMessagesView converts one adapter result into a rendered conversation.
//
// Row numbers are assigned here rather than by the caller, so the numbering is a
// pure function of the result and cannot drift between the text and JSON forms.
// The numbering is presentation only: it is never a routing identity, because a
// conversation record has no addressable identity of its own.
func BuildMessagesView(endpointID string, result protocol.MessagesResult) MessagesView {
	view := MessagesView{
		EndpointID:        endpointID,
		ProviderSessionID: result.ProviderSessionID,
		Rows:              make([]MessagesViewRow, 0, len(result.Messages)),
		MessageCount:      result.MessageCount,
		ObservedAtMS:      result.ObservedAtMS,
		Truncated:         result.Truncated,
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

// messagesRuleWidth is the width of the separator rule.
//
// It is a fixed 80 rather than the terminal width, because the layout being
// reproduced is the provider's own human-readable conversation format, which uses
// a fixed rule. A rule that followed the terminal would make the same conversation
// look different on two terminals and would no longer match the provider's output.
const messagesRuleWidth = 80

// messagesRule is the separator drawn above and below every header.
var messagesRule = strings.Repeat("=", messagesRuleWidth)

// messagesEmptyBody is the placeholder printed for a record that carried no text.
//
// The two leading spaces are part of the provider's own format, so they are kept
// verbatim. An empty body is stated rather than left blank, so a record that
// carried no text is not mistaken for a rendering failure.
const messagesEmptyBody = "  [No content]"

// RenderMessages writes one bounded conversation.
//
// The layout reproduces the provider's own human-readable conversation format
// exactly, because that is the format an operator already reads when they run the
// provider directly. Each message is introduced by a blank line, a rule, a header
// and a second rule, so the boundary between two messages is visible even when
// both bodies are long and neither ends with a blank line.
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
// escape sequences. With colour disabled the output is byte-identical to the
// provider's own format.
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
	for _, row := range view.Rows {
		if err := writeMessagesBlock(out, row, color); err != nil {
			return err
		}
	}
	// The provider's format ends with a blank line after the last block, so the
	// next shell prompt does not sit against the final body.
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
func messagesTruncationLabel(view MessagesView) string {
	if view.MessageCount > len(view.Rows) {
		return fmt.Sprintf("conversation is a bounded window: %d of %d messages shown", len(view.Rows), view.MessageCount)
	}
	if view.Truncated {
		return "one or more message bodies were shortened to the requested bound"
	}
	return ""
}

// writeMessagesBlock writes one message in the provider's block layout.
//
// The leading blank line, the two rules and the trailing line break are all part
// of the reproduced format, so they are written here rather than by the caller.
func writeMessagesBlock(out io.Writer, row MessagesViewRow, color ColorPolicy) error {
	if _, err := io.WriteString(out, "\n"); err != nil {
		return err
	}
	if err := writeStyled(out, ansiDim, messagesRule+"\n", color); err != nil {
		return err
	}
	if err := writeMessagesHeader(out, row, color); err != nil {
		return err
	}
	if err := writeStyled(out, ansiDim, messagesRule+"\n", color); err != nil {
		return err
	}
	// A body that is still a JSON object or array is rendered as readable text
	// before it reaches the terminal. The cluster is the abstraction layer, so a
	// structured body is presented for a human instead of being forwarded as
	// braces and quotes. The rendering is generic and names no provider field,
	// because provider vocabulary belongs to the adapter.
	body := filterProviderOutput(renderStructuredBody(strings.TrimSpace(row.Content)), color)
	if body == "" {
		if err := writeStyled(out, ansiDim, messagesEmptyBody+"\n", color); err != nil {
			return err
		}
		return nil
	}
	if _, err := io.WriteString(out, body); err != nil {
		return err
	}
	// The body was trimmed, so it never ends with a line break; the break that
	// separates it from the next block is written here.
	_, err := io.WriteString(out, "\n")
	return err
}

// writeMessagesHeader writes one message header in the provider's own shape:
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
// The role is upper-cased because the provider's own format upper-cases it, and an
// operator comparing the two surfaces must see the same word. The role is provider
// data, so it is sanitized like any other untrusted value. An absent role is
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
// The layout matches the provider's own format, including milliseconds, so the two
// surfaces print the same timestamp for the same record. A conversation spans days,
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
func (r CommandRunner) Messages(ctx context.Context, out, errors io.Writer, target, sessionID string, maxChars int, jsonMode bool, color ColorPolicy) error {
	querier, ok := r.API.(MessagesQuerier)
	if !ok {
		return fmt.Errorf("messages is unavailable: this client cannot read provider conversations")
	}
	// The blank-target check runs before endpoint resolution, because the shared
	// resolver reports its own command name. Delegating first would tell the
	// operator to run "history" when they typed "messages".
	if strings.TrimSpace(target) == "" {
		return fmt.Errorf("usage: messages <endpoint-id-or-hostname> <session-id> [-c N|--max-chars N]")
	}
	if strings.TrimSpace(sessionID) == "" {
		return fmt.Errorf("usage: messages <endpoint-id-or-hostname> <session-id> [-c N|--max-chars N]")
	}
	endpoint, err := resolveHistoryEndpoint(ctx, r.API, target)
	if err != nil {
		return err
	}
	result, err := querier.GetMessages(ctx, endpoint.EndpointID, sessionID, maxChars)
	if err != nil {
		return err
	}
	if result.ErrorCode != "" {
		return fmt.Errorf("messages for session %q on endpoint %q failed: %s", sessionID, endpoint.EndpointID, result.ErrorCode)
	}
	view := BuildMessagesView(endpoint.EndpointID, result)
	if jsonMode {
		return RenderJSON(out, view)
	}
	return RenderMessages(out, view, color)
}
