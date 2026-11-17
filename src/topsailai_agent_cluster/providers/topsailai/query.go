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
	maxMetricsBytes        = 1 << 20
	// maxMetricsBatchBytes bounds the whole-list document a set read collects.
	// It is larger than maxMetricsBytes because one document now carries the
	// runtime record of every row instead of one row, and the bound must not
	// truncate a document the provider legitimately produced.
	maxMetricsBatchBytes = 4 << 20
	// maxMetricsBatchSessions mirrors the Cluster contract bound. The provider is
	// a separate module and does not import Cluster internals, so the value is
	// restated here; the Cluster validates the same bound before any provider
	// process starts, so this copy is a second line of defence rather than the
	// only one.
	maxMetricsBatchSessions = 200
	maxDetailBytes          = 512 << 10
	maxMessageCount         = 10000000
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
	CreateTime       string `json:"create_time"`
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

// messageCountsFact carries the two provider message counts.
//
// The field names are the Cluster's positions, not the provider's layer names.
// The provider reports `user2agent` and `agent2llm`; the adapter maps the first
// onto inbound and the second onto outbound, so the wire contract never encodes
// one provider's internal structure.
type messageCountsFact struct {
	Inbound  int `json:"inbound"`
	Outbound int `json:"outbound"`
}

// metricsResult carries one session's current message counts.
type metricsResult struct {
	ProviderSessionID string            `json:"provider_session_id"`
	Messages          messageCountsFact `json:"messages"`
	ObservedAtMS      int64             `json:"observed_at_ms"`
}

// metricsBatchResult carries the message counts of a bounded set of sessions.
//
// Each member is a metricsResult, so a member that could not be measured is
// reported by its absence rather than by a zero count. The Cluster contract reads
// absence as "not answered", which keeps an unmeasured session distinguishable
// from a session that really has no messages.
type metricsBatchResult struct {
	Results      []metricsResult `json:"results"`
	ObservedAtMS int64           `json:"observed_at_ms"`
}

// detailResult carries one session's provider metadata and runtime document.
//
// Metadata is the provider's own session record, forwarded verbatim. Runtime is
// the reserved seam: this provider reports nothing for it today, so the field is
// omitted rather than filled with a placeholder, and a consumer reads its absence
// as "not reported" instead of "empty".
type detailResult struct {
	ProviderSessionID string `json:"provider_session_id"`
	Metadata          string `json:"metadata"`
	Runtime           string `json:"runtime,omitempty"`
	ObservedAtMS      int64  `json:"observed_at_ms"`
	MetadataTruncated bool   `json:"metadata_truncated,omitempty"`
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
	case querySessionMetrics:
		value, err = p.metrics(ctx, requested, payload)
	case querySessionMetricsBatch:
		value, err = p.metricsBatch(ctx, requested, payload)
	case querySessionDetail:
		value, err = p.detail(ctx, requested, payload)
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
		// The path is validated with the same rule the Cluster applies, so a
		// project this Provider reports is one the Cluster would also accept.
		// Checking only for emptiness let a path with surrounding whitespace or a
		// control character through, which the Cluster refuses.
		if err := validateFolder(project.Path); err != nil {
			return launchOptionsResult{}, fmt.Errorf("project %q path is invalid: %w", project.Name, err)
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
		result.Rows = append(result.Rows, historyRowFact{resourceSession, key, entry.SessionID, entry.SessionName, entry.ProjectWorkspace, boundedString(entry.Task, maxHistoryTaskBytes), entry.Status, providerTimeMS(entry.CreateTime), providerTimeMS(entry.ModifiedTimeRaw), entry.No, resumable, reason})
	}
	return result, nil
}

