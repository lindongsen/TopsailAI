package endpointstorage

import (
	"context"
	"fmt"
)

// ExpireSourceSnapshots deletes source cache whose latest successful observation,
// or update time when it never succeeded, is older than cutoffMS. Resource
// mappings and command evidence are deliberately retained because they are not
// cache and preserve stable public identity and execution history.
func (s *Store) ExpireSourceSnapshots(ctx context.Context, cutoffMS int64) ([]string, error) {
	if cutoffMS < 1 {
		return nil, fmt.Errorf("source cache expiry cutoff must be positive")
	}
	tx, err := s.db.BeginTx(ctx, nil)
	if err != nil {
		return nil, fmt.Errorf("begin source cache expiry: %w", err)
	}
	defer tx.Rollback()
	rows, err := tx.QueryContext(ctx, `SELECT adapter_id FROM source_cache WHERE COALESCE(last_success_at_ms, update_at_ms) < ? ORDER BY adapter_id`, cutoffMS)
	if err != nil {
		return nil, fmt.Errorf("select expired source cache: %w", err)
	}
	var adapterIDs []string
	for rows.Next() {
		var adapterID string
		if err := rows.Scan(&adapterID); err != nil {
			rows.Close()
			return nil, fmt.Errorf("scan expired source cache: %w", err)
		}
		adapterIDs = append(adapterIDs, adapterID)
	}
	if err := rows.Close(); err != nil {
		return nil, fmt.Errorf("close expired source cache rows: %w", err)
	}
	if err := rows.Err(); err != nil {
		return nil, fmt.Errorf("iterate expired source cache: %w", err)
	}
	if len(adapterIDs) > 0 {
		if _, err := tx.ExecContext(ctx, `DELETE FROM source_cache WHERE COALESCE(last_success_at_ms, update_at_ms) < ?`, cutoffMS); err != nil {
			return nil, fmt.Errorf("delete expired source cache: %w", err)
		}
	}
	if err := tx.Commit(); err != nil {
		return nil, fmt.Errorf("commit source cache expiry: %w", err)
	}
	return adapterIDs, nil
}
