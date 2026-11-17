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
	sessionProviderKeyPrefix    = "session:v1:"
	maxProviderKeyLength        = 256
)

type workspaceResponse struct {
	Items []workspaceItem `json:"items"`
	Total *int            `json:"total"`
}

type workspaceItem struct {
	SessionID         string            `json:"session_id"`
	ProviderRowKey    string            `json:"filename"`
	SessionName       string            `json:"session_name"`
	SessionQualifier  string            `json:"session_qualifier"`
	IsTask            bool              `json:"is_task"`
	ProcessGeneration json.RawMessage   `json:"process_generation"`
	State             string            `json:"state"`
	Status            string            `json:"status"`
	AgentID           string            `json:"agent_id"`
	PID               int64             `json:"pid"`
	ProjectWorkspace  string            `json:"project_workspace"`
	Pwd               string            `json:"pwd"`
	Driver            *workspaceDriver  `json:"driver"`
	Runtime           *workspaceRuntime `json:"runtime"`
}

// workspaceRuntime is one row's runtime record as the provider collected it.
//
// The record is an envelope, not the facts themselves: State says whether the
// row's process answered at all, and Data carries the answer. A row that was
// never asked, or whose process refused, has a State other than "ok" and no
// Data, so a reader must check State before trusting Data. Treating a missing
// Data as zero counts would state a measurement nobody made.
type workspaceRuntime struct {
	State     string        `json:"state"`
	ErrorCode string        `json:"error_code"`
	PID       int64         `json:"pid"`
	Data      *runtimeFacts `json:"data"`
}

// runtimeFacts is the directly readable fact set the provider publishes.
//
// Only the two message layers are modelled here, because they are the only
// fields this provider reads. The provider's document carries more, and adding a
// field here is a deliberate act rather than an automatic consequence of the
// provider growing.
type runtimeFacts struct {
	OK        bool `json:"ok"`
	Agent2LLM struct {
		Messages int `json:"messages"`
	} `json:"agent2llm"`
	User2Agent struct {
		Messages int `json:"messages"`
	} `json:"user2agent"`
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
	ProviderPwd              string        `json:"provider_pwd,omitempty"`
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
			// One unmappable row must not discard the rows that did map. Returning
			// the error aborted the whole inventory, so a single unattributable
			// provider file made every healthy session disappear and the Endpoint
			// reported the node as failed. The cycle is marked incomplete instead,
			// which publishes the observed rows as a partial report and keeps the
			// failure visible.
			result.Complete = false
			continue
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

// inspect revalidates one session target against the provider workspace.
//
// --local is deliberately NOT passed here, unlike discover and the mutation
// authority read. The inventory lists only what this Endpoint can control, so it
// stays local. Inspect must not, because resume authorizes on the absence of a
// live target: a session recorded on another machine is absent from a --local
// read, so --local would report it as not found and refuse the resume the
// operator asked for. A task directory shared between hosts is exactly the case
// where resuming another host's session is intended, and the provider applies no
// host filter to resume. Such a row still reports an empty generation, because
// this host cannot verify a process it cannot see, so it is found but not live.
//
// The targeted `-s <session_id>` form the old adapter used is unavailable here:
// a mapping key is a digest of the session identity, so the identifier cannot be
// recovered from the key. The full scan is therefore the only correct read, and
// it costs one workspace listing per inspect instead of one targeted listing.
func (p *provider) inspect(ctx context.Context, requested *target) (*inspectionResult, error) {
	key, err := validateSessionTarget(requested)
	if err != nil {
		return nil, err
	}
	var document workspaceResponse
	if err := runJSON(ctx, p.runner, []string{"workspace", "list", "--json"}, 1<<20, &document); err != nil {
		return nil, err
	}
	if document.Items == nil {
		return nil, errors.New("workspace response has no items")
	}
	scoped := sessionScopedKey(key)
	var found *providerObservation
	var live *providerObservation
	for _, item := range document.Items {
		matched, matchErr := matchesSessionKey(key, item)
		if matchErr != nil {
			return nil, matchErr
		}
		if !matched {
			continue
		}
		observation, observationErr := p.observation(item)
		if observationErr != nil {
			return nil, observationErr
		}
		if found != nil && !scoped {
			return nil, errors.New("provider resource key matches duplicate workspace rows")
		}
		if found == nil {
			found = &observation
		}
		// A live row decides liveness, so the scan must not stop at the first
		// non-live row: returning early would hide a live sibling and let resume
		// target a session that is still running.
		if observation.ProviderGeneration != "" && live == nil {
			live = &observation
		}
	}
	if live != nil {
		return &inspectionResult{Found: true, Live: true, Observation: live}, nil
	}
	if found != nil {
		return &inspectionResult{Found: true, Live: false, Observation: found}, nil
	}
	return &inspectionResult{Found: false, Live: false}, nil
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
		ProviderProjectWorkspace: item.ProjectWorkspace, ProviderPwd: item.Pwd, ProviderAgentID: item.AgentID,
		Drive: mapDrive(item.Driver, now),
	})
	if err != nil {
		return providerObservation{}, err
	}
	return providerObservation{ProviderResourceKey: key, ProviderGeneration: generation, ResourceKind: resourceSession, State: state, StateReason: reason, ObservedAtMS: now, Attributes: attributes}, nil
}

