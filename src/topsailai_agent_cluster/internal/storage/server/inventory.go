package serverstorage

import (
	"context"
	"encoding/json"
	"fmt"

	"topsailai_agent_cluster/internal/protocol"
)

// ReplaceInventory atomically replaces one Endpoint's latest report if newer.
func (s *Store) ReplaceInventory(ctx context.Context, endpointID string, report protocol.InventoryReport, receivedAtMS int64) error {
	if endpointID == "" {
		return fmt.Errorf("endpoint ID is required")
	}
	if err := report.Validate(); err != nil {
		return err
	}
	payload, err := json.Marshal(report)
	if err != nil {
		return fmt.Errorf("marshal inventory: %w", err)
	}
	tx, err := s.db.BeginTx(ctx, nil)
	if err != nil {
		return err
	}
	defer tx.Rollback()
	result, err := tx.ExecContext(ctx, `INSERT INTO endpoint_session_state(endpoint_id, schema_version, source_generation, snapshot_revision, observed_at_ms, received_at_ms, sessions_json, create_at_ms, update_at_ms) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(endpoint_id) DO UPDATE SET schema_version=excluded.schema_version, source_generation=excluded.source_generation, snapshot_revision=excluded.snapshot_revision, observed_at_ms=excluded.observed_at_ms, received_at_ms=excluded.received_at_ms, sessions_json=excluded.sessions_json, update_at_ms=excluded.update_at_ms WHERE excluded.observed_at_ms > endpoint_session_state.observed_at_ms OR (excluded.observed_at_ms = endpoint_session_state.observed_at_ms AND excluded.snapshot_revision > endpoint_session_state.snapshot_revision)`, endpointID, report.SchemaVersion, report.SourceGeneration, report.SnapshotRevision, report.ObservedAtMS, receivedAtMS, payload, receivedAtMS, receivedAtMS)
	if err != nil {
		return err
	}
	if affected, err := result.RowsAffected(); err != nil {
		return err
	} else if affected == 0 {
		return nil
	}
	return tx.Commit()
}
