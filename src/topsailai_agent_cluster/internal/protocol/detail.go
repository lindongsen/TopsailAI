package protocol

// SessionDetail carries one session's two provider documents.
//
// Both fields are opaque provider documents, not cluster-typed structures. The
// cluster deliberately does not model a provider's session record or its runtime
// observation: both are provider detail, they change when the provider changes,
// and a cluster type built from one provider's fields would have to change with
// it. The adapter forwards the provider's own documents and the surface renders
// them as readable text, so a second provider needs no protocol, Server, schema
// or CLI change.
//
// The names carry the provider_ prefix because the content is provider detail
// rather than a cluster-modelled fact. The prefix is the same one every other
// provider-owned value already uses, so a reader can tell at the field name which
// side of the seam a value came from.
//
// ProviderMetadata is the provider's session record. It is the whole record,
// because an operator asking for detail wants the facts the provider keeps, and a
// curated subset would silently hide the field that answers the question.
//
// ProviderRuntime is the provider's runtime observation. It is a seam: the
// cluster fixes the position and the bound, and the provider decides the content.
// A provider that has nothing to report leaves it empty, and the surface reports
// that it was not reported rather than inventing an observation.
//
// Both documents are optional, because a provider may legitimately report one and
// not the other. Requiring either would force a provider to emit a placeholder,
// and a placeholder is a claim nobody made.
//
// Both documents are bounded. A provider record can be large, and an unbounded
// document would let one session detail consume the channel budget that commands
// and heartbeats share. The bound is enforced as a hard rejection rather than a
// truncation: a shortened provider document presented as the whole record is
// worse than a refused read, because the operator cannot tell which fields are
// missing.
type SessionDetail struct {
	ProviderSessionID string `json:"provider_session_id"`
	ProviderMetadata  string `json:"provider_metadata,omitempty"`
	ProviderRuntime   string `json:"provider_runtime,omitempty"`
	ObservedAtMS      int64  `json:"observed_at_ms"`
	ErrorCode         string `json:"error_code,omitempty"`
}

// Standard detail error codes.
const (
	// DetailUnsupported means no configured adapter can read session detail.
	DetailUnsupported = "detail_unsupported"
	// DetailSessionNotFound means the provider does not have this session.
	DetailSessionNotFound = "session_not_found"
	// DetailResponseTooLarge means a provider document exceeded the configured
	// bound. It is a rejection, never a truncation, so the operator learns that
	// the record was refused instead of reading a partial record as complete.
	DetailResponseTooLarge = "detail_response_too_large"
	// DetailProviderError means the provider call failed.
	DetailProviderError = "provider_error"
)

// DefaultMaxDetailBytes bounds one accepted provider detail document unless the
// Endpoint configures a different bound.
//
// It is 1 MiB because a provider session record is a whole document rather than a
// summary, and the previous 512 KiB bound was reached by real records. The value
// is a default rather than a constant of the contract: an operator may raise or
// lower it per Endpoint, and the adapter enforces the configured value.
const DefaultMaxDetailBytes = 1 << 20

// MaxDetailCeilingBytes is the absolute ceiling any configured bound may reach.
//
// It exists because the document travels inside a provider response envelope, and
// JSON string escaping expands a document by up to six times when it contains
// control characters. A bound above this ceiling could therefore never be
// satisfied: the transport would reject the envelope before the document bound
// was ever consulted, and the operator would read a transport failure instead of
// the rejection this contract defines.
const MaxDetailCeilingBytes = 8 << 20

// SessionDetailQuery addresses one session whose provider record is wanted.
//
// The target is the provider's own session identifier for the same reason as
// SessionMetricsQuery: a session with no live process has no cluster resource ID,
// and detail is exactly the read an operator wants for such a session.
//
// The payload is closed. A caller cannot ask for selected fields, because the
// cluster does not model the provider's record and therefore cannot name a field to
// select. Asking for the whole record is the only request that stays honest when the
// provider adds or renames a field.
type SessionDetailQuery struct {
	ProviderSessionID string `json:"provider_session_id"`
}
