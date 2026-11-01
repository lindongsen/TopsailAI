package endpointstorage

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"

	"topsailai_agent_cluster/internal/protocol"
)

// SourceSnapshot is one Adapter's latest known collection state.
type SourceSnapshot struct {
	AdapterID        string
	ProviderType     string
	DisplayName      string
	Version          string
	Health           string
	Capabilities     protocol.CapabilityDescriptor
	Sessions         []protocol.Session
	ReportComplete   bool
	CollectionStatus string
	LastAttemptAtMS  int64
	LastSuccessAtMS  *int64
	DataKnown        bool
	Stale            bool
	ErrorCode        string
	ErrorMessage     string
}

// ApplySourceSnapshot stores a successful complete result or preserves prior data on failure.
func (s *Store) ApplySourceSnapshot(ctx context.Context, snapshot SourceSnapshot, nowMS int64) error {
	if snapshot.AdapterID == "" || snapshot.ProviderType == "" || snapshot.LastAttemptAtMS < 1 || nowMS < 1 {
		return errors.New("source identity and timestamps are required")
	}
	if snapshot.CollectionStatus == "" {
		return errors.New("collection status is required")
	}
	data, err := json.Marshal(snapshot.Sessions)
	if err != nil {
		return fmt.Errorf("marshal source sessions: %w", err)
	}
	_, err = s.db.ExecContext(ctx, `INSERT INTO source_cache(adapter_id, provider_type, display_name, version, health, sessions_json, report_complete, collection_status, last_attempt_at_ms, last_success_at_ms, data_known, stale, error_code, error_message, update_at_ms) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(adapter_id) DO UPDATE SET provider_type=excluded.provider_type, display_name=excluded.display_name, version=excluded.version, health=excluded.health, sessions_json=CASE WHEN excluded.data_known=1 AND excluded.report_complete=1 THEN excluded.sessions_json ELSE source_cache.sessions_json END, report_complete=excluded.report_complete, collection_status=excluded.collection_status, last_attempt_at_ms=excluded.last_attempt_at_ms, last_success_at_ms=COALESCE(excluded.last_success_at_ms, source_cache.last_success_at_ms), data_known=excluded.data_known, stale=excluded.stale, error_code=excluded.error_code, error_message=excluded.error_message, update_at_ms=excluded.update_at_ms`, snapshot.AdapterID, snapshot.ProviderType, snapshot.DisplayName, snapshot.Version, snapshot.Health, data, boolInt(snapshot.ReportComplete), snapshot.CollectionStatus, snapshot.LastAttemptAtMS, nullableMS(snapshot.LastSuccessAtMS), boolInt(snapshot.DataKnown), boolInt(snapshot.Stale), snapshot.ErrorCode, snapshot.ErrorMessage, nowMS)
	if err != nil {
		return fmt.Errorf("store source snapshot: %w", err)
	}
	return nil
}

// ListSourceSnapshots loads all persisted source states after a process restart.
func (s *Store) ListSourceSnapshots(ctx context.Context) ([]SourceSnapshot, error) {
	rows, err := s.db.QueryContext(ctx, `SELECT adapter_id, provider_type, display_name, version, health, sessions_json, report_complete, collection_status, last_attempt_at_ms, last_success_at_ms, data_known, stale, COALESCE(error_code, ''), COALESCE(error_message, '') FROM source_cache ORDER BY adapter_id`)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	var result []SourceSnapshot
	for rows.Next() {
		var item SourceSnapshot
		var data string
		var complete, known, stale int
		var successMS *int64
		if err := rows.Scan(&item.AdapterID, &item.ProviderType, &item.DisplayName, &item.Version, &item.Health, &data, &complete, &item.CollectionStatus, &item.LastAttemptAtMS, &successMS, &known, &stale, &item.ErrorCode, &item.ErrorMessage); err != nil {
			return nil, err
		}
		if err := json.Unmarshal([]byte(data), &item.Sessions); err != nil {
			return nil, fmt.Errorf("decode source %q: %w", item.AdapterID, err)
		}
		item.ReportComplete = complete != 0
		item.LastSuccessAtMS = successMS
		item.DataKnown = known != 0
		item.Stale = stale != 0
		result = append(result, item)
	}
	return result, rows.Err()
}

func boolInt(value bool) int {
	if value {
		return 1
	}
	return 0
}

func nullableMS(value *int64) any {
	if value == nil {
		return nil
	}
	return *value
}
