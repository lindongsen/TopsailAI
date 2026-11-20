package providercli

import (
	"bytes"
	"encoding/json"
	"errors"
	"fmt"

	"topsailai_agent_cluster/internal/protocol"
)

// LaunchOptionsPayload is the closed payload of a launch-profile read.
type LaunchOptionsPayload struct{}

// LaunchProfileFact is one provider-private launch profile before Endpoint mapping.
type LaunchProfileFact struct {
	ResourceKind        string `json:"resource_kind"`
	ProviderResourceKey string `json:"provider_resource_key"`
	DisplayName         string `json:"display_name"`
	Revision            string `json:"revision"`
}

// LaunchOptionsResult carries one Adapter instance's launch profile.
type LaunchOptionsResult struct {
	Profile LaunchProfileFact `json:"profile"`
}

// HistoryMessagesPayload bounds one provider history read.
type HistoryMessagesPayload struct {
	Limit int `json:"limit"`
}

// HistoryRowFact is one provider-private history row before Endpoint mapping.
type HistoryRowFact struct {
	ResourceKind             string `json:"resource_kind"`
	ProviderResourceKey      string `json:"provider_resource_key"`
	ProviderSessionID        string `json:"provider_session_id"`
	ProviderDisplayName      string `json:"provider_display_name,omitempty"`
	ProviderProjectWorkspace string `json:"provider_project_workspace,omitempty"`
	Task                     string `json:"task,omitempty"`
	ProviderStatus           string `json:"provider_status,omitempty"`
	CreatedAtMS              int64  `json:"created_at_ms,omitempty"`
	ModifiedAtMS             int64  `json:"modified_at_ms,omitempty"`
	ProviderNo               int    `json:"provider_no,omitempty"`
	Resumable                bool   `json:"resumable"`
	ResumeBlockedReason      string `json:"resume_blocked_reason,omitempty"`
}

// HistoryMessagesResult carries one bounded provider history observation.
type HistoryMessagesResult struct {
	Rows         []HistoryRowFact `json:"rows"`
	ObservedAtMS int64            `json:"observed_at_ms"`
	Truncated    bool             `json:"truncated"`
}

// ModelCatalogPayload is the closed payload of a session-scoped model catalog read.
type ModelCatalogPayload struct{}

// ModelProfileFact is one provider-private model profile before Endpoint mapping.
type ModelProfileFact struct {
	ResourceKind        string `json:"resource_kind"`
	ProviderResourceKey string `json:"provider_resource_key"`
	ProviderDisplayName string `json:"provider_display_name,omitempty"`
	CurrentState        string `json:"current_state"`
	Available           bool   `json:"available"`
	UnavailableReason   string `json:"unavailable_reason,omitempty"`
}

// ModelCatalogResult carries one bounded provider model catalog observation.
type ModelCatalogResult struct {
	Profiles                   []ModelProfileFact `json:"profiles"`
	CurrentProviderResourceKey string             `json:"current_provider_resource_key,omitempty"`
	ObservedAtMS               int64              `json:"observed_at_ms"`
	Truncated                  bool               `json:"truncated"`
}

// ProjectCatalogPayload is the closed payload of an Endpoint-scoped project read.
type ProjectCatalogPayload struct{}

// ProjectFact is one provider-private project before Endpoint mapping.
type ProjectFact struct {
	ResourceKind        string `json:"resource_kind"`
	ProviderResourceKey string `json:"provider_resource_key"`
	Name                string `json:"name"`
	Path                string `json:"path"`
}

// ProjectCatalogResult carries one bounded provider project observation.
type ProjectCatalogResult struct {
	Projects     []ProjectFact `json:"projects"`
	ObservedAtMS int64         `json:"observed_at_ms"`
	Truncated    bool          `json:"truncated"`
}

// SessionMessagesPayload bounds one provider conversation read.
type SessionMessagesPayload struct {
	MaxChars  int `json:"max_chars"`
	MaxTokens int `json:"max_tokens"`
}

// SessionMessageFact is one provider-neutral conversation record.
type SessionMessageFact struct {
	Role        string `json:"role,omitempty"`
	Content     string `json:"content"`
	CreatedAtMS int64  `json:"created_at_ms,omitempty"`
	WordCount   int    `json:"word_count,omitempty"`
	TokenCount  int    `json:"token_count,omitempty"`
}

