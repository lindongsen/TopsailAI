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
type MessagesViewRow struct {
	No          int    `json:"no"`
	Role        string `json:"role,omitempty"`
	Content     string `json:"content"`
	CreatedAtMS int64  `json:"created_at_ms,omitempty"`
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
		})
	}
	return view
}

// RenderMessages writes one bounded conversation.
//
// A conversation is multi-line prose, so it is rendered as labelled blocks rather
// than as a table: flattening a message into one cell would destroy its structure
// and make a long answer unreadable. Every body passes through the same provider
// output boundary the follow stream uses, so a control sequence in provider data
// can never reach the terminal as a trusted instruction.
//
// Truncation is always labelled. A shortened conversation must never be presented
// as complete, because the operator would otherwise conclude that the session
// ended where the bound was reached.
func RenderMessages(out io.Writer, view MessagesView, color ColorPolicy) error {
	if len(view.Rows) == 0 {
		if _, err := fmt.Fprintln(out, "no messages recorded for this session"); err != nil {
			return err
		}
		return nil
	}
	for _, row := range view.Rows {
		header := fmt.Sprintf("[%d] %s", row.No, messagesRoleCell(row.Role))
		if row.CreatedAtMS > 0 {
			header += "  " + formatMessagesTime(row.CreatedAtMS)
		}
		if _, err := fmt.Fprintln(out, header); err != nil {
			return err
		}
		body := filterProviderOutput(row.Content, color)
		if _, err := fmt.Fprint(out, body); err != nil {
			return err
		}
		if !strings.HasSuffix(body, "\n") {
			if _, err := fmt.Fprintln(out); err != nil {
				return err
			}
		}
		if _, err := fmt.Fprintln(out); err != nil {
			return err
		}
	}
	if view.Truncated {
		if _, err := fmt.Fprintf(out, "conversation is a bounded window: %d of %d messages shown\n", len(view.Rows), view.MessageCount); err != nil {
			return err
		}
	}
	return nil
}

// messagesRoleCell renders the provider's speaker word as one safe inline token.
//
// The role is provider data, so it is sanitized like any other untrusted value. An
// absent role is rendered as a dash rather than an empty label, so a record whose
// speaker was not reported is visibly unknown instead of looking like a formatting
// gap.
func messagesRoleCell(role string) string {
	clean := strings.TrimSpace(sanitizeInlineText(role))
	if clean == "" {
		return "-"
	}
	return clean
}

// formatMessagesTime renders one UTC epoch millisecond value in local time.
//
// A conversation spans days, so the date is printed as well as the clock: a bare
// clock time would make two records from different days look adjacent.
func formatMessagesTime(value int64) string {
	return time.UnixMilli(value).In(time.Local).Format("2006-01-02 15:04:05")
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
		return fmt.Errorf("usage: messages <endpoint-id-or-hostname> <session-id>")
	}
	if strings.TrimSpace(sessionID) == "" {
		return fmt.Errorf("usage: messages <endpoint-id-or-hostname> <session-id>")
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
		return fmt.Errorf("messages for session %s on endpoint %q failed: %s", sessionIdentityLabel("", sessionID, ""), endpoint.EndpointID, result.ErrorCode)
	}
	view := BuildMessagesView(endpoint.EndpointID, result)
	if jsonMode {
		return RenderJSON(out, view)
	}
	return RenderMessages(out, view, color)
}
