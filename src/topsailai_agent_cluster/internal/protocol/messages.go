package protocol

// MessagesQuery bounds one provider conversation read.
//
// Messages are persisted provider data, not a live projection: a stopped session
// still has its messages, so this query needs no generation and no liveness check.
// ProviderSessionID is the provider's own session key, because a stopped session
// is absent from the inventory and therefore has no cluster resource ID.
//
// MaxChars bounds one message body. It is applied by the adapter after the body is
// unwrapped, never forwarded to the provider: the provider truncates the raw
// stored document, which cuts a structured body into invalid JSON and leaves the
// adapter unable to unwrap exactly the long messages an operator most wants to
// read. Zero means no truncation. It cannot bound the document, because one
// message may be arbitrarily long, so the adapter applies its own byte bounds too.
type MessagesQuery struct {
	ProviderSessionID string `json:"provider_session_id"`
	MaxChars          int    `json:"max_chars,omitempty"`
}

// Message is one provider-neutral conversation record.
//
// Role is the provider's own speaker word, kept verbatim as evidence. The cluster
// never interprets it, because a second provider may use a different vocabulary.
//
// WordCount and TokenCount are provider-derived measurements of Content as the
// provider reported it, before any display truncation. They are carried here
// rather than computed by the renderer because the counting rule belongs to the
// adapter: a second provider may count differently, and a renderer that counted
// for itself would silently impose this provider's rule on every other one. Both
// are zero when the adapter could not measure the body, which is distinct from a
// measured zero-length body only in that no count is claimed.
type Message struct {
	Role    string `json:"role,omitempty"`
	Content string `json:"content"`
	// CreatedAtMS is UTC epoch milliseconds. The provider reports local
	// wall-clock time without a zone, so the adapter converts using the
	// endpoint's local zone and leaves the value zero when it cannot.
	CreatedAtMS int64 `json:"created_at_ms,omitempty"`
	// WordCount is the number of characters in the untruncated body, counted in
	// code points so a multi-byte character counts once.
	WordCount int `json:"word_count,omitempty"`
	// TokenCount is the number of model tokens in the untruncated body.
	TokenCount int `json:"token_count,omitempty"`
}

// MessagesResult carries one bounded conversation read.
//
// MessageCount is the provider's own count, which may exceed len(Messages) when a
// bound was reached. It is reported separately so a bounded window is never
// presented as the complete conversation.
//
// Truncated reports that a bound was reached. It is always labelled, because a
// shortened answer must never be presented as complete.
type MessagesResult struct {
	ProviderSessionID string    `json:"provider_session_id"`
	Messages          []Message `json:"messages"`
	MessageCount      int       `json:"message_count"`
	ObservedAtMS      int64     `json:"observed_at_ms"`
	Truncated         bool      `json:"truncated,omitempty"`
	ErrorCode         string    `json:"error_code,omitempty"`
}

// Standard messages error codes.
const (
	// MessagesUnsupported means no configured adapter can read messages.
	MessagesUnsupported = "messages_unsupported"
	// MessagesSessionNotFound means the provider does not have this session. It
	// is distinct from an empty conversation, which is a successful answer.
	MessagesSessionNotFound = "session_not_found"
	// MessagesResponseTooLarge means the provider document exceeded a bound.
	MessagesResponseTooLarge = "messages_response_too_large"
	// MessagesProviderError means the provider call failed.
	MessagesProviderError = "provider_error"
)

// Bounds for one messages read. They are deliberately small: messages are an
// operator-facing window, not a bulk export.
const (
	// MaxMessages bounds the accepted message count.
	MaxMessages = 1000
	// There is deliberately no per-message byte bound. The provider document is
	// rejected above MaxMessagesBytes, so no single body can exceed that size, and a
	// second bound could only ever cut a body that had already been accepted. Such a
	// cut would be silent, so the operator would read a truncated message as a
	// complete one. The only bound applied to a body is the caller's display bound,
	// which is counted in characters and always appends an ellipsis.
	// MaxMessagesBytes bounds the accepted provider document size.
	MaxMessagesBytes = 512 << 10
	// MaxMessagesMaxChars bounds the caller's per-message character request. A
	// larger value is clamped rather than rejected, so a caller cannot ask for a
	// bound the provider would silently reduce.
	MaxMessagesMaxChars = 100000
)
