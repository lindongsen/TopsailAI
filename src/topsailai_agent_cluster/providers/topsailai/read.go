package main

import (
	"context"
	"crypto/sha256"
	"encoding/base64"
	"encoding/json"
	"errors"
	"fmt"
	"strconv"
	"strings"
)

const (
	sessionRowProviderKeyPrefix = "session-row:v1:"
	historyProviderKeyPrefix    = "session-history:v1:"
	maxProviderKeyLength        = 256
)

type workspaceResponse struct {
	Items []workspaceItem `json:"items"`
	Total *int            `json:"total"`
}

type workspaceItem struct {
	SessionID         string           `json:"session_id"`
	ProviderRowKey    string           `json:"filename"`
	SessionName       string           `json:"session_name"`
	SessionQualifier  string           `json:"session_qualifier"`
	IsTask            bool             `json:"is_task"`
	ProcessGeneration json.RawMessage  `json:"process_generation"`
	State             string           `json:"state"`
	Status            string           `json:"status"`
	AgentID           string           `json:"agent_id"`
	PID               int64            `json:"pid"`
	ProjectWorkspace  string           `json:"project_workspace"`
	Driver            *workspaceDriver `json:"driver"`
}

type workspaceDriver struct {
	State        string `json:"state"`
	Reason       string `json:"reason"`
	DriverPID    int64  `json:"driver_pid"`
	RunID        string `json:"run_id"`
	Verification string `json:"verification"`
}

type providerSessionTarget struct {
	SessionID      string `json:"session_id"`
	ProviderRowKey string `json:"provider_row_key,omitempty"`
	PID            int64  `json:"pid,omitempty"`
	IsTask         bool   `json:"is_task,omitempty"`
}

type sessionAttributes struct {
	ProviderSessionID        string        `json:"provider_session_id,omitempty"`
	ProviderPID              int64         `json:"provider_pid,omitempty"`
	ProviderDisplayName      string        `json:"provider_display_name,omitempty"`
	ProviderSessionQualifier string        `json:"provider_session_qualifier,omitempty"`
	ProviderProjectWorkspace string        `json:"provider_project_workspace,omitempty"`
	ProviderAgentID          string        `json:"provider_agent_id,omitempty"`
	Drive                    *driveSummary `json:"drive,omitempty"`
}

type driveSummary struct {
	State        string `json:"state"`
	Reason       string `json:"reason,omitempty"`
	DrivePID     int64  `json:"drive_pid,omitempty"`
	RunID        string `json:"run_id,omitempty"`
	Verified     bool   `json:"verified"`
	ObservedAtMS int64  `json:"observed_at_ms"`
}

func (p *provider) discover(ctx context.Context) (*discoveryResult, error) {
	var document workspaceResponse
	if err := runJSON(ctx, p.runner, []string{"workspace", "list", "--json", "--local"}, 1<<20, &document); err != nil {
		return nil, err
	}
	if document.Items == nil {
		return nil, errors.New("workspace response has no items")
	}
	result := &discoveryResult{Observations: make([]providerObservation, 0, len(document.Items)), Complete: true}
	seen := make(map[string]struct{}, len(document.Items))
	for _, item := range document.Items {
		observation, err := p.observation(item)
		if err != nil {
			return nil, err
		}
		if _, exists := seen[observation.ProviderResourceKey]; exists {
			return nil, errors.New("workspace response contains duplicate provider resource key")
		}
		seen[observation.ProviderResourceKey] = struct{}{}
		result.Observations = append(result.Observations, observation)
	}
	if document.Total != nil && *document.Total > len(document.Items) {
		result.Complete = false
	}
	return result, nil
}

func (p *provider) inspect(ctx context.Context, requested *target) (*inspectionResult, error) {
	key, err := validateSessionTarget(requested)
	if err != nil {
		return nil, err
	}
	var document workspaceResponse
	if err := runJSON(ctx, p.runner, []string{"workspace", "list", "--json", "--local"}, 1<<20, &document); err != nil {
		return nil, err
	}
	if document.Items == nil {
		return nil, errors.New("workspace response has no items")
	}
	var found *providerObservation
	for _, item := range document.Items {
		candidate, keyErr := providerSessionKey(item)
		if keyErr != nil {
			return nil, keyErr
		}
		if candidate != key {
			continue
		}
		if found != nil {
			return nil, errors.New("provider resource key matches duplicate workspace rows")
		}
		observation, observationErr := p.observation(item)
		if observationErr != nil {
			return nil, observationErr
		}
		found = &observation
	}
	if found == nil {
		return &inspectionResult{Found: false, Live: false}, nil
	}
	return &inspectionResult{Found: true, Live: found.ProviderGeneration != "", Observation: found}, nil
}

func (p *provider) observation(item workspaceItem) (providerObservation, error) {
	key, err := providerSessionKey(item)
	if err != nil {
		return providerObservation{}, err
	}
	generation, err := workspaceGeneration(item.ProcessGeneration)
	if err != nil {
		return providerObservation{}, err
	}
	now := p.now().UnixMilli()
	state := normalizeSessionState(item.State)
	if item.State == "" {
		state = normalizeSessionState(item.Status)
	}
	reason := ""
	if generation == "" {
		state = "unknown"
		reason = "liveness_unverified"
	}
	attributes, err := json.Marshal(sessionAttributes{
		ProviderSessionID: item.SessionID, ProviderPID: item.PID,
		ProviderDisplayName: item.SessionName, ProviderSessionQualifier: item.SessionQualifier,
		ProviderProjectWorkspace: item.ProjectWorkspace, ProviderAgentID: item.AgentID,
		Drive: mapDrive(item.Driver, now),
	})
	if err != nil {
		return providerObservation{}, err
	}
	return providerObservation{ProviderResourceKey: key, ProviderGeneration: generation, ResourceKind: resourceSession, State: state, StateReason: reason, ObservedAtMS: now, Attributes: attributes}, nil
}