func (p *provider) models(ctx context.Context, requested *target, raw json.RawMessage) (modelResult, error) {
	var payload struct{}
	if err := decodeStrict(raw, &payload); err != nil {
		return modelResult{}, fmt.Errorf("%w: model.catalog payload", errInvalidRequest)
	}
	resolved, err := p.resolveWorkspaceTarget(ctx, requested)
	if err != nil {
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
	// The registry document names what can be selected, never what is selected, so
	// the current model is a second read. It is deliberately non-fatal: a catalog
	// that cannot prove the current model is still a usable menu, and failing the
	// whole read would take the menu away because one observation was unavailable.
	currentName := p.currentModelName(ctx, resolved.SessionID)
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
		result.Profiles = append(result.Profiles, modelProfileFact{resourceModelProfile, key, boundedString(entry.Name, 256), modelCurrentState(entry.Name, currentName), available, reason})
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

// metrics reads one session's current message counts.
//
// The counts come from the runtime record the provider already collects for
// `workspace list --include-runtime`. That record is built from plain attribute
// reads and collection lengths, so reading it costs one bounded document read
// instead of one control round trip per row.
//
// The previous implementation asked the session's own process for `agent.tokens`,
// which counts tokens across every message body. That work is proportional to the
// conversation size and was paid once per row, so a list of long sessions was
// dominated by counting tokens nobody displayed. The runtime record reports the
// same two layer lengths without that counting.
//
// A session with no live process has no runtime record to report, and that is a
// provider failure rather than a count of zero: a zero is a measured zero, and
// presenting an unmeasured session as empty would state a fact nobody observed.
func (p *provider) metrics(ctx context.Context, requested *target, raw json.RawMessage) (metricsResult, error) {
	sessionID, err := sessionQueryTarget(requested)
	if err != nil {
		return metricsResult{}, err
	}
	var payload struct{}
	if err := decodeStrict(raw, &payload); err != nil {
		return metricsResult{}, fmt.Errorf("%w: session.metrics payload", errInvalidRequest)
	}
	// The session selector is passed to the provider so the document describes
	// only the requested session. Collection runs after that filter, so a row the
	// caller did not ask for is never queried.
	args := []string{"workspace", "list", "--json", "--local", "-s", sessionID, "--include-runtime"}
	var document workspaceResponse
	if err := runJSON(ctx, p.runner, args, maxMetricsBytes, &document); err != nil {
		return metricsResult{}, err
	}
	counts, err := runtimeMessageCounts(document.Items, sessionID)
	if err != nil {
		return metricsResult{}, err
	}
	return metricsResult{ProviderSessionID: sessionID, Messages: counts, ObservedAtMS: p.now().UnixMilli()}, nil
}

// metricsBatch reads the current message counts of a bounded set of sessions.
//
// The set is read with one provider call, because the provider's cost is
// dominated by a fixed task-directory scan that does not depend on how many rows
// are asked about. Measured on this host: one row cost 949 ms and every row cost
// 926 ms, so a per-session read pays the scan once per session while a set read
// pays it once per set.
//
// The session selector is deliberately not passed. `-s` filters the returned rows
// but does not avoid the scan (652 ms for one row against 681 ms for all rows), so
// it would add argv length without saving work. The requested set is applied to
// the returned document instead.
//
// A requested session that cannot be measured is absent from Results rather than
// present with a zero count. A zero is a measured zero, and a session whose
// process never answered has not been measured. The Cluster contract reads
// absence as "not answered", so the two outcomes stay distinguishable and one
// unmeasurable session cannot blank its neighbours.
func (p *provider) metricsBatch(ctx context.Context, requested *target, raw json.RawMessage) (metricsBatchResult, error) {
	if requested != nil {
		return metricsBatchResult{}, fmt.Errorf("%w: session.metrics.batch does not accept a target", errInvalidRequest)
	}
	var payload struct {
		ProviderSessionIDs []string `json:"provider_session_ids"`
	}
	if err := decodeStrict(raw, &payload); err != nil {
		return metricsBatchResult{}, fmt.Errorf("%w: session.metrics.batch payload", errInvalidRequest)
	}
	if len(payload.ProviderSessionIDs) == 0 {
		return metricsBatchResult{}, fmt.Errorf("%w: session.metrics.batch requires at least one session", errInvalidRequest)
	}
	if len(payload.ProviderSessionIDs) > maxMetricsBatchSessions {
		return metricsBatchResult{}, fmt.Errorf("%w: session.metrics.batch accepts at most %d sessions", errInvalidRequest, maxMetricsBatchSessions)
	}
	args := []string{"workspace", "list", "--json", "--local", "--include-runtime"}
	var document workspaceResponse
	if err := runJSON(ctx, p.runner, args, maxMetricsBatchBytes, &document); err != nil {
		return metricsBatchResult{}, err
	}
	observedAtMS := p.now().UnixMilli()
	results := make([]metricsResult, 0, len(payload.ProviderSessionIDs))
	seen := make(map[string]struct{}, len(payload.ProviderSessionIDs))
	for _, sessionID := range payload.ProviderSessionIDs {
		if _, duplicate := seen[sessionID]; duplicate {
			continue
		}
		seen[sessionID] = struct{}{}
		counts, err := runtimeMessageCounts(document.Items, sessionID)
		if err != nil {
			// The reason is dropped here on purpose. The provider result carries no
			// per-member error field, so the only honest way to report an
			// unmeasurable member is to leave it out; the single-session read is the
			// surface that names the reason.
			continue
		}
		results = append(results, metricsResult{
			ProviderSessionID: sessionID,
			Messages:          counts,
			ObservedAtMS:      observedAtMS,
		})
	}
	return metricsBatchResult{Results: results, ObservedAtMS: observedAtMS}, nil
}

// runtimeMessageCounts reads one session's message counts from a workspace
// document that was collected with --include-runtime.
//
// Both the single-session read and the set read call this, so the two
// granularities cannot drift into two behaviours. The error is returned rather
// than collapsed into a boolean because the single-session surface reports the
// specific reason to the operator, while the set read only needs to know that the
// member was not measured.
func runtimeMessageCounts(items []workspaceItem, sessionID string) (messageCountsFact, error) {
	item, found := runtimeRow(items, sessionID)
	if !found {
		// A session the provider does not list is a normal outcome of a read, not
		// a fault, so it keeps its own code and the Cluster maps it to a different
		// answer than a provider failure.
		return messageCountsFact{}, codedError{code: providerSessionNotFoundCode, message: "provider session does not exist"}
	}
	return rowMessageCounts(item)
}

// rowMessageCounts reads one row's message counts from its runtime record.
//
// Discovery and the metrics read both call this, so the periodic report and the
// on-demand read cannot disagree about what a row's counts are. Discovery passes
// the row it already holds, which is why this takes a row rather than a session
// identifier: the selection rule belongs to the caller that knows what it is
// selecting for.
//
// An error means the row was not measured, never that it has no messages. The
// caller must therefore leave the counts absent rather than substitute a zero.
func rowMessageCounts(item workspaceItem) (messageCountsFact, error) {
	// Three conditions reach this point and they are not the same failure, so they
	// must not share one message. A row the provider never described has no runtime
	// record at all; a row whose process refused has a State other than "ok" and
	// carries the provider's own reason in ErrorCode; a row the provider called "ok"
	// but published nothing has a State of "ok" and no Data. Collapsing them into
	// "provider did not report runtime message counts" was true of all three and
	// therefore named none of them, so an operator reading the log could not tell a
	// refused control channel from a provider that simply had not collected the row.
	//
	// The provider's reason is interpolated rather than replaced by a Cluster
	// sentence, because it is the only text that says why the read was refused. It
	// is bounded provider text, not a payload, so it is safe to surface.
	if item.Runtime == nil {
		return messageCountsFact{}, errorsNew("provider did not report runtime message counts")
	}
	if item.Runtime.State != "ok" {
		if item.Runtime.ErrorCode != "" {
			return messageCountsFact{}, errorsNew(fmt.Sprintf(
				"provider runtime state %q refused the read: %s", item.Runtime.State, item.Runtime.ErrorCode))
		}
		return messageCountsFact{}, errorsNew(fmt.Sprintf(
			"provider runtime state %q refused the read without a reason", item.Runtime.State))
	}
	if item.Runtime.Data == nil {
		return messageCountsFact{}, errorsNew("provider did not report runtime message counts")
	}
	report := item.Runtime.Data
	if !report.OK {
		return messageCountsFact{}, errorsNew("provider reported no active agent")
	}
	// The provider's own layer names are mapped onto the Cluster's two positions
	// here and nowhere else. The human listed user2agent first, so inbound is the
	// operator's side and outbound is the model's side.
	counts := messageCountsFact{Inbound: report.User2Agent.Messages, Outbound: report.Agent2LLM.Messages}
	if counts.Inbound < 0 || counts.Outbound < 0 || counts.Inbound > maxMessageCount || counts.Outbound > maxMessageCount {
		return messageCountsFact{}, errorsNew("provider message count is out of range")
	}
	return counts, nil
}

// runtimeRow selects the row that describes the requested session.
//
// A session and its task children share one session identifier, but only the
// session row owns the control channel: a task row is a child process log whose
// runtime record is reported as unsupported. Selecting a task row would therefore
// report "no runtime data" for a session that answered perfectly well, so a
// non-task row always wins when both are present.
func runtimeRow(items []workspaceItem, sessionID string) (workspaceItem, bool) {
	var fallback workspaceItem
	var hasFallback bool
	for _, item := range items {
		if item.SessionID != sessionID {
			continue
		}
		if !item.IsTask {
			return item, true
		}
		if !hasFallback {
			fallback, hasFallback = item, true
		}
	}
	return fallback, hasFallback
}

// detail reads one session's provider metadata and runtime document.
//
// Metadata is the provider's own `session info --json` record, forwarded verbatim.
// The Cluster deliberately does not model that record: it is provider detail, it
// changes when the provider changes, and a Cluster type built from its fields
// would have to change with it. Forwarding the document keeps the surface honest
// and lets a second provider report a different record without a contract change.
//
// Runtime is the reserved seam. This provider reports nothing for it today, so the
// field is left empty and the surface says it was not reported. Filling it later
// is a provider change only.
func (p *provider) detail(ctx context.Context, requested *target, raw json.RawMessage) (detailResult, error) {
	sessionID, err := sessionQueryTarget(requested)
	if err != nil {
		return detailResult{}, err
	}
	var payload struct{}
	if err := decodeStrict(raw, &payload); err != nil {
		return detailResult{}, fmt.Errorf("%w: session.detail payload", errInvalidRequest)
	}
	stdout, stderr, runErr := p.runner.Run(ctx, []string{"session", "info", sessionID, "--json"}, nil)
	if len(stdout) > maxDetailBytes {
		return detailResult{}, errorsNew("provider session record exceeds the detail bound")
	}
	// The provider prints its own not-found document on stdout and exits non-zero,
	// so the document is inspected before the exit status. Reading the status first
	// would report a missing session as a provider failure.
	var probe struct {
		ErrorCode string `json:"error_code"`
	}
	if len(stdout) > 0 {
		if err := decodeJSONDocument(stdout, &probe, false); err != nil {
			if runErr != nil {
				return detailResult{}, fmt.Errorf("TopsailAI CLI failed: %w: %s", runErr, boundedText(stderr, 4096))
			}
			return detailResult{}, fmt.Errorf("decode TopsailAI CLI response: %w", err)
		}
	}
	if probe.ErrorCode == providerSessionNotFoundCode {
		return detailResult{}, codedError{code: providerSessionNotFoundCode, message: "provider session does not exist"}
	}
	if runErr != nil {
		return detailResult{}, fmt.Errorf("TopsailAI CLI failed: %w: %s", runErr, boundedText(stderr, 4096))
	}
	if len(stdout) == 0 {
		return detailResult{}, errorsNew("provider returned no session record")
	}
	return detailResult{ProviderSessionID: sessionID, Metadata: string(stdout), ObservedAtMS: p.now().UnixMilli()}, nil
}

// sessionQueryTarget extracts the provider session identifier from a session-scoped
// query target.
//
// Both new reads address a session by the provider's own identifier, exactly as
// session.messages does, because a session with no live process is absent from the
// inventory and therefore has no Cluster resource ID. The key is validated here so
// an empty or oversized identifier fails before any provider process starts.
func sessionQueryTarget(requested *target) (string, error) {
	if requested == nil || requested.ResourceKind != resourceSession || strings.TrimSpace(requested.ProviderResourceKey) == "" || len(requested.ProviderResourceKey) > maxProviderKeyLength {
		return "", fmt.Errorf("%w: provider session ID target is required", errInvalidRequest)
	}
	return requested.ProviderResourceKey, nil
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

// unwrapContent converts one stored conversation body into readable text.
//
// The provider stores a step record as a JSON object or array carrying a step name
// and the step body, so the body is unwrapped here rather than in the renderer:
// this record shape is provider detail, and the renderer must stay generic.
//
// A body that is not a step record is returned unchanged, so nothing is lost.
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
			builder.WriteString(providerStepText(raw))
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

// providerStepText renders one step body as the text it holds.
//
// The provider stores the body as a JSON string, so marshalling it would produce a
// quoted, escaped string: every real newline becomes the two characters \n and the
// whole body collapses onto one line, which is unreadable for a multi-line answer.
// A string is therefore written verbatim, and only a non-string value keeps the JSON
// form, because such a value has no plain-text form to prefer.
func providerStepText(value any) string {
	if text, ok := value.(string); ok {
		return text
	}
	return providerJSONDump(value)
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
