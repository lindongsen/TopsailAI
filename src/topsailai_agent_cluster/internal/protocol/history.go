package protocol

// HistoryQuery bounds one provider session-history read.
//
// History is a live provider query, not a persisted projection: nothing in this
// document is stored by the Server. Limit narrows the caller's view only; it can
// never raise the provider's own cap, which is an intentional product decision.
type HistoryQuery struct {
	Limit int `json:"limit,omitempty"`
}

// HistoryRow is one provider-neutral record of a past session.
//
// A history row is deliberately NOT a routable resource. It carries an opaque
// cluster handle so a resume request can address it, but it never carries a
// provider generation, because a past session is not running and therefore has
// no generation to validate. Routing still requires resource_id + generation,
// and only the inventory join can supply that pair.
type HistoryRow struct {
	// ProviderSessionID is the provider's own session key. It is not a cluster
	// resource ID, and it may be duplicated across endpoints, so it is only ever
	// resolved within one endpoint.
	ProviderSessionID string `json:"provider_session_id"`
	// ResourceID is the opaque cluster handle the Endpoint minted for this
	// provider session. It lets a resume request address the row without naming
	// a provider key or an adapter, so the Server still sees only an opaque ID.
	// It is never a routing identity on its own: routing needs a generation too.
	ResourceID string `json:"resource_id,omitempty"`
	// ProviderDisplayName is the provider session name, descriptive only.
	ProviderDisplayName string `json:"provider_display_name,omitempty"`
	// ProviderProjectWorkspace is the workspace the session worked on, descriptive only.
	ProviderProjectWorkspace string `json:"provider_project_workspace,omitempty"`
	// Task is the provider's recorded task text, descriptive only.
	Task string `json:"task,omitempty"`
	// ProviderStatus is the provider's own status word, kept verbatim as evidence.
	// The cluster never interprets it; the adapter owns that mapping.
	ProviderStatus string `json:"provider_status,omitempty"`
	// CreatedAtMS and ModifiedAtMS are UTC epoch milliseconds. The provider reports
	// local wall-clock time without a zone, so the adapter converts using the
	// endpoint's local zone and leaves the value zero when it cannot.
	CreatedAtMS  int64 `json:"created_at_ms,omitempty"`
	ModifiedAtMS int64 `json:"modified_at_ms,omitempty"`
	// ProviderNo is the provider's own row number, kept for operator
	// cross-reference. It is never a selection key.
	ProviderNo int `json:"provider_no,omitempty"`
	// Resumable is the adapter's first-line verdict. The cluster does not
	// re-derive it and does not second-guess it.
	Resumable bool `json:"resumable"`
	// ResumeBlockedReason is a bounded standard reason code when Resumable is false.
	ResumeBlockedReason string `json:"resume_blocked_reason,omitempty"`
}

// HistoryResult carries one bounded provider history read.
//
// Truncated reports that the provider returned its own capped window rather than
// everything that exists. It is surfaced so a bounded window is never presented
// as a complete history.
type HistoryResult struct {
	Rows         []HistoryRow `json:"rows"`
	ObservedAtMS int64        `json:"observed_at_ms"`
	Truncated    bool         `json:"truncated,omitempty"`
	ErrorCode    string       `json:"error_code,omitempty"`
}

// Standard resume-blocked reason codes. They are provider-neutral: an adapter
// maps its own vocabulary onto these values and keeps provider detail local.
const (
	// ResumeBlockedProviderRunning means the provider reports the session as live.
	ResumeBlockedProviderRunning = "provider_running"
	// ResumeBlockedWorkspaceMissing means the recorded workspace is unusable.
	ResumeBlockedWorkspaceMissing = "workspace_missing"
	// ResumeBlockedRecordIncomplete means the provider record cannot be trusted,
	// including an unrecognized status word. An unknown status is never resumable.
	ResumeBlockedRecordIncomplete = "record_incomplete"
)

// Standard history error codes.
const (
	// HistoryUnsupported means no configured adapter can list history.
	HistoryUnsupported = "history_unsupported"
	// HistoryProviderError means the provider call failed.
	HistoryProviderError = "provider_error"
	// HistoryResponseTooLarge means the provider document exceeded a bound.
	HistoryResponseTooLarge = "history_response_too_large"
)

// Bounds for one history read. They are deliberately small: history is an
// operator-facing window, not a bulk export.
const (
	// MaxHistoryRows bounds the accepted row count.
	MaxHistoryRows = 1000
	// MaxHistoryBytes bounds the accepted provider document size.
	MaxHistoryBytes = 512 << 10
	// MaxHistoryTaskBytes bounds one task text.
	MaxHistoryTaskBytes = 8192
)
