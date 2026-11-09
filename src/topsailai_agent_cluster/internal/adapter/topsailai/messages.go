package topsailai

import (
	"context"
	"encoding/json"
	"fmt"
	"strings"
	"time"
	"unicode/utf8"

	"topsailai_agent_cluster/internal/protocol"
)

// messagesEntry mirrors one record of the provider's `session history --json`
// document. The provider reports three fields per message; only these are used.
type messagesEntry struct {
	Role       string `json:"role"`
	Content    string `json:"content"`
	CreateTime string `json:"create_time"`
}

// messagesEnvelope mirrors the provider's `session history --json` envelope.
type messagesEnvelope struct {
	OK           bool            `json:"ok"`
	ErrorCode    string          `json:"error_code"`
	Message      string          `json:"message"`
	SessionID    string          `json:"session_id"`
	MessageCount int             `json:"message_count"`
	Messages     []messagesEntry `json:"messages"`
}

// sessionInfoEnvelope mirrors only the failure fields of `session info --json`.
//
// The success document carries many fields the cluster does not need, so only the
// error code is decoded. Its presence is the whole point: `session history`
// returns a successful empty document for a session that does not exist, so the
// two cases are otherwise indistinguishable.
type sessionInfoEnvelope struct {
	ErrorCode string `json:"error_code"`
}

// Messages reads one session's conversation without mutation.
//
// The provider stores messages independently of the process, so this read works
// for a session that stopped long ago. That is the reason the command exists:
// every other read surface requires a live target.
//
// The existence pre-check runs first, because the provider reports a missing
// session as a successful empty history. Without the check an operator would read
// "no messages" for a session that was never recorded, which is a different and
// misleading claim.
func (a *Adapter) Messages(ctx context.Context, query protocol.MessagesQuery) (protocol.MessagesResult, error) {
	sessionID := strings.TrimSpace(query.ProviderSessionID)
	if sessionID == "" {
		return protocol.MessagesResult{ErrorCode: protocol.MessagesProviderError}, fmt.Errorf("provider session ID is required")
	}
	// --db-conn is deliberately never passed: it lets the caller choose the
	// database, so forwarding it would let a remote payload select which store is
	// read. The provider's own configured database is the only one reachable here.
	if code, err := a.requireSession(ctx, sessionID); err != nil {
		return protocol.MessagesResult{ProviderSessionID: sessionID, ErrorCode: code}, err
	}
	args := []string{"session", "history", sessionID, "--json"}
	if maxChars := clampMessagesMaxChars(query.MaxChars); maxChars > 0 {
		args = append(args, "--max-chars", fmt.Sprint(maxChars))
	}
	output, err := a.run(ctx, args, nil)
	if err != nil {
		return protocol.MessagesResult{ProviderSessionID: sessionID, ErrorCode: protocol.MessagesProviderError}, err
	}
	if len(output) > protocol.MaxMessagesBytes {
		return protocol.MessagesResult{ProviderSessionID: sessionID, ErrorCode: protocol.MessagesResponseTooLarge}, fmt.Errorf("messages response exceeds byte limit")
	}
	var envelope messagesEnvelope
	if err := json.Unmarshal(output, &envelope); err != nil {
		return protocol.MessagesResult{ProviderSessionID: sessionID, ErrorCode: protocol.MessagesProviderError}, fmt.Errorf("decode session history: %w", err)
	}
	if !envelope.OK || envelope.ErrorCode != "" {
		return protocol.MessagesResult{ProviderSessionID: sessionID, ErrorCode: protocol.MessagesProviderError}, fmt.Errorf("session history failed (ok=%t, error_code=%q)", envelope.OK, envelope.ErrorCode)
	}
	if len(envelope.Messages) > protocol.MaxMessages {
		return protocol.MessagesResult{ProviderSessionID: sessionID, ErrorCode: protocol.MessagesResponseTooLarge}, fmt.Errorf("messages count exceeds limit")
	}
	nowMS := time.Now().UnixMilli()
	result := protocol.MessagesResult{
		ProviderSessionID: sessionID,
		Messages:          make([]protocol.Message, 0, len(envelope.Messages)),
		MessageCount:      envelope.MessageCount,
		ObservedAtMS:      nowMS,
	}
	// The provider's own count is judged before any bound is applied, because a
	// narrowed view must not be mistaken for a complete conversation.
	if envelope.MessageCount > len(envelope.Messages) {
		result.Truncated = true
	}
	total := 0
	for _, entry := range envelope.Messages {
		content, cut := boundedMessageContent(entry.Content)
		if cut {
			result.Truncated = true
		}
		total += len(content)
		if total > protocol.MaxMessagesBytes {
			result.Truncated = true
			break
		}
		result.Messages = append(result.Messages, protocol.Message{
			Role:        entry.Role,
			Content:     content,
			CreatedAtMS: messagesTimeMS(entry.CreateTime),
		})
	}
	return result, nil
}

