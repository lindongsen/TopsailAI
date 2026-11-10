package topsailai

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"strings"
	"time"
	"unicode/utf8"

	"topsailai_agent_cluster/internal/protocol"
	"topsailai_agent_cluster/internal/tokenizer"
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
	// --max-chars is deliberately never passed to the provider. The provider
	// truncates the raw stored document, which cuts a structured body into
	// invalid JSON; the adapter would then be unable to unwrap exactly the long
	// messages an operator most wants to read. The bound is applied below, after
	// unwrapping, so it shortens readable text instead of corrupting the record.
	args := []string{"session", "history", sessionID, "--json"}
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
	// The caller's display bounds are deliberately not applied here. A bound is a
	// presentation decision, so it belongs to the renderer that presents the body:
	// cutting the stored text here would cut a structured body into invalid JSON,
	// and the renderer would then have to print the fragment verbatim because it
	// could no longer parse it. The adapter therefore returns every body whole and
	// reports only what the provider itself reported.
	total := 0
	for _, entry := range envelope.Messages {
		// The counts are measured from the body as the provider stored it. That is
		// the order the provider's own human-readable surface uses, and it is
		// load-bearing: a count taken after a display bound would describe the
		// shortened text, so the same message would report a different size
		// depending on how much of it was displayed.
		wordCount := utf8.RuneCountInString(entry.Content)
		tokenCount := tokenizer.Count(entry.Content)
		// The provider wraps most bodies in its own step record, so the body is
		// unwrapped before it is returned. The record format is provider detail, so
		// unwrapping belongs here rather than in the renderer.
		content := unwrapProviderContent(entry.Content)
		// The byte guard is a transport bound, not a display bound: it keeps one
		// oversized conversation from exhausting the channel. Breaking here leaves
		// fewer messages than the provider counted, so the renderer reports a
		// bounded window rather than a shortened body, which is the true fact.
		total += len(content)
		if total > protocol.MaxMessagesBytes {
			break
		}
		result.Messages = append(result.Messages, protocol.Message{
			Role:        entry.Role,
			Content:     content,
			CreatedAtMS: messagesTimeMS(entry.CreateTime),
			WordCount:   wordCount,
			TokenCount:  tokenCount,
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

// Provider step-record field names. These are provider vocabulary, so they are
// confined to this adapter and never appear in the protocol, the Server or the CLI.
const (
	providerStepField    = "step_name"
	providerRawTextField = "raw_text"
	providerFormatPrefix = "topsailai."
)

// unwrapProviderContent converts one provider message body into the readable form
// the provider's own human-facing surface prints.
//
// The provider stores most bodies as its own step record, either one object or an
// array of them, each carrying a step name and the text the operator actually
// wrote. Printing that record verbatim shows JSON to the operator, which is why the
// cluster unwraps it here rather than in the renderer: the record format is
// provider detail, so it belongs to the adapter and must never reach the protocol,
// the Server, a stored document or a CLI help body.
//
// The unwrapping is deliberately forgiving. A body that is not a step record, or
// that no longer parses because the provider truncated it, is returned unchanged.
// Losing the operator's text would be worse than showing it in its raw form, and a
// truncated body is exactly the case where the surviving text still matters.
func unwrapProviderContent(content string) string {
	// The provider applies the same cheap prefilter before parsing, so a plain
	// prose body never pays for a decode attempt.
	if !strings.Contains(content, providerStepField) {
		return content
	}
	var decoded any
	if err := json.Unmarshal([]byte(content), &decoded); err != nil {
		return content
	}
	entries, ok := providerStepEntries(decoded)
	if !ok {
		return content
	}
	var builder strings.Builder
	for _, entry := range entries {
		builder.WriteString(providerFormatPrefix)
		builder.WriteString(fmt.Sprint(entry[providerStepField]))
		builder.WriteString("\n")
		delete(entry, providerStepField)
		if value, present := entry[providerRawTextField]; present {
			builder.WriteString(providerJSONDump(value))
			builder.WriteString("\n")
			delete(entry, providerRawTextField)
		}
		// Any field the cluster does not model is preserved rather than dropped,
		// because a step record can carry evidence the operator still needs.
		if len(entry) > 0 {
			builder.WriteString(providerJSONDump(entry))
			builder.WriteString("\n")
		}
		builder.WriteString("\n")
	}
	return strings.TrimSpace(builder.String())
}

// providerStepEntries normalizes a decoded body into step records.
//
// The provider accepts both a single record and an array of them, and it refuses
// the whole body when any element is not a record carrying a step name. The same
// all-or-nothing rule is kept here, so a mixed body is shown verbatim instead of
// being half-unwrapped into something that reads like a complete conversation.
func providerStepEntries(decoded any) ([]map[string]any, bool) {
	candidates, isList := decoded.([]any)
	if !isList {
		candidates = []any{decoded}
	}
	entries := make([]map[string]any, 0, len(candidates))
	for _, candidate := range candidates {
		entry, isRecord := candidate.(map[string]any)
		if !isRecord {
			return nil, false
		}
		if _, present := entry[providerStepField]; !present {
			return nil, false
		}
		entries = append(entries, entry)
	}
	return entries, true
}

// providerJSONDump renders one decoded value the way the provider's own formatter
// does: a string is returned unchanged, and anything else is indented JSON with
// its keys sorted and its non-ASCII text left readable.
func providerJSONDump(value any) string {
	if text, isText := value.(string); isText {
		return text
	}
	var buffer bytes.Buffer
	encoder := json.NewEncoder(&buffer)
	encoder.SetEscapeHTML(false)
	encoder.SetIndent("", "  ")
	if err := encoder.Encode(value); err != nil {
		return fmt.Sprint(value)
	}
	return strings.TrimRight(buffer.String(), "\n")
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
