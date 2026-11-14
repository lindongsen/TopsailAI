package main

import (
	"context"
	"encoding/json"
	"fmt"
	"strings"
	"time"
	"unicode/utf8"
)

const (
	queryVersion           = "v1"
	launchProfileKey       = "topsailai-default"
	launchProfileRevision  = "topsailai-launch-v1"
	modelProviderKeyPrefix = "model:"
	providerHistoryRowCap  = 30
	maxProjects            = 1000
	maxProjectBytes        = 256 << 10
	maxHistoryRows         = 1000
	maxHistoryBytes        = 1 << 20
	maxHistoryTaskBytes    = 8192
	maxModelProfiles       = 1000
	maxModelBytes          = 1 << 20
	maxMessages            = 1000
	maxMessagesBytes       = 4 << 20
)

type launchOptionsPayload struct {
	IncludeProjects bool `json:"include_projects"`
}
type launchProfileFact struct {
	ResourceKind        string `json:"resource_kind"`
	ProviderResourceKey string `json:"provider_resource_key"`
	DisplayName         string `json:"display_name"`
	Revision            string `json:"revision"`
}

type projectFact struct {
	Name string `json:"name"`
	Path string `json:"path"`
}
type launchOptionsResult struct {
	Profile  launchProfileFact `json:"profile"`
	Projects []projectFact     `json:"projects"`
}

