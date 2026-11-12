package serverstorage

import (
	"context"
	"database/sql"
	"encoding/json"
	"fmt"

	"topsailai_agent_cluster/internal/protocol"
)

// ReplaceInventory atomically replaces one Endpoint's latest report if newer.
func (s *Store) ReplaceInventory(ctx context.Context, endpointID string, report protocol.InventoryReport, receivedAtMS int64) error {
	_, _, _, err := s.ReplaceInventoryCommitted(ctx, endpointID, report, receivedAtMS)
	return err
}

// ReplaceInventoryCommitted returns the committed revision, whether this call
// changed the row, and whether committed storage represents the submitted report.
func (s *Store) ReplaceInventoryCommitted(ctx context.Context, endpointID string, report protocol.InventoryReport, receivedAtMS int64) (int64, bool, bool, error) {
	if endpointID == "" {
		return 0, false, false, fmt.Errorf("endpoint ID is required")
	}
	if err := report.Validate(); err != nil {
		return 0, false, false, err
	}
	payload, err := json.Marshal(report)
	if err != nil {
		return 0, false, false, fmt.Errorf("marshal inventory: %w", err)
	}
	changed := false
	err = s.withTransaction(ctx, "inventory replacement", func(conn *sql.Conn) error {
		result, err := conn.ExecContext(ctx, `INSERT INTO endpoint_session_state(endpoint_id, schema_version, source_generation, snapshot_revision, observed_at_ms, received_at_ms, sessions_json, create_at_ms, update_at_ms) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(endpoint_id) DO UPDATE SET schema_version=excluded.schema_version, source_generation=excluded.source_generation, snapshot_revision=excluded.snapshot_revision, observed_at_ms=excluded.observed_at_ms, received_at_ms=excluded.received_at_ms, sessions_json=excluded.sessions_json, update_at_ms=excluded.update_at_ms WHERE excluded.observed_at_ms > endpoint_session_state.observed_at_ms OR (excluded.observed_at_ms = endpoint_session_state.observed_at_ms AND excluded.snapshot_revision > endpoint_session_state.snapshot_revision)`, endpointID, report.SchemaVersion, report.SourceGeneration, report.SnapshotRevision, report.ObservedAtMS, receivedAtMS, payload, receivedAtMS, receivedAtMS)
		if err != nil {
			return err
		}
		affected, err := result.RowsAffected()
		if err != nil {
			return err
		}
		changed = affected > 0
		return nil
	})
	if err != nil {
		return 0, false, false, err
	}
	if changed {
		return report.SnapshotRevision, true, true, nil
	}
	var committed int64
	var committedPayload []byte
	if err := s.db.QueryRowContext(ctx, `SELECT snapshot_revision, sessions_json FROM endpoint_session_state WHERE endpoint_id = ?`, endpointID).Scan(&committed, &committedPayload); err != nil {
		return 0, false, false, err
	}
	represented := committed > report.SnapshotRevision || (committed == report.SnapshotRevision && string(committedPayload) == string(payload))
	return committed, false, represented, nil
}