// requireSession proves the provider has this session before its history is read.
//
// A provider storage failure is reported as a provider error rather than as a
// missing session, because telling the operator the session was deleted would stop
// them looking for data that still exists.
func (a *Adapter) requireSession(ctx context.Context, sessionID string) (string, error) {
	output, err := a.run(ctx, []string{"session", "info", sessionID, "--json"}, nil)
	// A non-zero exit still carries the structured failure document on stdout, so
	// the document is decoded before the error is judged.
	var envelope sessionInfoEnvelope
	if len(output) > 0 {
		if decodeErr := json.Unmarshal(output, &envelope); decodeErr != nil {
			if err != nil {
				return protocol.MessagesProviderError, fmt.Errorf("session info for %q failed: %w", sessionID, err)
			}
			return protocol.MessagesProviderError, fmt.Errorf("decode session info for %q: %w", sessionID, decodeErr)
		}
	}
	switch envelope.ErrorCode {
	case "":
		if err != nil {
			return protocol.MessagesProviderError, fmt.Errorf("session info for %q failed: %w", sessionID, err)
		}
		return "", nil
	case protocol.MessagesSessionNotFound:
		return protocol.MessagesSessionNotFound, fmt.Errorf("session %q was not found", sessionID)
	default:
		// The provider distinguishes a storage fault from a missing session, and the
		// distinction is preserved here: reporting a fault as a deletion would stop
		// the operator looking for data that still exists.
		return protocol.MessagesProviderError, fmt.Errorf("session info for %q failed: %s", sessionID, envelope.ErrorCode)
	}
}

// clampMessagesMaxChars bounds the caller's per-message character request.
//
// A value above the accepted maximum is clamped rather than rejected, so a caller
// cannot request a bound the provider would silently reduce. Zero keeps the
// provider's own default.
func clampMessagesMaxChars(value int) int {
	if value <= 0 {
		return 0
	}
	if value > protocol.MaxMessagesMaxChars {
		return protocol.MaxMessagesMaxChars
	}
	return value
}

// boundedMessageContent keeps one message body inside the accepted bound.
//
// The cut lands on a UTF-8 boundary, because a raw byte slice would split a
// multi-byte character and produce invalid text. The caller is told that a cut
// happened, so a shortened message is never presented as complete.
func boundedMessageContent(content string) (string, bool) {
	if !utf8.ValidString(content) {
		return "", true
	}
	if len(content) <= protocol.MaxMessageContentBytes {
		return content, false
	}
	cut := protocol.MaxMessageContentBytes
	for cut > 0 && !utf8.RuneStart(content[cut]) {
		cut--
	}
	return content[:cut], true
}

// messagesTimeMS converts one provider timestamp to UTC epoch milliseconds.
//
// The provider emits local wall-clock time without a zone, because it formats a
// stored timestamp. The value is therefore interpreted in the endpoint's local
// zone, which is the zone the provider ran in. An unparsable value yields zero
// rather than a fabricated instant, so a missing time is never presented as a real
// observation.
func messagesTimeMS(raw string) int64 {
	raw = strings.TrimSpace(raw)
	if raw == "" {
		return 0
	}
	for _, layout := range []string{"2006-01-02 15:04:05.000", "2006-01-02 15:04:05", "2006-01-02T15:04:05"} {
		if parsed, err := time.ParseInLocation(layout, raw, time.Local); err == nil {
			return parsed.UnixMilli()
		}
	}
	if parsed, err := time.Parse(time.RFC3339, raw); err == nil {
		return parsed.UnixMilli()
	}
	return 0
}