// providerSessionKey mints the mapping key for one workspace row.
//
// The filename is the only identity a row must carry. A row may legitimately
// report no session identifier: the provider publishes a stdout file it cannot
// attribute to a session, and refusing such a row aborted the whole inventory
// over one unattributable file. The session identifier stays inside the digest
// when it is present, so a row that has one keeps exactly the key it had
// before, and an unattributed row still receives a stable key of its own.
func providerSessionKey(item workspaceItem) (string, error) {
	if strings.TrimSpace(item.ProviderRowKey) == "" {
		return "", errors.New("workspace row requires filename")
	}
	identity := struct {
		SessionID      string `json:"session_id"`
		ProviderRowKey string `json:"provider_row_key"`
		IsTask         bool   `json:"is_task"`
	}{item.SessionID, item.ProviderRowKey, item.IsTask}
	return stableProviderKey(sessionRowProviderKeyPrefix, identity)
}

// historySessionKey mints the mapping key for one history row.
//
// A history row reports no row key, PID or task flag, so it cannot claim to be one
// particular workspace row. It names a session, which is exactly what the
// session-scoped key names, so the two paths share one minter: a history row and an
// operator-typed handle for the same session resolve to the same resource ID. Two
// minters would give one session two identities, and a resume from history would
// then address a different resource than a resume by handle.
func historySessionKey(sessionID string) (string, error) {
	if strings.TrimSpace(sessionID) == "" {
		return "", errors.New("history row requires session_id")
	}
	return sessionProviderKey(sessionID)
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

// validateSessionTarget accepts both session selectors this Provider mints.
//
// A row key names one workspace row and a session key names the session itself.
// Both are TopsailAI session selectors, so both are valid targets; the difference
// is carried by the prefix and decided by sessionScopedKey, because the keys are
// digests and cannot be decoded back into a flag.
func validateSessionTarget(value *target) (string, error) {
	if value == nil || value.ResourceKind != resourceSession || value.ProviderResourceKey == "" {
		return "", fmt.Errorf("%w: session target is required", errInvalidRequest)
	}
	if len(value.ProviderResourceKey) > maxProviderKeyLength {
		return "", fmt.Errorf("%w: invalid TopsailAI session key", errInvalidRequest)
	}
	if !strings.HasPrefix(value.ProviderResourceKey, sessionRowProviderKeyPrefix) &&
		!strings.HasPrefix(value.ProviderResourceKey, sessionProviderKeyPrefix) {
		return "", fmt.Errorf("%w: invalid TopsailAI session key", errInvalidRequest)
	}
	return value.ProviderResourceKey, nil
}

// sessionProviderKey encodes a session-scoped mapping key from a provider session
// identifier alone.
//
// It is deliberately distinct from providerSessionKey, which encodes one workspace
// row. One provider session identifier can appear in several independently
// selectable rows, so a handle that names the session must not claim to be one
// particular row. The prefix is separate rather than a flag inside the document,
// because both keys are digests and a decoder cannot read a flag it cannot reach.
func sessionProviderKey(sessionID string) (string, error) {
	if strings.TrimSpace(sessionID) == "" {
		return "", errors.New("provider session handle is empty")
	}
	return stableProviderKey(sessionProviderKeyPrefix, struct {
		SessionID string `json:"session_id"`
	}{sessionID})
}

// sessionScopedKey reports whether one mapping key names a session rather than a row.
func sessionScopedKey(key string) bool {
	return strings.HasPrefix(key, sessionProviderKeyPrefix)
}

// matchesSessionKey reports whether one workspace row belongs to the target key.
//
// A session-scoped key matches every row of its session, which is the correct
// reading for a target the operator named by session identifier: the operator did
// not choose a row. A row-scoped key still matches exactly one row.
//
// A row that reports no session identifier cannot belong to a session-scoped
// target, so it reports no match. Returning the minter's error instead would let
// one unattributed row abort the resolution of every session-scoped key, which is
// a wider failure than the row itself.
func matchesSessionKey(key string, item workspaceItem) (bool, error) {
	if sessionScopedKey(key) {
		if strings.TrimSpace(item.SessionID) == "" {
			return false, nil
		}
		candidate, err := sessionProviderKey(item.SessionID)
		if err != nil {
			return false, err
		}
		return candidate == key, nil
	}
	candidate, err := providerSessionKey(item)
	if err != nil {
		return false, err
	}
	return candidate == key, nil
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
	scoped := sessionScopedKey(key)
	var found *providerSessionTarget
	var live *providerSessionTarget
	for _, item := range document.Items {
		matched, matchErr := matchesSessionKey(key, item)
		if matchErr != nil {
			return providerSessionTarget{}, matchErr
		}
		if !matched {
			continue
		}
		if found != nil && !scoped {
			return providerSessionTarget{}, errors.New("provider resource key matches duplicate workspace rows")
		}
		resolved := providerSessionTarget{SessionID: item.SessionID, ProviderRowKey: item.ProviderRowKey, PID: item.PID, IsTask: item.IsTask}
		if found == nil {
			found = &resolved
		}
		generation, generationErr := workspaceGeneration(item.ProcessGeneration)
		if generationErr != nil {
			return providerSessionTarget{}, generationErr
		}
		// A row-addressed read follows the live row when the target names a
		// session, because that is the row producing output.
		if generation != "" && live == nil {
			live = &resolved
		}
	}
	if live != nil {
		return *live, nil
	}
	if found == nil {
		return providerSessionTarget{}, errors.New("provider session row was not found")
	}
	return *found, nil
}

// resolvePayload is the frozen resolve payload: one provider session identifier.
type resolvePayload struct {
	Handle string `json:"handle"`
}

// resolveSessionHandle mints the session-scoped mapping key for a handle.
//
// It never asks the provider CLI whether the session exists. The operator named the
// target, so deciding existence here would reject exactly the case this function
// exists for: a session the Endpoint has not discovered yet. Minting is local
// bookkeeping, and the provider CLI remains the only party that answers existence
// when the operation actually reaches it.
func (p *provider) resolveSessionHandle(raw json.RawMessage) (*resolutionResult, error) {
	var payload resolvePayload
	if err := decodeStrict(raw, &payload); err != nil {
		return nil, fmt.Errorf("%w: decode resolve payload: %v", errInvalidRequest, err)
	}
	key, err := sessionProviderKey(payload.Handle)
	if err != nil {
		return nil, fmt.Errorf("%w: %v", errInvalidRequest, err)
	}
	return &resolutionResult{ProviderResourceKey: key, ResourceKind: resourceSession}, nil
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