// SessionMessagesResult carries one bounded provider conversation observation.
type SessionMessagesResult struct {
	ProviderSessionID string               `json:"provider_session_id"`
	Messages          []SessionMessageFact `json:"messages"`
	MessageCount      int                  `json:"message_count"`
	ObservedAtMS      int64                `json:"observed_at_ms"`
	Truncated         bool                 `json:"truncated"`
}

// SessionMetricsPayload is the closed payload of a session-scoped metrics read.
type SessionMetricsPayload struct{}

// SessionMetricsBatchPayload carries the bounded set of sessions one batch read
// addresses.
//
// The set is in the payload rather than in a target because a target names one
// resource and this request names many. It is a caller-supplied collection, so it
// is bounded by protocol.MaxMetricsBatchSessions before any provider process
// starts.
type SessionMetricsBatchPayload struct {
	ProviderSessionIDs []string `json:"provider_session_ids"`
}

// MessageCountsFact carries the two provider message counts before Endpoint mapping.
type MessageCountsFact struct {
	Inbound  int `json:"inbound"`
	Outbound int `json:"outbound"`
}

// SessionMetricsResult carries one session's current message counts.
type SessionMetricsResult struct {
	ProviderSessionID string            `json:"provider_session_id"`
	Messages          MessageCountsFact `json:"messages"`
	ObservedAtMS      int64             `json:"observed_at_ms"`
}

// SessionMetricsBatchResult carries the message counts of a bounded set of
// sessions.
//
// Each member is a SessionMetricsResult, so a member that could not be measured
// is reported by its own absence rather than by a zero count. A zero is a
// measured zero, and a set read that filled an unmeasured member with zeros would
// state a fact the provider never observed.
type SessionMetricsBatchResult struct {
	Results      []SessionMetricsResult `json:"results"`
	ObservedAtMS int64                  `json:"observed_at_ms"`
}

// SessionDetailPayload is the closed payload of a session-scoped detail read.
type SessionDetailPayload struct{}

// SessionDetailResult carries one session's two provider documents.
//
// Both documents are optional, because a provider may legitimately report one and
// not the other. Requiring either would force a provider to emit a placeholder,
// and a placeholder is a claim nobody made.
//
// There is no truncation flag. An oversized document is rejected rather than
// shortened, so a consumer never has to decide whether a document it received is
// the whole document.
type SessionDetailResult struct {
	ProviderSessionID string `json:"provider_session_id"`
	ProviderMetadata  string `json:"provider_metadata,omitempty"`
	ProviderRuntime   string `json:"provider_runtime,omitempty"`
	ObservedAtMS      int64  `json:"observed_at_ms"`
}

// DecodeQueryPayload validates and decodes one query-specific request payload.
func DecodeQueryPayload(query NamedContract, target *Target, payload json.RawMessage) (any, error) {
	if isNullJSON(payload) {
		return nil, errors.New("query payload must not be null")
	}
	if !IsStandardQuery(query.Name, query.Version) {
		return nil, fmt.Errorf("unregistered standard query %q version %q", query.Name, query.Version)
	}
	if err := validateQueryTarget(query.Name, target); err != nil {
		return nil, err
	}
	switch query.Name {
	case QueryLaunchOptions:
		var value LaunchOptionsPayload
		if err := decodeStrict(payload, &value); err != nil {
			return nil, err
		}
		return value, nil
	case QueryHistoryMessages:
		var value HistoryMessagesPayload
		if err := decodeStrict(payload, &value); err != nil {
			return nil, err
		}
		if value.Limit < 0 || value.Limit > protocol.MaxHistoryRows {
			return nil, fmt.Errorf("history limit must be between 0 and %d", protocol.MaxHistoryRows)
		}
		return value, nil
	case QueryModelCatalog:
		var value ModelCatalogPayload
		if err := decodeStrict(payload, &value); err != nil {
			return nil, err
		}
		return value, nil
	case QueryProjectCatalog:
		var value ProjectCatalogPayload
		if err := decodeStrict(payload, &value); err != nil {
			return nil, err
		}
		return value, nil
	case QuerySessionMessages:
		var value SessionMessagesPayload
		if err := decodeStrict(payload, &value); err != nil {
			return nil, err
		}
		if value.MaxChars < 0 || value.MaxChars > protocol.MaxMessagesMaxChars {
			return nil, fmt.Errorf("max_chars must be between 0 and %d", protocol.MaxMessagesMaxChars)
		}
		if value.MaxTokens < 0 || value.MaxTokens > protocol.MaxMessagesMaxTokens {
			return nil, fmt.Errorf("max_tokens must be between 0 and %d", protocol.MaxMessagesMaxTokens)
		}
		return value, nil
	case QuerySessionMetrics:
		var value SessionMetricsPayload
		if err := decodeStrict(payload, &value); err != nil {
			return nil, err
		}
		return value, nil
	case QuerySessionMetricsBatch:
		var value SessionMetricsBatchPayload
		if err := decodeStrict(payload, &value); err != nil {
			return nil, err
		}
		// The set is validated here, before any provider process starts, so an
		// oversized or empty request fails at the contract boundary instead of
		// becoming an unbounded provider document.
		if len(value.ProviderSessionIDs) == 0 {
			return nil, errors.New("session.metrics.batch requires at least one provider_session_id")
		}
		if len(value.ProviderSessionIDs) > protocol.MaxMetricsBatchSessions {
			return nil, fmt.Errorf("session.metrics.batch accepts at most %d sessions", protocol.MaxMetricsBatchSessions)
		}
		seen := make(map[string]struct{}, len(value.ProviderSessionIDs))
		for _, sessionID := range value.ProviderSessionIDs {
			// The member is a provider-private identity, so it is validated with
			// the same rule the single-session read applies to its target. A
			// Cluster resource ID is refused here rather than forwarded, because
			// the provider cannot resolve one: it would silently omit the member
			// and the caller would read a caller error as an unmeasured session.
			if err := validateProviderResourceKey("provider_session_id", sessionID, true); err != nil {
				return nil, err
			}
			if _, duplicate := seen[sessionID]; duplicate {
				return nil, fmt.Errorf("session.metrics.batch contains duplicate provider_session_id %q", sessionID)
			}
			seen[sessionID] = struct{}{}
		}
		return value, nil
	case QuerySessionDetail:
		var value SessionDetailPayload
		if err := decodeStrict(payload, &value); err != nil {
			return nil, err
		}
		return value, nil
	default:
		return nil, errors.New("unsupported query")
	}
}

