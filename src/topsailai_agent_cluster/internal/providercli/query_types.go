package providercli

import (
	"bytes"
	"encoding/json"
	"errors"
	"fmt"

	"topsailai_agent_cluster/internal/protocol"
)

// LaunchOptionsPayload selects whether launch projects are included with the profile facts.
type LaunchOptionsPayload struct {
	IncludeProjects bool `json:"include_projects"`
}

// LaunchProfileFact is one provider-private launch profile before Endpoint mapping.
type LaunchProfileFact struct {
	ResourceKind        string `json:"resource_kind"`
	ProviderResourceKey string `json:"provider_resource_key"`
	DisplayName         string `json:"display_name"`
	Revision            string `json:"revision"`
}

// LaunchProjectFact is one provider-managed project directory.
type LaunchProjectFact struct {
	Name string `json:"name"`
	Path string `json:"path"`
}

// LaunchOptionsResult carries one Adapter instance's launch profile and optional projects.
type LaunchOptionsResult struct {
	Profile  LaunchProfileFact   `json:"profile"`
	Projects []LaunchProjectFact `json:"projects"`
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

// SessionDetailPayload is the closed payload of a session-scoped detail read.
type SessionDetailPayload struct{}

// SessionDetailResult carries one session's provider metadata and runtime document.
type SessionDetailResult struct {
	ProviderSessionID string `json:"provider_session_id"`
	Metadata          string `json:"metadata"`
	Runtime           string `json:"runtime,omitempty"`
	ObservedAtMS      int64  `json:"observed_at_ms"`
	MetadataTruncated bool   `json:"metadata_truncated,omitempty"`
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
func DecodeQueryResult(query NamedContract, data json.RawMessage) (any, error) {
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
	case QuerySessionDetail:
		var value SessionDetailResult
		if err := decodeStrict(data, &value); err != nil {
			return nil, err
		}
		return value, value.validate()
	default:
		return nil, fmt.Errorf("unsupported query %q", query.Name)
	}
}

func validateQueryTarget(name string, target *Target) error {
	switch name {
	case QueryLaunchOptions, QueryHistoryMessages:
		if target != nil {
			return fmt.Errorf("%s query must not contain target", name)
		}
	case QueryModelCatalog, QuerySessionMessages, QuerySessionMetrics, QuerySessionDetail:
		if target == nil {
			return fmt.Errorf("%s query requires a session target", name)
		}
		if target.ResourceKind != ResourceSession {
			return fmt.Errorf("%s query target must be resource_kind session", name)
		}
		if err := target.validate(false); err != nil {
			return err
		}
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
	if r.Projects == nil {
		return errors.New("launch projects are required")
	}
	if len(r.Projects) > protocol.MaxProjects {
		return fmt.Errorf("launch projects exceed %d", protocol.MaxProjects)
	}
	for _, project := range r.Projects {
		if project.Name == "" || project.Path == "" {
			return errors.New("launch project name and path are required")
		}
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

// validate rejects a detail result whose documents are absent or oversized.
// Metadata is required because a detail read that returns no record has not
// answered the question, while Runtime is optional because it is a seam that no
// provider fills yet.
func (r SessionDetailResult) validate() error {
	if err := validateIdentifier("provider_session_id", r.ProviderSessionID, true); err != nil {
		return err
	}
	if r.ObservedAtMS < 1 {
		return errors.New("session detail result has invalid observation time")
	}
	if r.Metadata == "" {
		return errors.New("session detail metadata is required")
	}
	if len(r.Metadata) > protocol.MaxDetailBytes || len(r.Runtime) > protocol.MaxDetailBytes {
		return fmt.Errorf("session detail document exceeds %d bytes", protocol.MaxDetailBytes)
	}
	return nil
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
