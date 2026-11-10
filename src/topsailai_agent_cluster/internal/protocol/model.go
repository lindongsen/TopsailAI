package protocol

// ModelProfile is one selectable model configuration an Endpoint offers for a
// session.
//
// It is an Endpoint-scoped opaque resource, exactly like Session and HistoryRow:
// the cluster mints the identifier and the provider's own name, index and file
// path never appear on the wire. A profile is addressed by ModelProfileID and
// nothing else, so a second adapter can supply profiles without the Server, the
// schema or the CLI learning anything about how they are stored.
type ModelProfile struct {
	// ModelProfileID is the opaque cluster identifier the Endpoint minted for
	// this provider entry. It is never a provider name, a provider index or a
	// provider file path, and it is the only addressing key a caller may use.
	ModelProfileID string `json:"model_profile_id"`
	// DisplayName is a human-readable label for the operator. Descriptive only:
	// the cluster never parses it, and it is never an addressing key.
	DisplayName string `json:"display_name,omitempty"`
	// Current reports whether the session is using this profile now. It is an
	// observation, not a stored fact: the catalog read derives it, so no second
	// source of truth exists that could disagree with the provider.
	Current bool `json:"current,omitempty"`
	// Available reports whether the profile can be selected right now.
	Available bool `json:"available"`
	// UnavailableReason is a bounded standard reason code when Available is
	// false. It is provider-neutral; the adapter keeps its own detail local.
	UnavailableReason string `json:"unavailable_reason,omitempty"`
}

// ModelCatalogQuery bounds one model-catalog read for one session.
//
// The target is the standard CommandTarget, so a catalog read addresses a session
// exactly the way every other session-scoped operation does. A catalog read is
// read-only, so it does not require a generation: an unverified session can still
// be asked which profiles it offers, and only a selection needs a live target.
type ModelCatalogQuery struct {
	Target CommandTarget `json:"target"`
}

// ModelCatalog is one bounded read of the profiles a session can select.
//
// An empty Profiles list is a real answer meaning "this session offers no
// selectable profile". It is deliberately different from an Endpoint that cannot
// answer at all, which reports ModelCatalogUnsupported instead. Collapsing the
// two would make an unconfigured adapter look like a session with no options.
type ModelCatalog struct {
	Profiles []ModelProfile `json:"profiles"`
	// CurrentProfileID names the profile the session is using now. It is empty
	// when the provider reported no current profile, which is an observation and
	// not an error.
	CurrentProfileID string `json:"current_profile_id,omitempty"`
	// ObservedAtMS is when the Endpoint observed this catalog, in UTC epoch
	// milliseconds. A catalog is a live read, so it is never a stored projection.
	ObservedAtMS int64 `json:"observed_at_ms"`
	// Truncated reports that the provider returned its own capped window rather
	// than every profile that exists, so a bounded window is never presented as a
	// complete catalog.
	Truncated bool `json:"truncated,omitempty"`
	// ErrorCode is a bounded standard error code when the read could not answer.
	ErrorCode string `json:"error_code,omitempty"`
}

// ModelSelectRequest asks one session to switch to a profile.
//
// The payload carries the opaque profile identifier and nothing else. It never
// carries a provider name, a provider index or a provider credential, so the
// Server validates a standard shape and never forwards provider vocabulary.
type ModelSelectRequest struct {
	ModelProfileID string `json:"model_profile_id"`
}

// Standard model-catalog error codes. They are provider-neutral: an adapter maps
// its own vocabulary onto these values and keeps provider detail local.
const (
	// ModelCatalogUnsupported means no configured adapter can answer this query.
	// It is reported instead of an empty catalog, because an empty catalog would
	// read as "this session offers no profile", which is a different claim.
	ModelCatalogUnsupported = "model_catalog_unsupported"
	// ModelCatalogProviderError means the adapter's provider call failed.
	ModelCatalogProviderError = "provider_error"
	// ModelCatalogTooLarge means the provider document exceeded a bound.
	ModelCatalogTooLarge = "model_catalog_too_large"
)

// Standard model-selection error codes.
const (
	// ModelSelectUnknownProfile means the requested profile identifier is not one
	// this Endpoint minted. It is rejected before any provider call, so an
	// unknown identifier can never reach a provider as a guess.
	ModelSelectUnknownProfile = "unknown_model_profile"
	// ModelSelectUnavailable means the profile exists but cannot be selected now.
	ModelSelectUnavailable = "model_profile_unavailable"
)

// Standard model-profile unavailable reason codes.
const (
	// ModelProfileDisabled means the provider reports the entry as disabled.
	ModelProfileDisabled = "disabled"
	// ModelProfileUnsupportedProtocol means the provider cannot run this entry.
	ModelProfileUnsupportedProtocol = "unsupported_protocol"
)

// Bounds for one model catalog read. They are deliberately small: a catalog is an
// operator-facing menu, not a bulk export.
const (
	// MaxModelProfiles bounds the accepted profile count.
	MaxModelProfiles = 1000
	// MaxModelCatalogBytes bounds the accepted provider document size.
	MaxModelCatalogBytes = 256 << 10
	// MaxModelDisplayNameBytes bounds one display name.
	MaxModelDisplayNameBytes = 256
)