// DecodeQueryResult strictly decodes and validates one query-specific Provider result.
//
// maxDetailBytes is the configured bound for one provider detail document. It is a
// parameter rather than a package constant because the bound is Endpoint
// configuration: an operator may raise it for a provider whose records are large,
// and a package constant would silently ignore that setting.
func DecodeQueryResult(query NamedContract, data json.RawMessage, maxDetailBytes int) (any, error) {
	if !IsStandardQuery(query.Name, query.Version) {
		return nil, fmt.Errorf("unregistered standard query %q version %q", query.Name, query.Version)
	}
	if isNullJSON(data) {
		return nil, errors.New("query_result must not be null")
	}
	if len(data) == 0 {
		return nil, errors.New("query_result is required")
	}
	switch query.Name {
	case QueryLaunchOptions:
		var value LaunchOptionsResult
		if err := decodeStrict(data, &value); err != nil {
			return nil, err
		}
		return value, value.validate()
	case QueryHistoryMessages:
		var value HistoryMessagesResult
		if err := decodeStrict(data, &value); err != nil {
			return nil, err
		}
		return value, value.validate()
	case QueryModelCatalog:
		var value ModelCatalogResult
		if err := decodeStrict(data, &value); err != nil {
			return nil, err
		}
		return value, value.validate()
	case QueryProjectCatalog:
		var value ProjectCatalogResult
		if err := decodeStrict(data, &value); err != nil {
			return nil, err
		}
		return value, value.validate()
	case QuerySessionMessages:
		var value SessionMessagesResult
		if err := decodeStrict(data, &value); err != nil {
			return nil, err
		}
		return value, value.validate()
	case QuerySessionMetrics:
		var value SessionMetricsResult
		if err := decodeStrict(data, &value); err != nil {
			return nil, err
		}
		return value, value.validate()
	case QuerySessionMetricsBatch:
		var value SessionMetricsBatchResult
		if err := decodeStrict(data, &value); err != nil {
			return nil, err
		}
		return value, value.validate()
	case QuerySessionDetail:
		var value SessionDetailResult
		if err := decodeStrict(data, &value); err != nil {
			return nil, err
		}
		return value, value.validate(maxDetailBytes)
	default:
		return nil, fmt.Errorf("unsupported query %q", query.Name)
	}
}

func validateQueryTarget(name string, target *Target) error {
	if QueryRequiresSessionTarget(name) {
		if target == nil {
			return fmt.Errorf("%s query requires a session target", name)
		}
		if target.ResourceKind != ResourceSession {
			return fmt.Errorf("%s query target must be resource_kind session", name)
		}
		if err := target.validate(false); err != nil {
			return err
		}
		return nil
	}
	if target != nil {
		return fmt.Errorf("%s query must not contain target", name)
	}
	return nil
}