type historyPayload struct {
	Limit int `json:"limit"`
}
type historyEntry struct {
	SessionID        string `json:"session_id"`
	SessionName      string `json:"session_name"`
	ProjectWorkspace string `json:"project_workspace"`
	ModifiedTimeRaw  string `json:"modified_time_raw"`
	CreateTimeRaw    string `json:"create_time_raw"`
	Task             string `json:"task"`
	No               int    `json:"no"`
	Status           string `json:"status"`
}
type historyRowFact struct {
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
type historyResult struct {
	Rows         []historyRowFact `json:"rows"`
	ObservedAtMS int64            `json:"observed_at_ms"`
	Truncated    bool             `json:"truncated"`
}

type modelEntry struct {
	Name     string `json:"name"`
	Protocol string `json:"protocol"`
	Enabled  *bool  `json:"enabled"`
}
type modelProfileFact struct {
	ResourceKind        string `json:"resource_kind"`
	ProviderResourceKey string `json:"provider_resource_key"`
	ProviderDisplayName string `json:"provider_display_name,omitempty"`
	CurrentState        string `json:"current_state"`
	Available           bool   `json:"available"`
	UnavailableReason   string `json:"unavailable_reason,omitempty"`
}
type modelResult struct {
	Profiles                   []modelProfileFact `json:"profiles"`
	CurrentProviderResourceKey string             `json:"current_provider_resource_key,omitempty"`
	ObservedAtMS               int64              `json:"observed_at_ms"`
	Truncated                  bool               `json:"truncated"`
}

type messagesPayload struct {
	MaxChars  int `json:"max_chars"`
	MaxTokens int `json:"max_tokens"`
}
type messagesEntry struct {
	Role       string `json:"role"`
	Content    string `json:"content"`
	CreateTime string `json:"create_time"`
}
type messagesEnvelope struct {
	OK           bool            `json:"ok"`
	ErrorCode    string          `json:"error_code"`
	SessionID    string          `json:"session_id"`
	MessageCount int             `json:"message_count"`
	Messages     []messagesEntry `json:"messages"`
}
type messageFact struct {
	Role        string `json:"role,omitempty"`
	Content     string `json:"content"`
	CreatedAtMS int64  `json:"created_at_ms,omitempty"`
	WordCount   int    `json:"word_count,omitempty"`
	TokenCount  int    `json:"token_count,omitempty"`
}
type messagesResult struct {
	ProviderSessionID string        `json:"provider_session_id"`
	Messages          []messageFact `json:"messages"`
	MessageCount      int           `json:"message_count"`
	ObservedAtMS      int64         `json:"observed_at_ms"`
	Truncated         bool          `json:"truncated"`
}

func (p *provider) query(ctx context.Context, contract *namedContract, requested *target, payload json.RawMessage) (json.RawMessage, error) {
	if contract == nil || contract.Version != queryVersion {
		return nil, fmt.Errorf("%w: standard query v1 is required", errInvalidRequest)
	}
	var value any
	var err error
	switch contract.Name {
	case queryLaunchOptions:
		value, err = p.launchOptions(ctx, requested, payload)
	case queryHistoryMessages:
		value, err = p.history(ctx, requested, payload)
	case queryModelCatalog:
		value, err = p.models(ctx, requested, payload)
	case querySessionMessages:
		value, err = p.messages(ctx, requested, payload)
	default:
		return nil, errUnsupported
	}
	if err != nil {
		return nil, err
	}
	return json.Marshal(value)
}

func (p *provider) launchOptions(ctx context.Context, requested *target, raw json.RawMessage) (launchOptionsResult, error) {
	if requested != nil {
		return launchOptionsResult{}, fmt.Errorf("%w: launch.options does not accept a target", errInvalidRequest)
	}
	var payload launchOptionsPayload
	if err := decodeStrict(raw, &payload); err != nil {
		return launchOptionsResult{}, fmt.Errorf("%w: launch.options payload: %v", errInvalidRequest, err)
	}
	result := launchOptionsResult{Profile: launchProfileFact{resourceLaunchProfile, launchProfileKey, "TopsailAI", launchProfileRevision}, Projects: []projectFact{}}
	if !payload.IncludeProjects {
		return result, nil
	}
	var projects []projectFact
	if err := runJSON(ctx, p.runner, []string{"project", "list", "--json"}, maxProjectBytes, &projects); err != nil {
		return launchOptionsResult{}, err
	}
	if projects == nil || len(projects) > maxProjects {
		return launchOptionsResult{}, errorsNew("invalid or oversized project list")
	}
	for _, project := range projects {
		if project.Name == "" || project.Path == "" {
			return launchOptionsResult{}, errorsNew("project name and path are required")
		}
	}
	result.Projects = projects
	return result, nil
}

func (p *provider) history(ctx context.Context, requested *target, raw json.RawMessage) (historyResult, error) {
	if requested != nil {
		return historyResult{}, fmt.Errorf("%w: history.messages does not accept a target", errInvalidRequest)
	}
	var payload historyPayload
	if err := decodeStrict(raw, &payload); err != nil || payload.Limit < 0 || payload.Limit > maxHistoryRows {
		return historyResult{}, fmt.Errorf("%w: invalid history payload", errInvalidRequest)
	}
	var entries []historyEntry
	if err := runJSON(ctx, p.runner, []string{"project", "list_sessions", "--json"}, maxHistoryBytes, &entries); err != nil {
		return historyResult{}, err
	}
	if len(entries) > maxHistoryRows {
		return historyResult{}, errorsNew("history row count exceeds limit")
	}
	truncated := len(entries) >= providerHistoryRowCap
	if payload.Limit > 0 && payload.Limit < len(entries) {
		entries = entries[:payload.Limit]
		truncated = true
	}
	result := historyResult{Rows: make([]historyRowFact, 0, len(entries)), ObservedAtMS: p.now().UnixMilli(), Truncated: truncated}
	seen := make(map[string]struct{}, len(entries))
	for _, entry := range entries {
		key, err := historySessionKey(entry.SessionID)
		if err != nil {
			return historyResult{}, err
		}
		if _, exists := seen[key]; exists {
			return historyResult{}, errorsNew("history response contains duplicate provider resource key")
		}
		seen[key] = struct{}{}
		resumable, reason := historyResumability(entry.Status)
		result.Rows = append(result.Rows, historyRowFact{resourceSession, key, entry.SessionID, entry.SessionName, entry.ProjectWorkspace, boundedString(entry.Task, maxHistoryTaskBytes), entry.Status, providerTimeMS(entry.CreateTimeRaw), providerTimeMS(entry.ModifiedTimeRaw), entry.No, resumable, reason})
	}
	return result, nil
}

func (p *provider) models(ctx context.Context, requested *target, raw json.RawMessage) (modelResult, error) {
	var payload struct{}
	if err := decodeStrict(raw, &payload); err != nil {
		return modelResult{}, fmt.Errorf("%w: model.catalog payload", errInvalidRequest)
	}
	if _, err := p.resolveWorkspaceTarget(ctx, requested); err != nil {
		return modelResult{}, err
	}
	var entries []modelEntry
	if err := runJSON(ctx, p.runner, []string{"models", "list", "--json"}, maxModelBytes, &entries); err != nil {
		return modelResult{}, err
	}
	if len(entries) > maxModelProfiles {
		return modelResult{}, errorsNew("model profile count exceeds limit")
	}
	entries = collapseModels(entries)
	result := modelResult{Profiles: make([]modelProfileFact, 0, len(entries)), ObservedAtMS: p.now().UnixMilli()}
	seen := make(map[string]struct{}, len(entries))
	for _, entry := range entries {
		if strings.TrimSpace(entry.Name) == "" {
			return modelResult{}, errorsNew("model profile name is required")
		}
		key := modelProviderKeyPrefix + entry.Name
		if len(key) > maxProviderKeyLength {
			return modelResult{}, errorsNew("model provider resource key exceeds contract limit")
		}
		if _, exists := seen[key]; exists {
			return modelResult{}, errorsNew("model response contains duplicate provider resource key")
		}
		seen[key] = struct{}{}
		available, reason := modelAvailability(entry)
		result.Profiles = append(result.Profiles, modelProfileFact{resourceModelProfile, key, boundedString(entry.Name, 256), "unknown", available, reason})
	}
	return result, nil
}

func (p *provider) messages(ctx context.Context, requested *target, raw json.RawMessage) (messagesResult, error) {
	if requested == nil || requested.ResourceKind != resourceSession || strings.TrimSpace(requested.ProviderResourceKey) == "" || len(requested.ProviderResourceKey) > maxProviderKeyLength {
		return messagesResult{}, fmt.Errorf("%w: provider session ID target is required", errInvalidRequest)
	}
	sessionID := requested.ProviderResourceKey
	var payload messagesPayload
	if err := decodeStrict(raw, &payload); err != nil || payload.MaxChars < 0 || payload.MaxChars > 100000 || payload.MaxTokens < 0 || payload.MaxTokens > 200000 {
		return messagesResult{}, fmt.Errorf("%w: invalid session.messages payload", errInvalidRequest)
	}
	var info struct {
		ErrorCode string `json:"error_code"`
	}
	if err := runJSON(ctx, p.runner, []string{"session", "info", sessionID, "--json"}, maxMessagesBytes, &info); err != nil {
		return messagesResult{}, err
	}
	if info.ErrorCode != "" {
		// A session the provider does not know is reported with its own code so
		// the Cluster can answer "this session does not exist" instead of "the
		// provider failed". The two send the operator to different places.
		return messagesResult{}, codedError{code: providerSessionNotFoundCode, message: "provider session does not exist"}
	}
	var envelope messagesEnvelope
	if err := runJSON(ctx, p.runner, []string{"session", "history", sessionID, "--json"}, maxMessagesBytes, &envelope); err != nil {
		return messagesResult{}, err
	}
	if !envelope.OK || envelope.ErrorCode != "" || len(envelope.Messages) > maxMessages {
		return messagesResult{}, errorsNew("invalid session history response")
	}
	result := messagesResult{ProviderSessionID: sessionID, Messages: make([]messageFact, 0, len(envelope.Messages)), MessageCount: envelope.MessageCount, ObservedAtMS: p.now().UnixMilli(), Truncated: envelope.MessageCount > len(envelope.Messages)}
	total := 0
	for _, entry := range envelope.Messages {
		content := unwrapContent(entry.Content)
		total += len(content)
		if total > maxMessagesBytes {
			result.Truncated = true
			break
		}
		result.Messages = append(result.Messages, messageFact{entry.Role, content, providerTimeMS(entry.CreateTime), utf8.RuneCountInString(entry.Content), tokenCount(entry.Content)})
	}
	return result, nil
}

func historyResumability(status string) (bool, string) {
	switch strings.TrimSpace(status) {
	case "Idle":
		return true, ""
	case "Running":
		return false, "provider_running"
	default:
		return false, "record_incomplete"
	}
}
func providerTimeMS(raw string) int64 {
	raw = strings.TrimSpace(raw)
	if raw == "" {
		return 0
	}
	for _, layout := range []string{"2006-01-02T15:04:05", "2006-01-02 15:04:05.000", "2006-01-02 15:04:05"} {
		if value, err := time.ParseInLocation(layout, raw, time.Local); err == nil {
			return value.UnixMilli()
		}
	}
	if value, err := time.Parse(time.RFC3339, raw); err == nil {
		return value.UnixMilli()
	}
	return 0
}
func collapseModels(entries []modelEntry) []modelEntry {
	positions := map[string]int{}
	out := make([]modelEntry, 0, len(entries))
	for _, entry := range entries {
		if i, ok := positions[entry.Name]; ok && entry.Name != "" {
			out[i] = entry
			continue
		}
		if entry.Name != "" {
			positions[entry.Name] = len(out)
		}
		out = append(out, entry)
	}
	return out
}
func modelAvailability(entry modelEntry) (bool, string) {
	if entry.Enabled != nil && !*entry.Enabled {
		return false, "disabled"
	}
	if entry.Protocol != "openai-compatible" {
		return false, "unsupported_protocol"
	}
	return true, ""
}
func unwrapContent(content string) string {
	if !strings.Contains(content, "step_name") {
		return content
	}
	var decoded any
	if json.Unmarshal([]byte(content), &decoded) != nil {
		return content
	}
	entries, ok := providerStepEntries(decoded)
	if !ok {
		return content
	}
	var builder strings.Builder
	for _, entry := range entries {
		builder.WriteString("topsailai.")
		builder.WriteString(fmt.Sprint(entry["step_name"]))
		builder.WriteByte('\n')
		delete(entry, "step_name")
		if raw, present := entry["raw_text"]; present {
			builder.WriteString(providerJSONDump(raw))
			builder.WriteByte('\n')
			delete(entry, "raw_text")
		}
		if len(entry) > 0 {
			builder.WriteString(providerJSONDump(entry))
			builder.WriteByte('\n')
		}
		builder.WriteByte('\n')
	}
	return strings.TrimSpace(builder.String())
}

func providerStepEntries(decoded any) ([]map[string]any, bool) {
	candidates, list := decoded.([]any)
	if !list {
		candidates = []any{decoded}
	}
	entries := make([]map[string]any, 0, len(candidates))
	for _, candidate := range candidates {
		entry, record := candidate.(map[string]any)
		if !record {
			return nil, false
		}
		if _, present := entry["step_name"]; !present {
			return nil, false
		}
		entries = append(entries, entry)
	}
	return entries, true
}

func providerJSONDump(value any) string {
	document, err := json.Marshal(value)
	if err != nil {
		return fmt.Sprint(value)
	}
	return string(document)
}

func errorsNew(value string) error { return fmt.Errorf("%s", value) }
