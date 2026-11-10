package topsailai

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"strings"
	"sync"
	"time"
	"unicode/utf8"

	tiktoken "github.com/pkoukk/tiktoken-go"
	tiktokenloader "github.com/pkoukk/tiktoken-go-loader"

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
	// The caller's display bound is resolved once, before the loop, so every
	// message is shortened by the same rule.
	maxChars := clampMessagesMaxChars(query.MaxChars)
	total := 0
	for _, entry := range envelope.Messages {
		// The counts are measured from the body as the provider stored it, before
		// unwrapping and before any display bound. That is the order the provider's
		// own human-readable surface uses, and it is load-bearing: a count taken
		// after truncation would describe the shortened text, so the same message
		// would report a different size depending on how much of it was displayed.
		wordCount := utf8.RuneCountInString(entry.Content)
		tokenCount := countProviderTokens(entry.Content)
		// The provider wraps most bodies in its own step record, so the body is
		// unwrapped before it is bounded. The order matters: bounding first would
		// cut the wrapper into invalid JSON, and the unwrapper would then have to
		// give up on exactly the long messages an operator most wants to read.
		unwrapped := unwrapProviderContent(entry.Content)
		content := truncateMessageContent(unwrapped, maxChars)
		if content != unwrapped {
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

// clampMessagesMaxChars bounds the caller's per-message character request.
//
// A value above the accepted maximum is clamped rather than rejected, so a caller
// cannot request a bound the adapter would silently reduce. Zero means no
// truncation, which is the cluster's own convention: the provider treats a zero
// bound as an empty body, but a request that erases every message is not a useful
// operator intent, so the cluster reads zero as "show the whole body".
func clampMessagesMaxChars(value int) int {
	if value <= 0 {
		return 0
	}
	if value > protocol.MaxMessagesMaxChars {
		return protocol.MaxMessagesMaxChars
	}
	return value
}

// truncateMessageContent shortens one readable body to the caller's display bound.
//
// The cut is counted in code points and lands on a rune boundary, so a multi-byte
// character is never split. The provider's own human-readable surface appends an
// ellipsis to a shortened body, and the same marker is used here so the operator
// can see that text is missing rather than assuming the message ended there.
//
// A zero bound means no truncation. The provider treats a zero bound as an empty
// body, but that reading is not carried over: a request that erases every message
// is not a useful operator intent, and silently returning nothing would look like
// a session with no content.
func truncateMessageContent(content string, maxChars int) string {
	if maxChars <= 0 {
		return content
	}
	if utf8.RuneCountInString(content) <= maxChars {
		return content
	}
	count := 0
	for offset := range content {
		if count == maxChars {
			return content[:offset] + "..."
		}
		count++
	}
	return content
}

// providerTokenEncodingName is the encoding the provider's own counter uses.
//
// It is named here rather than derived from a model, because the provider counts
// with a fixed encoding and the cluster must reproduce that number, not the number
// a different model would produce.
const providerTokenEncodingName = "cl100k_base"

var (
	// providerTokenEncodingOnce builds the encoder at most once per process.
	//
	// Loading the encoding costs about 200ms, which is a fifth of the whole
	// messages budget. Building it per message would spend the budget on setup and
	// leave nothing for the read itself.
	providerTokenEncodingOnce sync.Once
	// providerTokenEncoding is nil when the encoding could not be loaded, so a
	// counting failure degrades to "no count claimed" instead of failing the read.
	providerTokenEncoding *tiktoken.Tiktoken
)

// countProviderTokens reports how many model tokens one body contains.
//
// The provider's own human-readable surface prints this number next to each
// message, so the cluster reproduces it rather than inventing a different measure.
// The counting rule is provider detail and therefore lives in the adapter: a
// second provider may count differently, and the renderer must never compute this
// for itself.
//
// The encoding is loaded from an embedded vocabulary, so counting works on a host
// with no network access. A load or encode failure returns zero, which the protocol
// documents as "no count claimed" rather than as a measured empty body: a display
// detail must never turn a readable conversation into a failed read.
func countProviderTokens(content string) int {
	if content == "" {
		return 0
	}
	providerTokenEncodingOnce.Do(func() {
		// The offline loader is installed before the encoding is requested, because
		// the default loader downloads the vocabulary at first use. A packaged node
		// may have no route to the internet, so a download would make the count
		// depend on network reachability.
		tiktoken.SetBpeLoader(tiktokenloader.NewOfflineLoader())
		encoding, err := tiktoken.GetEncoding(providerTokenEncodingName)
		if err != nil {
			return
		}
		providerTokenEncoding = encoding
	})
	if providerTokenEncoding == nil {
		return 0
	}
	// EncodeOrdinary is used rather than Encode because the provider calls
	// encoding.encode(text) with no special-token arguments, which treats every
	// special token as ordinary text. Encode would instead panic on a body that
	// happens to contain a token-looking string, and a conversation is untrusted
	// text that may contain anything.
	return len(providerTokenEncoding.EncodeOrdinary(content))
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