func (r LaunchOptionsResult) validate() error {
	if err := validateTypedProviderKey(r.Profile.ResourceKind, ResourceLaunchProfile, r.Profile.ProviderResourceKey); err != nil {
		return err
	}
	if err := validateIdentifier("launch profile display_name", r.Profile.DisplayName, true); err != nil {
		return err
	}
	if err := validateIdentifier("launch profile revision", r.Profile.Revision, true); err != nil {
		return err
	}
	return nil
}

func (r HistoryMessagesResult) validate() error {
	if r.Rows == nil {
		return errors.New("history rows are required")
	}
	if len(r.Rows) > protocol.MaxHistoryRows || r.ObservedAtMS < 1 {
		return errors.New("history result exceeds bounds or has invalid observation time")
	}
	seen := make(map[string]struct{}, len(r.Rows))
	for _, row := range r.Rows {
		if err := validateTypedProviderKey(row.ResourceKind, ResourceSession, row.ProviderResourceKey); err != nil {
			return err
		}
		if _, ok := seen[row.ProviderResourceKey]; ok {
			return fmt.Errorf("duplicate history provider_resource_key %q", row.ProviderResourceKey)
		}
		seen[row.ProviderResourceKey] = struct{}{}
		if err := validateIdentifier("provider_session_id", row.ProviderSessionID, true); err != nil {
			return err
		}
		if row.CreatedAtMS < 0 || row.ModifiedAtMS < 0 || row.ProviderNo < 0 {
			return errors.New("history numeric fields must not be negative")
		}
	}
	return nil
}

func (r ModelCatalogResult) validate() error {
	if r.Profiles == nil {
		return errors.New("model profiles are required")
	}
	if len(r.Profiles) > protocol.MaxModelProfiles || r.ObservedAtMS < 1 {
		return errors.New("model catalog exceeds bounds or has invalid observation time")
	}
	seen := make(map[string]struct{}, len(r.Profiles))
	for _, profile := range r.Profiles {
		if err := validateTypedProviderKey(profile.ResourceKind, ResourceModelProfile, profile.ProviderResourceKey); err != nil {
			return err
		}
		if _, ok := seen[profile.ProviderResourceKey]; ok {
			return fmt.Errorf("duplicate model provider_resource_key %q", profile.ProviderResourceKey)
		}
		seen[profile.ProviderResourceKey] = struct{}{}
		if err := protocol.ValidateModelCurrentState(profile.CurrentState); err != nil {
			return err
		}
	}
	if r.CurrentProviderResourceKey != "" {
		if _, ok := seen[r.CurrentProviderResourceKey]; !ok {
			return errors.New("current_provider_resource_key is not in profiles")
		}
	}
	return nil
}

func (r ProjectCatalogResult) validate() error {
	if r.Projects == nil {
		return errors.New("projects are required")
	}
	if len(r.Projects) > protocol.MaxProjects || r.ObservedAtMS < 1 {
		return errors.New("project catalog exceeds bounds or has invalid observation time")
	}
	seen := make(map[string]struct{}, len(r.Projects))
	for _, project := range r.Projects {
		if err := validateTypedProviderKey(project.ResourceKind, ResourceProject, project.ProviderResourceKey); err != nil {
			return err
		}
		if _, ok := seen[project.ProviderResourceKey]; ok {
			return fmt.Errorf("duplicate project provider_resource_key %q", project.ProviderResourceKey)
		}
		seen[project.ProviderResourceKey] = struct{}{}
		if project.Name == "" || project.Path == "" {
			return errors.New("project name and path are required")
		}
		if err := protocol.ValidateFolder(project.Path); err != nil {
			return fmt.Errorf("project %q path is invalid: %w", project.Name, err)
		}
	}
	return nil
}

func (r SessionMessagesResult) validate() error {
	if err := validateIdentifier("provider_session_id", r.ProviderSessionID, true); err != nil {
		return err
	}
	if r.Messages == nil || len(r.Messages) > protocol.MaxMessages || r.MessageCount < len(r.Messages) || r.ObservedAtMS < 1 {
		return errors.New("session messages result is invalid or exceeds bounds")
	}
	for _, message := range r.Messages {
		if message.CreatedAtMS < 0 || message.WordCount < 0 || message.TokenCount < 0 {
			return errors.New("message numeric fields must not be negative")
		}
	}
	return nil
}

