package topsailai

import (
	"context"
	"encoding/json"
	"fmt"
	"strings"
	"time"
	"unicode/utf8"

	"topsailai_agent_cluster/internal/protocol"
)

// historyEntry mirrors one row of the provider's `project list_sessions --json`
// document. The provider reports nine fields; only these are consumed.
type historyEntry struct {
	SessionID        string `json:"session_id"`
	SessionName      string `json:"session_name"`
	ProjectWorkspace string `json:"project_workspace"`
	ModifiedTimeRaw  string `json:"modified_time_raw"`
	CreateTimeRaw    string `json:"create_time_raw"`
	Task             string `json:"task"`
	No               int    `json:"no"`
	ModifiedTime     string `json:"modified_time"`
	Status           string `json:"status"`
}

// providerHistoryRowCap is the row cap the provider applies to its own
// `project list_sessions` surface. The provider hardcodes this window and offers
// no way to ask for one more row, so the adapter cannot distinguish "exactly this
// many sessions exist" from "the provider stopped at its cap".
//
// The ambiguity is resolved in the safe direction: a full window is reported as
// truncated. Claiming completeness when the provider may have withheld rows would
// present a bounded window as a complete history, which is the failure this field
// exists to prevent. The opposite error merely tells the operator that older
// sessions may exist when none do.
const providerHistoryRowCap = 30

// History lists provider session history without mutation.
//
// The provider's own row cap is an intentional product decision, so this method
// never paginates around it and never presents the result as a complete history.
// The adapter owns the first-line resumability verdict because it is the only
// layer that knows what a provider status word means.
func (a *Adapter) History(ctx context.Context, query protocol.HistoryQuery) (protocol.HistoryResult, error) {
	output, err := a.run(ctx, []string{"project", "list_sessions", "--json"}, nil)
	if err != nil {
		return protocol.HistoryResult{}, err
	}
	if len(output) > protocol.MaxHistoryBytes {
		return protocol.HistoryResult{ErrorCode: protocol.HistoryResponseTooLarge}, fmt.Errorf("history response exceeds byte limit")
	}
	var entries []historyEntry
	if err := json.Unmarshal(output, &entries); err != nil {
		return protocol.HistoryResult{}, fmt.Errorf("decode history: %w", err)
	}
	if len(entries) > protocol.MaxHistoryRows {
		return protocol.HistoryResult{ErrorCode: protocol.HistoryResponseTooLarge}, fmt.Errorf("history row count exceeds limit")
	}
	// The provider cap is judged before the caller's own limit is applied,
	// because a narrowed view must not be mistaken for a complete provider answer.
	truncated := len(entries) >= providerHistoryRowCap
	limit := query.Limit
	if limit > 0 && limit < len(entries) {
		entries = entries[:limit]
	}
	nowMS := time.Now().UnixMilli()
	result := protocol.HistoryResult{Rows: make([]protocol.HistoryRow, 0, len(entries)), ObservedAtMS: nowMS, Truncated: truncated}
	for _, entry := range entries {
		if entry.SessionID == "" {
			continue
		}
		// The opaque handle is minted here, inside the Endpoint, so a resume
		// request can address this row without naming a provider key or an
		// adapter. A mapping failure fails the whole read instead of publishing
		// an unaddressable row, because such a row would look selectable and
		// then fail at dispatch.
		resourceID, err := a.resourceID(ctx, entry.SessionID)
		if err != nil {
			return protocol.HistoryResult{}, fmt.Errorf("map history resource: %w", err)
		}
		row := protocol.HistoryRow{
			ProviderSessionID: entry.SessionID,
			ResourceID:        resourceID,
			DisplayName:       entry.SessionName,
			ProjectWorkspace:  entry.ProjectWorkspace,
			Task:              boundedHistoryTask(entry.Task),
			ProviderStatus:    entry.Status,
			CreatedAtMS:       historyTimeMS(entry.CreateTimeRaw),
			ModifiedAtMS:      historyTimeMS(entry.ModifiedTimeRaw),
			ProviderNo:        entry.No,
		}
		row.Resumable, row.ResumeBlockedReason = historyResumability(entry.Status)
		result.Rows = append(result.Rows, row)
	}
	return result, nil
}

// historyResumability is the adapter's first-line verdict.
//
// Only an explicitly idle session is a resume candidate. An unrecognized status
// word is never resumable: presenting an unknown state as resumable would let an
// operator resume a session that may still be running, and the cluster must not
// guess on the provider's behalf.
func historyResumability(status string) (bool, string) {
	switch strings.TrimSpace(status) {
	case "Idle":
		return true, ""
	case "Running":
		return false, protocol.ResumeBlockedProviderRunning
	default:
		return false, protocol.ResumeBlockedRecordIncomplete
	}
}

// boundedHistoryTask keeps one task text inside the accepted bound. A task that
// exceeds the bound is truncated rather than dropped, because the row is still a
// valid history record and the operator needs to see that it exists.
func boundedHistoryTask(task string) string {
	if !utf8.ValidString(task) {
		return ""
	}
	if len(task) <= protocol.MaxHistoryTaskBytes {
		return task
	}
	cut := protocol.MaxHistoryTaskBytes
	for cut > 0 && !utf8.RuneStart(task[cut]) {
		cut--
	}
	return task[:cut]
}

// historyTimeMS converts one provider timestamp to UTC epoch milliseconds.
//
// The provider emits local wall-clock time without a zone, because it formats a
// filesystem modification time with datetime.fromtimestamp(...).isoformat(). The
// value is therefore interpreted in the endpoint's local zone, which is the zone
// the provider ran in. An unparsable value yields zero rather than a fabricated
// instant, so a missing time is never presented as a real observation.
func historyTimeMS(raw string) int64 {
	raw = strings.TrimSpace(raw)
	if raw == "" {
		return 0
	}
	if parsed, err := time.ParseInLocation("2006-01-02T15:04:05", raw, time.Local); err == nil {
		return parsed.UnixMilli()
	}
	if parsed, err := time.Parse(time.RFC3339, raw); err == nil {
		return parsed.UnixMilli()
	}
	return 0
}
