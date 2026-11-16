package protocol

// SessionDetail carries one session's provider metadata and runtime document.
//
// Both fields are opaque provider documents, not cluster-typed structures. The
// cluster deliberately does not model a provider's session record: the record is
// provider detail, it changes when the provider changes, and a cluster type built
// from one provider's fields would have to change with it. The adapter forwards
// the provider's own document and the surface renders it as readable text, so a
// second provider needs no protocol, Server, schema or CLI change.
//
// Metadata is the provider's session record. It is the whole record, because an
// operator asking for detail wants the facts the provider keeps, and a curated
// subset would silently hide the field that answers the question.
//
// Runtime is a seam. It is reserved for a runtime observation whose source is not
// yet decided, so it is empty today and the surface reports that it was not
// reported. It exists now so that filling it later requires no protocol, Server,
// schema or CLI change: a provider that starts reporting it needs only to emit the
// document, and every layer already carries it.
//
// Both documents are bounded. A provider record can be large, and an unbounded
// document would let one session detail consume the channel budget that commands
// and heartbeats share.
type SessionDetail struct {
	ProviderSessionID string `json:"provider_session_id"`
	Metadata          string `json:"metadata"`
	Runtime           string `json:"runtime,omitempty"`
	ObservedAtMS      int64  `json:"observed_at_ms"`
	MetadataTruncated bool   `json:"metadata_truncated,omitempty"`
	ErrorCode         string `json:"error_code,omitempty"`
}

// Standard detail error codes.
const (
	// DetailUnsupported means no configured adapter can read session detail.
	DetailUnsupported = "detail_unsupported"
	// DetailSessionNotFound means the provider does not have this session.
	DetailSessionNotFound = "session_not_found"
	// DetailResponseTooLarge means the provider document exceeded a bound.
	DetailResponseTooLarge = "detail_response_too_large"
	// DetailProviderError means the provider call failed.
	DetailProviderError = "provider_error"
)

// MaxDetailBytes bounds one accepted provider detail document. It matches the
// messages bound, because both carry a provider document of comparable size and
// both travel the same channel.
const MaxDetailBytes = 512 << 10