// validate rejects a metrics result that cannot be presented as a real count.
// A negative or absurd count is refused rather than clamped, because a clamped
// count would be presented as a measurement the provider never made.
func (r SessionMetricsResult) validate() error {
	if err := validateIdentifier("provider_session_id", r.ProviderSessionID, true); err != nil {
		return err
	}
	if r.ObservedAtMS < 1 {
		return errors.New("session metrics result has invalid observation time")
	}
	if r.Messages.Inbound < 0 || r.Messages.Outbound < 0 {
		return errors.New("message counts must not be negative")
	}
	if r.Messages.Inbound > protocol.MaxMessageCount || r.Messages.Outbound > protocol.MaxMessageCount {
		return fmt.Errorf("message counts exceed %d", protocol.MaxMessageCount)
	}
	return nil
}

// validate rejects a batch result that cannot be presented as real counts.
//
// Every member is validated with the same rule a single-session read uses, so a
// batch cannot accept a count the single read would refuse. The member count is
// bounded by the same limit the request is bounded by, because a provider that
// answered more sessions than were asked about has not answered the question.
//
// A duplicate member is refused rather than collapsed: two entries for one
// session would leave the caller choosing which one is the measurement, and that
// choice belongs to the provider that made it.
func (r SessionMetricsBatchResult) validate() error {
	if r.Results == nil {
		return errors.New("session metrics batch results are required")
	}
	if r.ObservedAtMS < 1 {
		return errors.New("session metrics batch result has invalid observation time")
	}
	if len(r.Results) > protocol.MaxMetricsBatchSessions {
		return fmt.Errorf("session metrics batch exceeds %d results", protocol.MaxMetricsBatchSessions)
	}
	seen := make(map[string]struct{}, len(r.Results))
	for _, result := range r.Results {
		if err := result.validate(); err != nil {
			return err
		}
		if _, duplicate := seen[result.ProviderSessionID]; duplicate {
			return fmt.Errorf("session metrics batch contains duplicate provider_session_id %q", result.ProviderSessionID)
		}
		seen[result.ProviderSessionID] = struct{}{}
	}
	return nil
}

// validate rejects a detail result that cannot be presented as a real
// observation.
//
// Both documents are optional, so an empty document is accepted and reported as
// not reported. What is rejected is a document that exceeds the configured bound:
// the contract refuses it rather than shortening it, because a shortened provider
// document presented as the whole document leaves the consumer unable to tell
// which fields were dropped.
//
// The rejection carries DetailResponseTooLarge so the failure reaches the operator
// as a specific machine code. A plain error would surface as a generic decode
// failure, and the operator would read "the provider is broken" instead of "this
// record is larger than the configured bound".
func (r SessionDetailResult) validate(maxBytes int) error {
	if err := validateIdentifier("provider_session_id", r.ProviderSessionID, true); err != nil {
		return err
	}
	if r.ObservedAtMS < 1 {
		return errors.New("session detail result has invalid observation time")
	}
	for _, document := range []struct {
		name  string
		value string
	}{
		{"provider_metadata", r.ProviderMetadata},
		{"provider_runtime", r.ProviderRuntime},
	} {
		if len(document.value) > maxBytes {
			return detailTooLargeError{field: document.name, size: len(document.value), max: maxBytes}
		}
	}
	return nil
}

// detailTooLargeError reports one provider document that exceeded the configured
// bound.
//
// It is a typed error rather than a formatted string because the Endpoint
// classifies a read failure by its machine code. Without the code the rejection
// would be indistinguishable from a malformed provider response, and the operator
// would be told to investigate a provider that answered correctly.
type detailTooLargeError struct {
	field string
	size  int
	max   int
}

func (e detailTooLargeError) Error() string {
	return fmt.Sprintf("session detail %s is %d bytes, exceeding the configured bound of %d bytes", e.field, e.size, e.max)
}

// ErrorCode reports the stable machine code for an oversized provider document.
func (e detailTooLargeError) ErrorCode() string {
	return protocol.DetailResponseTooLarge
}

func validateTypedProviderKey(actualKind, requiredKind, key string) error {
	if actualKind != requiredKind {
		return fmt.Errorf("resource_kind must be %q, got %q", requiredKind, actualKind)
	}
	return validateProviderResourceKey("provider_resource_key", key, true)
}

func isNullJSON(data json.RawMessage) bool {
	trimmed := bytes.TrimSpace(data)
	return len(trimmed) == 0 || bytes.Equal(trimmed, []byte("null"))
}