func providerSessionKey(item workspaceItem) (string, error) {
	if strings.TrimSpace(item.SessionID) == "" || strings.TrimSpace(item.ProviderRowKey) == "" {
		return "", errors.New("workspace row requires session_id and filename")
	}
	identity := struct {
		SessionID      string `json:"session_id"`
		ProviderRowKey string `json:"provider_row_key"`
		IsTask         bool   `json:"is_task"`
	}{item.SessionID, item.ProviderRowKey, item.IsTask}
	return stableProviderKey(sessionRowProviderKeyPrefix, identity)
}

func historySessionKey(sessionID string) (string, error) {
	if strings.TrimSpace(sessionID) == "" {
		return "", errors.New("history row requires session_id")
	}
	return stableProviderKey(historyProviderKeyPrefix, struct {
		SessionID string `json:"session_id"`
	}{sessionID})
}

func stableProviderKey(prefix string, identity any) (string, error) {
	document, err := json.Marshal(identity)
	if err != nil {
		return "", fmt.Errorf("encode provider identity: %w", err)
	}
	digest := sha256.Sum256(document)
	key := prefix + base64.RawURLEncoding.EncodeToString(digest[:])
	if len(key) > maxProviderKeyLength {
		return "", errors.New("provider resource key exceeds contract limit")
	}
	return key, nil
}

func validateSessionTarget(value *target) (string, error) {
	if value == nil || value.ResourceKind != resourceSession || value.ProviderResourceKey == "" {
		return "", fmt.Errorf("%w: session target is required", errInvalidRequest)
	}
	if len(value.ProviderResourceKey) > maxProviderKeyLength || !strings.HasPrefix(value.ProviderResourceKey, sessionRowProviderKeyPrefix) {
		return "", fmt.Errorf("%w: invalid TopsailAI session key", errInvalidRequest)
	}
	return value.ProviderResourceKey, nil
}

func (p *provider) resolveWorkspaceTarget(ctx context.Context, value *target) (providerSessionTarget, error) {
	key, err := validateSessionTarget(value)
	if err != nil {
		return providerSessionTarget{}, err
	}
	var document workspaceResponse
	if err := runJSON(ctx, p.runner, []string{"workspace", "list", "--json", "--local"}, 1<<20, &document); err != nil {
		return providerSessionTarget{}, err
	}
	if document.Items == nil {
		return providerSessionTarget{}, errors.New("workspace response has no items")
	}
	var matched *providerSessionTarget
	for _, item := range document.Items {
		candidate, keyErr := providerSessionKey(item)
		if keyErr != nil {
			return providerSessionTarget{}, keyErr
		}
		if candidate != key {
			continue
		}
		if matched != nil {
			return providerSessionTarget{}, errors.New("provider resource key matches duplicate workspace rows")
		}
		resolved := providerSessionTarget{SessionID: item.SessionID, ProviderRowKey: item.ProviderRowKey, PID: item.PID, IsTask: item.IsTask}
		matched = &resolved
	}
	if matched == nil {
		return providerSessionTarget{}, errors.New("provider session row was not found")
	}
	return *matched, nil
}

func (t providerSessionTarget) matches(item workspaceItem) bool {
	return item.SessionID == t.SessionID && item.ProviderRowKey == t.ProviderRowKey && item.PID == t.PID && item.IsTask == t.IsTask
}

func workspaceGeneration(raw json.RawMessage) (string, error) {
	raw = json.RawMessage(strings.TrimSpace(string(raw)))
	if len(raw) == 0 || string(raw) == "null" {
		return "", nil
	}
	var text string
	if raw[0] == '"' {
		if err := json.Unmarshal(raw, &text); err != nil {
			return "", err
		}
		return text, nil
	}
	var number int64
	if err := json.Unmarshal(raw, &number); err != nil {
		return "", fmt.Errorf("generation is not an integer or string")
	}
	return strconv.FormatInt(number, 10), nil
}

func normalizeSessionState(state string) string {
	switch state {
	case "running":
		return "running"
	case "input", "waiting_input":
		return "waiting_input"
	case "idle":
		return "idle"
	default:
		return "unknown"
	}
}

func mapDrive(value *workspaceDriver, observedAtMS int64) *driveSummary {
	if value == nil {
		return nil
	}
	state := "unknown"
	switch value.State {
	case "ON":
		state = "running"
	case "STALE":
		state = "stale"
	case "EXIT":
		state = "exited"
	case "FAIL":
		state = "failed"
	case "-":
		state = "none"
	}
	verified := value.Verification == "verified" && state == "running"
	return &driveSummary{State: state, Reason: boundedString(strings.TrimSpace(value.Reason), 64), DrivePID: value.DriverPID, RunID: value.RunID, Verified: verified, ObservedAtMS: observedAtMS}
}

func boundedString(value string, limit int) string {
	if len(value) <= limit {
		return value
	}
	for limit > 0 && (value[limit]&0xc0) == 0x80 {
		limit--
	}
	return value[:limit]
}
